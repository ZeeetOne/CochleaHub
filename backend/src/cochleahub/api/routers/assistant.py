"""Assistant endpoint (stage 7; D11, D20). The only non-GET route: it reads data through the
same read-only routes and writes nothing but its own conversation log."""

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import sessionmaker

from cochleahub.assistant.agent import Conversation, run_turn
from cochleahub.assistant.tools import Source, ToolExecutor
from cochleahub.config import settings
from cochleahub.db.models import AssistantConversation, AssistantTurn
from cochleahub.db.session import SessionLocal

router = APIRouter(prefix="/assistant", tags=["assistant"])

Backend = Literal["claude", "local"]


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    conversation_id: uuid.UUID | None = None
    backend: Backend | None = Field(None, description="Default: LLM_BACKEND setting.")


class BackendStatus(BaseModel):
    available: bool
    model: str
    where: str
    reason: str | None = None


class AssistantStatus(BaseModel):
    default: Backend
    backends: dict[str, BackendStatus]


class Turn(BaseModel):
    created_at: datetime
    question: str
    answer: str
    tool_calls: list
    sources: list
    stop_reason: str | None
    model: str | None
    latency_s: float | None
    error: str | None


# --- dependencies (overridden in tests) ------------------------------------------------------


def get_session_factory() -> sessionmaker:
    return SessionLocal


@lru_cache
def get_executor() -> ToolExecutor:
    from cochleahub.assistant.retrieval import open_index

    return ToolExecutor(index=open_index())


def make_backend(name: str):
    from cochleahub.assistant.backends import ClaudeBackend, LocalBackend

    return ClaudeBackend() if name == "claude" else LocalBackend()


def get_backend_factory() -> Callable[[str], object]:
    return make_backend


def claude_status() -> BackendStatus:
    bedrock = settings.llm_provider == "bedrock"
    where = f"Amazon Bedrock ({settings.aws_region})" if bedrock else "Claude API (cloud)"
    model = settings.bedrock_model if bedrock else settings.llm_model
    if not bedrock and not settings.anthropic_api_key:
        return BackendStatus(available=False, model=model, where=where,
                             reason="ANTHROPIC_API_KEY is not set.")
    return BackendStatus(available=True, model=model, where=where)


def local_status() -> BackendStatus:
    where = f"Ollama on {settings.ollama_url} (local network)"
    try:
        r = httpx.get(f"{settings.ollama_url}/api/tags", timeout=2)
        r.raise_for_status()
        names = {m["name"] for m in r.json().get("models", [])}
    except httpx.HTTPError as e:
        return BackendStatus(available=False, model=settings.local_model, where=where,
                             reason=f"Ollama not reachable ({type(e).__name__}).")
    wanted = settings.local_model
    if wanted not in names and f"{wanted}:latest" not in names:
        return BackendStatus(available=False, model=wanted, where=where,
                             reason=f"Model not pulled: run `ollama pull {wanted}`.")
    return BackendStatus(available=True, model=wanted, where=where)


def get_status_checks() -> dict[str, Callable[[], BackendStatus]]:
    return {"claude": claude_status, "local": local_status}


# --- routes ----------------------------------------------------------------------------------


@router.get("/status", response_model=AssistantStatus)
def status(checks: Annotated[dict, Depends(get_status_checks)]):
    return AssistantStatus(
        default=settings.llm_backend, backends={k: check() for k, check in checks.items()}
    )


@router.get("/conversations/{conversation_id}", response_model=list[Turn])
def conversation(
    conversation_id: uuid.UUID,
    factory: Annotated[sessionmaker, Depends(get_session_factory)],
):
    with factory() as session:
        conv = session.get(AssistantConversation, conversation_id)
        if conv is None:
            raise HTTPException(404, f"Unknown conversation {conversation_id}.")
        return conv.turns


def sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


@router.post("/chat", responses={200: {"content": {"text/event-stream": {}}}})
def chat(
    req: ChatRequest,
    factory: Annotated[sessionmaker, Depends(get_session_factory)],
    executor: Annotated[ToolExecutor, Depends(get_executor)],
    backends: Annotated[Callable[[str], object], Depends(get_backend_factory)],
    checks: Annotated[dict, Depends(get_status_checks)],
):
    """Answer one question as a Server-Sent Events stream (see assistant/agent.py for the
    event types). The first event is `{"type": "conversation", "id": ...}`."""
    with factory() as session:
        if req.conversation_id:
            row = session.get(AssistantConversation, req.conversation_id)
            if row is None:
                raise HTTPException(404, f"Unknown conversation {req.conversation_id}.")
            name = row.backend
            conv = Conversation(
                backend=row.backend, model=row.model, messages=row.messages,
                sources=[Source(**s) for s in row.sources],
            )
            conv_id = row.id
        else:
            name = req.backend or settings.llm_backend
            conv, conv_id = None, uuid.uuid4()
    check = checks[name]()
    if not check.available:
        raise HTTPException(503, f"Assistant backend '{name}' unavailable: {check.reason}")
    backend = backends(name)
    conv = conv or Conversation(backend=name, model=backend.model)

    async def events():
        started = time.perf_counter()
        yield sse({"type": "conversation", "id": str(conv_id), "backend": name,
                   "model": backend.model})
        answer, tool_calls, cited, done, error = "", [], [], {}, None
        try:
            async for ev in run_turn(backend, executor, conv, req.question):
                if ev["type"] == "tool_call":
                    tool_calls.append({"name": ev["name"], "input": ev["input"]})
                elif ev["type"] == "tool_result":
                    tool_calls[_pending(tool_calls)] |= {
                        "ok": ev["ok"], "summary": ev["summary"], "error": ev["error"],
                    }
                elif ev["type"] == "answer":
                    answer = "".join(b["text"] for b in ev["blocks"])
                    cited = ev["sources"]
                elif ev["type"] == "done":
                    done = ev
                elif ev["type"] == "error":
                    error = ev["message"]
                yield sse(ev)
        except Exception as e:  # noqa: BLE001 - reported to the client and logged with the turn
            error = f"{type(e).__name__}: {e}"
            yield sse({"type": "error", "message": f"The assistant failed: {error}"})
        save(factory, conv_id, conv, req.question, answer, tool_calls, cited, done, error,
             time.perf_counter() - started)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _pending(tool_calls: list[dict]) -> int:
    """Tool results arrive in call order; match the first call still without a result."""
    return next(i for i, t in enumerate(tool_calls) if "ok" not in t)


def save(factory, conv_id, conv, question, answer, tool_calls, cited, done, error, latency):
    now = datetime.now(UTC)
    with factory.begin() as session:
        row = session.get(AssistantConversation, conv_id)
        if row is None:
            row = AssistantConversation(id=conv_id, backend=conv.backend, model=conv.model,
                                        created_at=now)
            session.add(row)
        row.messages = conv.messages
        row.sources = [asdict(s) for s in conv.sources]
        row.updated_at = now
        row.turns.append(AssistantTurn(
            created_at=now, question=question, answer=answer, tool_calls=tool_calls,
            sources=cited, stop_reason=done.get("stop_reason"), model=done.get("model"),
            usage=done.get("usage", {}), latency_s=round(latency, 3), error=error,
        ))
