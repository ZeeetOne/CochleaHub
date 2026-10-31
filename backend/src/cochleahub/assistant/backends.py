"""LLM backends behind one interface (D11, D20).

- ClaudeBackend: Claude through the Claude API (development) or Amazon Bedrock in an EU region
  (production: requests stay in the operator's AWS account and region). Tool results are sent
  as `search_result` blocks, so citations are produced and located by the API itself.
- LocalBackend: an open-weight model served by Ollama inside the hospital network; nothing
  leaves the machine. Locally deployed open models have been shown to work on clinical text
  while keeping data on premises [Wiest2024]. Citations use [S#] markers that we resolve.

Each backend keeps the conversation in its own message format; a conversation stays on the
backend it started on. `turn()` runs one model call and yields UI events; the agent loop
(agent.py) decides whether to call tools and go round again.
"""

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from cochleahub.assistant.prompts import CLAUDE_SYSTEM, LOCAL_SYSTEM
from cochleahub.assistant.tools import TOOLS, Source, ToolOutcome
from cochleahub.config import settings


@dataclass
class ToolCall:
    id: str
    name: str
    input: Any


@dataclass
class TurnResult:
    """Outcome of one model call."""

    stop_reason: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    # final answer as text blocks, each with the indices (into `sources`) it cites
    blocks: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    model: str = ""


class ClaudeBackend:
    name = "claude"

    def __init__(self, client=None):
        if client is not None:
            self.client = client
        elif settings.llm_provider == "bedrock":
            from anthropic import AsyncAnthropicBedrockMantle

            self.client = AsyncAnthropicBedrockMantle(aws_region=settings.aws_region)
        else:
            from anthropic import AsyncAnthropic

            self.client = AsyncAnthropic(api_key=settings.anthropic_api_key or None)
        self.model = (
            settings.bedrock_model if settings.llm_provider == "bedrock" else settings.llm_model
        )
        # Tool inputs stream as generated; with eager streaming the server no longer validates
        # them, so the executor validates every input before running it (tools.validate).
        self.tools = [{**t, "eager_input_streaming": True} for t in TOOLS]

    pre_retrieve = False  # Claude decides when to search (it does so reliably, D21)

    def start(self, question: str, context=(), offset: int = 0) -> list[dict]:
        return [{"role": "user", "content": question}]

    def ask(self, messages: list[dict], question: str, context=(), offset: int = 0) -> None:
        messages.append({"role": "user", "content": question})

    async def turn(self, messages: list[dict], sources: list[Source]) -> AsyncIterator[dict | TurnResult]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 16000,
            "system": CLAUDE_SYSTEM,
            "tools": self.tools,
            "messages": messages,
            "output_config": {"effort": settings.llm_effort},
            "cache_control": {"type": "ephemeral"},  # system + tools + history are a stable prefix
        }
        if settings.llm_provider == "anthropic":
            # On a safety-classifier decline, the API retries on a fallback model by itself.
            kwargs |= {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        async with self.client.beta.messages.stream(**kwargs) as stream:
            async for event in stream:
                if event.type == "text":
                    yield {"type": "text", "text": event.text}
            message = await stream.get_final_message()

        content = [b.to_dict() for b in message.content]
        messages.append({"role": "assistant", "content": content})
        result = TurnResult(
            stop_reason=message.stop_reason or "end_turn",
            usage=message.usage.to_dict() if message.usage else {},
            model=message.model,
        )
        for b in message.content:
            if b.type == "tool_use":
                result.tool_calls.append(ToolCall(b.id, b.name, b.input))
            elif b.type == "text":
                cited = []
                for c in b.citations or []:
                    if getattr(c, "type", "") == "search_result_location":
                        idx = c.search_result_index
                        if 0 <= idx < len(sources) and idx not in cited:
                            cited.append(idx)
                result.blocks.append({"text": b.text, "citations": cited})
        yield result

    def add_tool_results(
        self, messages: list[dict], results: list[tuple[ToolCall, ToolOutcome]], offset: int = 0
    ) -> None:
        """All results of one turn go back in one user message (parallel tool use).
        `search_result_index` in citations counts every search_result block of the whole
        conversation in order, which is the order of the agent's source list."""
        content = []
        for call, outcome in results:
            if outcome.ok:
                body = [
                    {
                        "type": "search_result",
                        "source": s.source,
                        "title": s.title,
                        "content": [{"type": "text", "text": s.text}],
                        "citations": {"enabled": True},
                    }
                    for s in outcome.sources
                ]
                content.append({"type": "tool_result", "tool_use_id": call.id, "content": body})
            else:
                content.append({
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "is_error": True,
                    "content": [{"type": "text", "text": outcome.error or "error"}],
                })
        messages.append({"role": "user", "content": content})


MARKER = re.compile(r"\[S(\d+)\]")


def strip_reasoning(text: str) -> str:
    """Drop reasoning a model leaked into its answer (`<think>...</think>`)."""
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    return text.strip()


class LocalBackend:
    name = "local"

    def __init__(self, client=None):
        if client is None:
            from ollama import AsyncClient

            client = AsyncClient(host=settings.ollama_url)
        self.client = client
        self.model = settings.local_model
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in TOOLS
        ]

    pre_retrieve = True  # retrieve-then-generate: the small model skipped search_docs (D21)

    def start(self, question: str, context=(), offset: int = 0) -> list[dict]:
        messages = [{"role": "system", "content": LOCAL_SYSTEM}]
        self.ask(messages, question, context, offset)
        return messages

    def ask(self, messages: list[dict], question: str, context=(), offset: int = 0) -> None:
        if context:
            numbered = "\n\n".join(
                f"[S{offset + i + 1}] {s.title}\n{s.text}" for i, s in enumerate(context)
            )
            question = (f"{question}\n\nCochleaHub sources retrieved for this question "
                        f"(cite them as [S#]; call tools for anything they do not cover):"
                        f"\n\n{numbered}")
        messages.append({"role": "user", "content": question})

    async def turn(self, messages: list[dict], sources: list[Source]) -> AsyncIterator[dict | TurnResult]:
        text, calls, usage = "", [], {}
        # think=True makes Ollama return reasoning separately (`message.thinking`), which we
        # drop; with think=False some reasoning models still write it into the answer text.
        # num_ctx: Ollama's default context is smaller than a few tool rounds need, and a
        # prompt longer than the context is silently truncated from the front.
        stream = await self.client.chat(
            model=self.model, messages=messages, tools=self.tools, stream=True, think=True,
            options={"temperature": 0, "num_ctx": settings.local_context_tokens},
        )
        async for chunk in stream:
            msg = chunk.message
            if msg.content:
                text += msg.content
                yield {"type": "text", "text": msg.content}
            calls.extend(msg.tool_calls or [])
            if chunk.done:
                usage = {
                    "input_tokens": chunk.prompt_eval_count or 0,
                    "output_tokens": chunk.eval_count or 0,
                }
        text = strip_reasoning(text)
        assistant: dict[str, Any] = {"role": "assistant", "content": text}
        if calls:
            assistant["tool_calls"] = [
                {"function": {"name": c.function.name, "arguments": dict(c.function.arguments)}}
                for c in calls
            ]
        messages.append(assistant)
        result = TurnResult(
            stop_reason="tool_use" if calls else "end_turn", usage=usage, model=self.model
        )
        for i, c in enumerate(calls):
            result.tool_calls.append(
                ToolCall(f"local-{len(messages)}-{i}", c.function.name, dict(c.function.arguments))
            )
        if text:
            cited = []
            for m in MARKER.findall(text):
                idx = int(m) - 1
                if 0 <= idx < len(sources) and idx not in cited:
                    cited.append(idx)
            result.blocks.append({"text": text, "citations": cited})
        yield result

    def add_tool_results(
        self, messages: list[dict], results: list[tuple[ToolCall, ToolOutcome]], offset: int = 0
    ) -> None:
        """Sources are numbered across the conversation (offset = sources seen before), the
        same order Claude uses for `search_result_index`."""
        n = offset
        for call, outcome in results:
            if outcome.ok:
                parts = []
                for s in outcome.sources:
                    n += 1
                    parts.append(f"[S{n}] {s.title}\n{s.text}")
                body = "\n\n".join(parts)
            else:
                body = json.dumps({"error": outcome.error})
            messages.append({"role": "tool", "tool_name": call.name, "content": body})
