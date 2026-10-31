"""Agent loop (D11): model call → tool calls → tool results → model call, until the model
answers [Yao2023]. Yields events for the UI as they happen.

Events:
  tool_call   {id, name, input}
  tool_result {id, name, ok, summary | error, sources: [{index, source, title}]}
  text        {text}                       streamed answer text
  answer      {blocks: [{text, citations}], sources: [{index, source, title, text}]}
  guard       {ungrounded: [numbers]}      answer had numbers no source backs; model asked to fix
  done        {stop_reason, backend, model, usage, rounds}
  error       {message}

Two additions after the stage 8 baseline (D21):
- Retrieve first: backends with `pre_retrieve` (the local model) get the documentation passages
  and the specimen list in the question itself, as in retrieve-then-generate RAG [Lewis2020],
  instead of having to decide to call search_docs. The small model had skipped the search and
  answered from memory.
- Grounding guard: an answer whose numbers are not backed by any source the model was shown is
  sent back once with the list of those numbers. If the corrected answer still has them, the
  answer says so. The check is code, so it does not depend on the model.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field

from cochleahub.assistant.backends import TurnResult
from cochleahub.assistant.grounding import grounded
from cochleahub.assistant.tools import Source, ToolExecutor
from cochleahub.config import settings

CORRECTION = (
    "Check your answer: these numbers do not appear in any CochleaHub source you were given: "
    "{numbers}. Rewrite the answer without them, or call a tool to get the value. Do not use "
    "general knowledge for numbers."
)
UNVERIFIED_NOTE = (
    "\n\nNote: these numbers could not be verified against CochleaHub sources: {numbers}."
)

REFUSAL_TEXT = (
    "The model declined to answer this request. CochleaHub's assistant can show measurements "
    "and explain methods, but cannot help with this question."
)


@dataclass
class Conversation:
    backend: str
    model: str
    messages: list = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)  # every source shown to the model


def add_usage(total: dict, usage: dict) -> None:
    for k, v in usage.items():
        if isinstance(v, int):
            total[k] = total.get(k, 0) + v


def sources_text(sources: list[Source]) -> str:
    return "\n".join(f"{s.title}\n{s.text}" for s in sources)


async def run_tools(executor, conv, calls) -> AsyncIterator[tuple[dict, list]]:
    """Run tool calls concurrently; yield their UI events, then (None, outcomes)."""
    for call in calls:
        yield {"type": "tool_call", "id": call.id, "name": call.name, "input": call.input}, []
    outcomes = await asyncio.gather(
        *(executor.run(c.name, c.input if isinstance(c.input, dict) else {}) for c in calls)
    )
    n = len(conv.sources)
    for call, outcome in zip(calls, outcomes, strict=True):
        shown = []
        for s in outcome.sources:
            shown.append({"index": n, "source": s.source, "title": s.title})
            n += 1
        yield {
            "type": "tool_result", "id": call.id, "name": call.name, "ok": outcome.ok,
            "summary": outcome.summary, "error": outcome.error, "sources": shown,
        }, []
    yield None, outcomes


async def run_turn(
    backend, executor: ToolExecutor, conv: Conversation, question: str
) -> AsyncIterator[dict]:
    context: list[Source] = []
    offset = len(conv.sources)
    if getattr(backend, "pre_retrieve", False):
        from cochleahub.assistant.backends import ToolCall

        calls = [ToolCall(f"pre-{len(conv.messages)}-0", "list_specimens", {}),
                 ToolCall(f"pre-{len(conv.messages)}-1", "search_docs", {"query": question})]
        async for event, outcomes in run_tools(executor, conv, calls):
            if event is not None:
                yield event
        for outcome in outcomes:
            context.extend(outcome.sources)
        conv.sources.extend(context)
    if conv.messages:
        backend.ask(conv.messages, question, context=context, offset=offset)
    else:
        conv.messages = backend.start(question, context=context, offset=offset)

    corrected = False
    blocks: list[dict] = []
    usage: dict = {}
    stop_reason, model = "end_turn", backend.model
    rounds = 0
    for rounds in range(1, settings.assistant_max_tool_rounds + 1):
        result: TurnResult | None = None
        async for event in backend.turn(conv.messages, conv.sources):
            if isinstance(event, TurnResult):
                result = event
            else:
                yield event
        assert result is not None
        add_usage(usage, result.usage)
        model = result.model or model
        stop_reason = result.stop_reason
        # the answer is the last round's text; text before a tool call is narration
        # ("let me look that up") and was already streamed
        blocks = [b for b in result.blocks if b["text"].strip()]

        if stop_reason == "refusal":
            blocks.append({"text": REFUSAL_TEXT, "citations": []})
            break
        if stop_reason == "max_tokens" and result.tool_calls:
            yield {"type": "error", "message": "The answer was cut off before a tool call "
                   "completed; please ask a narrower question."}
            break
        if not result.tool_calls:
            answer = "".join(b["text"] for b in blocks)
            ok, ungrounded = grounded(answer, sources_text(conv.sources), question)
            if ok or not settings.assistant_grounding_guard:
                break
            if not corrected:
                corrected = True
                yield {"type": "guard", "ungrounded": ungrounded}
                backend.ask(conv.messages, CORRECTION.format(
                    numbers=", ".join(f"{v:g}" for v in ungrounded)))
                continue
            blocks.append({"text": UNVERIFIED_NOTE.format(
                numbers=", ".join(f"{v:g}" for v in ungrounded)), "citations": []})
            break

        offset = len(conv.sources)
        async for event, outcomes in run_tools(executor, conv, result.tool_calls):
            if event is not None:
                yield event
        for outcome in outcomes:
            conv.sources.extend(outcome.sources)
        backend.add_tool_results(
            conv.messages, list(zip(result.tool_calls, outcomes, strict=True)), offset
        )
    else:
        yield {"type": "error", "message": f"Stopped after {rounds} tool rounds without an "
               "answer."}
        stop_reason = "max_rounds"

    cited = sorted({i for b in blocks for i in b["citations"]})
    yield {
        "type": "answer",
        "blocks": blocks,
        "sources": [{"index": i, **asdict(conv.sources[i])} for i in cited],
    }
    yield {
        "type": "done", "stop_reason": stop_reason, "backend": backend.name, "model": model,
        "usage": usage, "rounds": rounds,
    }
