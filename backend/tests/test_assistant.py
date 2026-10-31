"""Assistant: retrieval, tools over the real API routes, the agent loop, citations and the SSE
endpoint. LLMs are replaced by scripted backends; no network."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from cochleahub.api.main import app
from cochleahub.api.routers import assistant as route
from cochleahub.assistant.agent import Conversation, run_turn
from cochleahub.assistant.backends import ClaudeBackend, LocalBackend, ToolCall, TurnResult
from cochleahub.assistant.retrieval import BM25, Chunk, Index, chunk_markdown, rrf, tokenize
from cochleahub.assistant.tools import Source, ToolExecutor, ToolOutcome

V1 = "/api/v1"

# --- retrieval -------------------------------------------------------------------------------


def test_chunks_follow_sections_and_keep_titles():
    md = "# Guide\n\nIntro.\n\n## CT viewer\n\nScroll to change slice.\n\n## Charts\n\nBands.\n"
    chunks = chunk_markdown("docs/g.md", md)
    assert [c.id for c in chunks] == ["docs/g.md#guide", "docs/g.md#ct-viewer", "docs/g.md#charts"]
    assert chunks[1].title == "Guide › CT viewer"


def test_bm25_matches_exact_codes():
    docs = [tokenize("OUT_OF_PUBLISHED_RANGE warning for height"), tokenize("volume of bone")]
    scores = BM25(docs).scores(tokenize("what is OUT_OF_PUBLISHED_RANGE"))
    assert scores[0] > scores[1] == 0


def test_rrf_rewards_agreement_between_rankings():
    fused = rrf([[0, 1, 2], [1, 0, 2]])
    assert fused[0] == fused[1] > fused[2]


def test_lexical_only_index_searches():
    chunks = [Chunk("a#x", "a", "A › CT viewer", "window level with left drag"),
              Chunk("b#y", "b", "B › Volumes", "voxel volume of structures")]
    hits = Index(chunks, None).search("left drag window", k=1)
    assert hits[0].chunk.id == "a#x" and hits[0].bm25_rank == 1


# --- tools over the API ----------------------------------------------------------------------


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def executor(seeded_api):
    index = Index([Chunk("docs/m.md#cochlea", "docs/m.md", "M › Cochlea", "A is the basal "
                         "diameter; values outside the range are a QC warning.")], None)
    return ToolExecutor(index=index)


def test_tool_results_carry_provenance(executor, seeded_api):
    out = run(executor.run("get_cochlea_dimensions", {"specimen_id": "zeta"}))
    assert out.ok and len(out.sources) == 3
    run_id = seeded_api.run_ids["completed"]
    assert all(run_id in s.source for s in out.sources)
    assert "pipeline v0.1.0" in out.sources[0].title
    height = json.loads(out.sources[2].text)
    assert height["dimension"] == "height" and height["in_range"] is False


def test_missing_data_is_an_error_the_model_can_abstain_on(executor):
    out = run(executor.run("get_distances", {"specimen_id": "nope"}))
    assert not out.ok and out.error.startswith("No data: Unknown specimen")
    out = run(executor.run("get_qc_flags", {"specimen_id": "empty"}))
    assert not out.ok and "no completed pipeline run" in out.error
    out = run(executor.run("get_measurements", {"specimen_id": "zeta", "structures": ["Uvula"]}))
    assert not out.ok and "Available: Scala Tympani" in out.error


def test_specimen_id_is_case_insensitive(executor):
    assert run(executor.run("get_distances", {"specimen_id": "ZETA"})).ok


def test_tool_input_is_validated(executor):
    assert "missing required" in run(executor.run("get_distances", {})).error
    bad = run(executor.run("compare_metric", {"metric": "weight"}))
    assert "must be one of" in bad.error


def test_docs_search_returns_passages(executor):
    out = run(executor.run("search_docs", {"query": "basal diameter"}))
    assert out.ok and out.sources[0].source == "docs/m.md#cochlea"


# --- agent loop ------------------------------------------------------------------------------


class ScriptedBackend:
    """Stands in for a model: each turn returns the next scripted TurnResult."""

    name, model = "claude", "scripted"

    def __init__(self, turns):
        self.turns = list(turns)
        self.seen_sources = []

    def start(self, question):
        return [{"role": "user", "content": question}]

    def ask(self, messages, question):
        messages.append({"role": "user", "content": question})

    async def turn(self, messages, sources):
        self.seen_sources.append(len(sources))
        result = self.turns.pop(0)
        for b in result.blocks:
            yield {"type": "text", "text": b["text"]}
        messages.append({"role": "assistant", "content": "…"})
        yield result

    def add_tool_results(self, messages, results, offset=0):
        messages.append({"role": "user", "content": [o.ok for _, o in results]})


def collect(gen):
    async def go():
        return [e async for e in gen]
    return asyncio.run(go())


def test_agent_calls_tools_then_answers_with_citations(executor):
    backend = ScriptedBackend([
        TurnResult("tool_use", [ToolCall("t1", "get_cochlea_dimensions", {"specimen_id": "zeta"}),
                                ToolCall("t2", "get_distances", {"specimen_id": "nope"})]),
        TurnResult("end_turn", blocks=[{"text": "Height is 4.36 mm.", "citations": [2]}],
                   usage={"output_tokens": 7}),
    ])
    conv = Conversation("claude", "scripted")
    events = collect(run_turn(backend, executor, conv, "How tall is the cochlea?"))
    types = [e["type"] for e in events]
    assert types == ["tool_call", "tool_call", "tool_result", "tool_result", "text", "answer",
                     "done"]
    failed = events[3]
    assert failed["ok"] is False and "Unknown specimen" in failed["error"]
    answer = events[5]
    assert answer["sources"][0]["index"] == 2 and "height" in answer["sources"][0]["source"]
    assert events[-1]["rounds"] == 2
    # sources are numbered across the conversation: the second call saw the 3 earlier ones
    assert backend.seen_sources == [0, 3] and len(conv.sources) == 3


def test_agent_stops_after_max_rounds(executor, monkeypatch):
    monkeypatch.setattr("cochleahub.assistant.agent.settings.assistant_max_tool_rounds", 2)
    loop = TurnResult("tool_use", [ToolCall("t", "list_specimens", {})])
    events = collect(run_turn(ScriptedBackend([loop, loop]), executor,
                              Conversation("claude", "s"), "loop"))
    assert any(e["type"] == "error" and "2 tool rounds" in e["message"] for e in events)
    assert events[-1]["stop_reason"] == "max_rounds"


def test_answer_is_the_last_rounds_text(executor):
    backend = ScriptedBackend([
        TurnResult("tool_use", [ToolCall("t", "list_specimens", {})],
                   blocks=[{"text": "Let me check.", "citations": []}]),
        TurnResult("end_turn", blocks=[{"text": "One specimen.", "citations": [0]}]),
    ])
    events = collect(run_turn(backend, executor, Conversation("claude", "s"), "How many?"))
    answer = next(e for e in events if e["type"] == "answer")
    assert [b["text"] for b in answer["blocks"]] == ["One specimen."]


def test_refusal_is_reported(executor):
    events = collect(run_turn(ScriptedBackend([TurnResult("refusal")]), executor,
                              Conversation("claude", "s"), "?"))
    answer = next(e for e in events if e["type"] == "answer")
    assert "declined" in answer["blocks"][0]["text"]


# --- backend message formats -----------------------------------------------------------------


def test_claude_tool_results_are_citable_search_results():
    backend = ClaudeBackend(client=object())
    messages = []
    ok = ToolOutcome(True, [Source("api:/x", "X · run 1", "{}")])
    err = ToolOutcome(False, error="No data: Unknown specimen 'nope'.")
    backend.add_tool_results(messages, [(ToolCall("a", "n", {}), ok), (ToolCall("b", "n", {}), err)])
    [user] = messages
    first, second = user["content"]
    assert first["content"][0]["type"] == "search_result"
    assert first["content"][0]["citations"] == {"enabled": True}
    assert second["is_error"] is True


class FakeOllama:
    def __init__(self, chunks):
        self.chunks = chunks

    async def chat(self, **kwargs):
        async def gen():
            for c in self.chunks:
                yield c
        return gen()


def chunk(content="", tool_calls=None, done=False):
    return SimpleNamespace(
        message=SimpleNamespace(content=content, tool_calls=tool_calls),
        done=done, prompt_eval_count=10, eval_count=5,
    )


def test_local_backend_resolves_source_markers():
    backend = LocalBackend(client=FakeOllama([chunk("Height 4.36 mm [S2]."), chunk(done=True)]))
    sources = [Source("a", "A", "1"), Source("b", "B", "2")]
    events = collect(backend.turn([], sources))
    result = events[-1]
    assert result.blocks == [{"text": "Height 4.36 mm [S2].", "citations": [1]}]
    assert result.usage == {"input_tokens": 10, "output_tokens": 5}


def test_local_backend_numbers_sources_across_the_conversation():
    backend = LocalBackend(client=FakeOllama([]))
    messages = []
    ok = ToolOutcome(True, [Source("s", "T", "x"), Source("s2", "T2", "y")])
    backend.add_tool_results(messages, [(ToolCall("a", "get_distances", {}), ok)], offset=3)
    assert messages[0]["content"].startswith("[S4] T") and "[S5] T2" in messages[0]["content"]


# --- endpoint --------------------------------------------------------------------------------


@pytest.fixture
def chat_client(seeded_api, executor):
    def backend_factory(name):
        return ScriptedBackend([
            TurnResult("tool_use", [ToolCall("t1", "get_cochlea_dimensions",
                                             {"specimen_id": "zeta"})]),
            TurnResult("end_turn", blocks=[{"text": "A is 8.97 mm.", "citations": [0]}]),
        ])

    available = route.BackendStatus(available=True, model="scripted", where="test")
    app.dependency_overrides[route.get_session_factory] = lambda: seeded_api.sessionmaker
    app.dependency_overrides[route.get_executor] = lambda: executor
    app.dependency_overrides[route.get_backend_factory] = lambda: backend_factory
    app.dependency_overrides[route.get_status_checks] = lambda: {
        "claude": lambda: available,
        "local": lambda: route.BackendStatus(available=False, model="m", where="test",
                                             reason="Ollama not reachable."),
    }
    with TestClient(app) as c:
        yield c


def sse_events(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_chat_streams_events_and_logs_the_turn(chat_client):
    r = chat_client.post(f"{V1}/assistant/chat", json={"question": "What is A?", "backend": "claude"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = sse_events(r)
    assert events[0]["type"] == "conversation"
    assert [e["type"] for e in events][-2:] == ["answer", "done"]
    conv_id = events[0]["id"]

    turns = chat_client.get(f"{V1}/assistant/conversations/{conv_id}").json()
    assert turns[0]["answer"] == "A is 8.97 mm."
    assert turns[0]["tool_calls"][0]["name"] == "get_cochlea_dimensions"
    assert turns[0]["tool_calls"][0]["ok"] is True
    assert turns[0]["sources"][0]["source"].endswith("#a")

    # follow-up continues the same conversation
    r = chat_client.post(f"{V1}/assistant/chat", json={"question": "And B?",
                                                       "conversation_id": conv_id})
    assert sse_events(r)[0]["id"] == conv_id
    assert len(chat_client.get(f"{V1}/assistant/conversations/{conv_id}").json()) == 2


def test_unavailable_backend_is_refused_up_front(chat_client):
    r = chat_client.post(f"{V1}/assistant/chat", json={"question": "Hi", "backend": "local"})
    assert r.status_code == 503 and "Ollama not reachable" in r.json()["detail"]
    status = chat_client.get(f"{V1}/assistant/status").json()
    assert status["backends"]["claude"]["available"] is True


# --- Claude backend against real SDK types (no network) ---------------------------------------


class FakeStream:
    def __init__(self, message, texts):
        self.message, self.texts = message, texts

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def gen():
            for t in self.texts:
                yield SimpleNamespace(type="text", text=t)
        return gen()

    async def get_final_message(self):
        return self.message


def test_claude_turn_builds_request_and_reads_citations():
    from anthropic.types.beta import BetaMessage

    message = BetaMessage.model_validate({
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 100, "output_tokens": 20},
        "content": [
            {"type": "text", "text": "Height is 4.36 mm", "citations": [{
                "type": "search_result_location", "source": "api:/x#height", "title": "h",
                "cited_text": "{}", "search_result_index": 1, "start_block_index": 0,
                "end_block_index": 1,
            }]},
            {"type": "text", "text": ", outside the range.", "citations": None},
        ],
    })
    calls = {}

    def stream(**kwargs):
        calls.update(kwargs)
        return FakeStream(message, ["Height is 4.36 mm", ", outside the range."])

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)))
    backend = ClaudeBackend(client=client)
    messages = backend.start("How tall?")
    events = collect(backend.turn(messages, [Source("a", "A", "1"), Source("b", "B", "2")]))
    result = events[-1]

    from cochleahub.config import settings

    assert calls["model"] == settings.llm_model and calls["fallbacks"] == "default"
    assert calls["output_config"] == {"effort": settings.llm_effort}
    assert "thinking" not in calls  # always on for this model; only effort is set
    assert all(t["eager_input_streaming"] for t in calls["tools"])
    assert result.blocks[0] == {"text": "Height is 4.36 mm", "citations": [1]}
    assert result.blocks[1]["citations"] == []
    # the assistant turn is stored as plain JSON for the next request and the audit log
    assert messages[-1]["role"] == "assistant"
    json.dumps(messages)


def test_search_modes_and_relevance_labels():
    from cochleahub.evaluation.retrieval_eval import is_relevant

    chunks = [Chunk("docs/DECISIONS.md#d6-minimum-distances-accepted", "d", "D6", "facial nerve"),
              Chunk("docs/x.md#other", "x", "X", "volume of bone")]
    index = Index(chunks, None)
    assert index.search("facial nerve", k=1, mode="bm25")[0].chunk.id.startswith("docs/DECISIONS")
    assert index.search("facial nerve", k=1, mode="dense") == []  # no vectors in this index
    # labels are id prefixes, so they survive a status change in a decision's title
    assert is_relevant(chunks[0].id, ["docs/DECISIONS.md#d6-"])
    assert not is_relevant(chunks[1].id, ["docs/DECISIONS.md#d6-"])
