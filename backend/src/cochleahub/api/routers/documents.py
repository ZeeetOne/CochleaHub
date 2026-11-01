"""Document library for the assistant (D25): upload, list, inspect, delete.

Uploads are reference documents (protocols, guidelines, papers, de-identified case reports).
They are not for patient data: the uploader must attest that a file contains no
patient-identifiable information, and the UI says so. Patient documents need access control,
de-identification, deletion guarantees and an institutional setting first, as in RAG over
clinical notes [Unlu2024]; that is designed, not built (D25).

Pipeline: validate (type by extension *and* content, size, attestation) → store the original in
S3 → status "queued" → background: extract (tables kept as Markdown) → chunk → embed locally →
index in PostgreSQL → "indexed" (or "failed" with the reason). Identical files are detected by
hash. Processing runs in the API process; a production deployment would hand it to a queue
worker (e.g. SQS) so uploads survive restarts.
"""

import hashlib
import re
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from cochleahub.api.deps import get_store
from cochleahub.storage.objects import ObjectStore

router = APIRouter(prefix="/documents", tags=["documents"])

MAX_BYTES = 20 * 1024 * 1024


class Document(BaseModel):
    id: int
    title: str
    source: str  # "corpus" (built-in documentation) or "upload"
    status: str  # queued | processing | indexed | failed
    error: str | None
    filename: str | None
    content_type: str | None
    size_bytes: int | None
    sections: int | None
    chunk_count: int
    uploaded_at: datetime | None
    indexed_at: datetime | None


class DocumentDetail(Document):
    passages: list[dict]  # [{id, title, chars}]
    download_url: str | None


# --- dependencies (overridden in tests) ------------------------------------------------------


def get_rag_sessions() -> sessionmaker:
    from cochleahub.db.session import SessionLocal

    return SessionLocal


@lru_cache
def get_embedder():
    from cochleahub.assistant.retrieval import shared_embedder

    return shared_embedder()


Sessions = Annotated[sessionmaker, Depends(get_rag_sessions)]


def as_model(d) -> Document:
    return Document(
        id=d.id, title=d.title, source=d.source, status=d.status, error=d.error,
        filename=d.filename, content_type=d.content_type, size_bytes=d.size_bytes,
        sections=d.sections, chunk_count=d.chunk_count, uploaded_at=d.uploaded_at,
        indexed_at=d.indexed_at,
    )


def safe_name(filename: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1])
    return name[:120] or "document"


def process(sessions: sessionmaker, embedder, doc_id: int, filename: str, data: bytes) -> None:
    """Background step: extract, chunk, embed and index one upload."""
    from cochleahub.assistant.store import RagDocument, replace_chunks
    from cochleahub.documents.extract import ExtractionError, to_chunks

    with sessions.begin() as s:
        doc = s.get(RagDocument, doc_id)
        if doc is None:  # deleted before processing started
            return
        doc.status = "processing"
        title = doc.title
    try:
        chunks, sections = to_chunks(doc_id, title, filename, data)
        with sessions.begin() as s:
            doc = s.get(RagDocument, doc_id)
            if doc is None:
                return
            replace_chunks(s, doc, chunks, embedder)
            doc.status, doc.sections, doc.error = "indexed", sections, None
            doc.indexed_at = datetime.now(UTC)
    except Exception as e:  # noqa: BLE001 - recorded on the document, shown to the user
        message = str(e) if isinstance(e, ExtractionError) else (
            f"Processing failed ({type(e).__name__}).")
        with sessions.begin() as s:
            doc = s.get(RagDocument, doc_id)
            if doc is not None:
                doc.status, doc.error = "failed", message


# --- routes ----------------------------------------------------------------------------------


@router.get("", response_model=list[Document])
def list_documents(sessions: Sessions, source: str | None = None):
    from cochleahub.assistant.store import RagDocument

    q = select(RagDocument).order_by(RagDocument.source.desc(), RagDocument.id.desc())
    if source:
        q = q.where(RagDocument.source == source)
    with sessions() as s:
        return [as_model(d) for d in s.scalars(q)]


@router.post("", response_model=Document, status_code=202)
async def upload(
    sessions: Sessions,
    store: Annotated[ObjectStore, Depends(get_store)],
    embedder: Annotated[object, Depends(get_embedder)],
    background: BackgroundTasks,
    file: Annotated[UploadFile, File(description="PDF, DOCX, TXT or MD, up to 20 MB")],
    no_patient_data: Annotated[bool, Form(description="Uploader attests: no patient-"
                                          "identifiable information in this file")] = False,
    title: Annotated[str | None, Form(max_length=200)] = None,
):
    from cochleahub.assistant.store import RagDocument
    from cochleahub.documents.extract import TYPES, ExtractionError, file_type

    if not no_patient_data:
        raise HTTPException(422, "Confirm that the document contains no patient-identifiable "
                                 "information. Patient documents cannot be uploaded.")
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "The file is larger than 20 MB.")
    if not data:
        raise HTTPException(422, "The file is empty.")
    filename = safe_name(file.filename or "document")
    try:
        ext = file_type(filename, data)
    except ExtractionError as e:
        raise HTTPException(415, str(e)) from e

    digest = hashlib.sha256(data).hexdigest()
    path = f"upload/{digest}"
    with sessions() as s:
        existing = s.scalar(select(RagDocument).where(RagDocument.path == path))
        if existing is not None:
            raise HTTPException(409, f"This file was already uploaded as document "
                                     f"{existing.id} ('{existing.title}').")

    key = f"documents/{digest}/{filename}"
    store.put_bytes(data, key, TYPES[ext])
    with sessions.begin() as s:
        doc = RagDocument(
            path=path, title=(title or filename.rsplit(".", 1)[0]).strip()[:200],
            content_hash=digest, chunk_count=0, source="upload", status="queued",
            filename=filename, content_type=TYPES[ext], size_bytes=len(data), object_key=key,
            no_patient_data=True, uploaded_at=datetime.now(UTC),
        )
        s.add(doc)
        s.flush()
        result = as_model(doc)
    background.add_task(process, sessions, embedder, result.id, filename, data)
    return result


@router.get("/{doc_id}", response_model=DocumentDetail)
def document(doc_id: int, sessions: Sessions, store: Annotated[ObjectStore, Depends(get_store)]):
    from cochleahub.assistant.store import RagChunk, RagDocument

    with sessions() as s:
        doc = s.get(RagDocument, doc_id)
        if doc is None:
            raise HTTPException(404, f"Unknown document {doc_id}.")
        passages = [{"id": c.id, "title": c.title, "chars": len(c.text)} for c in s.scalars(
            select(RagChunk).where(RagChunk.document_id == doc_id).order_by(RagChunk.position))]
        url = store.presigned_url(doc.object_key, expires_s=600) if doc.object_key else None
        return DocumentDetail(**as_model(doc).model_dump(), passages=passages, download_url=url)


@router.delete("/{doc_id}", status_code=204)
def delete_document(
    doc_id: int, sessions: Sessions, store: Annotated[ObjectStore, Depends(get_store)]
):
    """Removes the document, its passages (cascade) and the stored original."""
    from cochleahub.assistant.store import RagDocument

    with sessions.begin() as s:
        doc = s.get(RagDocument, doc_id)
        if doc is None:
            raise HTTPException(404, f"Unknown document {doc_id}.")
        if doc.source != "upload":
            raise HTTPException(409, "Built-in documentation is managed with "
                                     "`cochleahub index-docs`, not deleted here.")
        key = doc.object_key
        s.delete(doc)
    if key:
        store.delete(key)

