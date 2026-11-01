"""Retrieval index in PostgreSQL: pgvector for embeddings, full-text search for keywords (D24).

The same hybrid retrieval as the in-memory index (D19), moved into the database the rest of
CochleaHub already uses, so the index is persistent, shared by every API process, backed up with
the data, and on AWS lives in RDS, which offers the pgvector extension.

- `rag_documents` holds one row per source document with a content hash. `source` is
  "corpus" (CochleaHub's own docs, synced by `index-docs`) or "upload" (added through the
  document library, D25), with its lifecycle status.
- `rag_chunks` holds one row per passage: its text, its embedding (`vector(384)`, HNSW index,
  cosine distance) and a generated `tsvector` (GIN index). The title is weighted above the body.

Ingestion is idempotent. Unchanged passages keep their embeddings; only new or edited passages
are embedded; passages and documents that disappeared from the corpus are deleted.

Search runs two ranked queries and fuses them with Reciprocal Rank Fusion [Cormack2009], as in
the in-memory index and as in medical RAG benchmarks that fuse lexical and dense retrievers
[Xiong2024]. The lexical side is PostgreSQL's `ts_rank_cd` over an OR-query of the question's
stemmed terms, not BM25 [Robertson2009]; `cochleahub eval-retrieval` measures the difference.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    delete,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from cochleahub.assistant.retrieval import Chunk, Hit, rrf

EMBED_DIM = 384  # BAAI/bge-small-en-v1.5; another model needs a migration


class RagBase(DeclarativeBase):
    """Kept apart from the main schema's metadata: these types exist only in PostgreSQL, while
    the main schema is also created on SQLite in tests."""


class RagDocument(RagBase):
    __tablename__ = "rag_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String(256), unique=True)
    title: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    chunk_count: Mapped[int] = mapped_column(Integer)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # uploads (D25)
    source: Mapped[str] = mapped_column(String(16), default="corpus", server_default="corpus",
                                        index=True)
    status: Mapped[str] = mapped_column(String(16), default="indexed", server_default="indexed")
    error: Mapped[str | None] = mapped_column(Text)
    filename: Mapped[str | None] = mapped_column(String(256))
    content_type: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    sections: Mapped[int | None] = mapped_column(Integer)  # pages (PDF) or sections
    object_key: Mapped[str | None] = mapped_column(String(512))  # original file in S3
    no_patient_data: Mapped[bool | None] = mapped_column(Boolean)  # uploader's attestation
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RagChunk(RagBase):
    __tablename__ = "rag_chunks"
    __table_args__ = (
        Index("ix_rag_chunks_tsv", "tsv", postgresql_using="gin"),
        Index("ix_rag_chunks_embedding", "embedding", postgresql_using="hnsw",
              postgresql_ops={"embedding": "vector_cosine_ops"}),
    )

    id: Mapped[str] = mapped_column(String(512), primary_key=True)  # "docs/x.md#section"
    document_id: Mapped[int] = mapped_column(ForeignKey("rag_documents.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    text_hash: Mapped[str] = mapped_column(String(64))
    embedding_model: Mapped[str] = mapped_column(String(128))
    embedding = mapped_column(Vector(EMBED_DIM))
    tsv = mapped_column(
        TSVECTOR,
        Computed("setweight(to_tsvector('english', title), 'A') || "
                 "setweight(to_tsvector('english', text), 'B')", persisted=True),
    )


def sha(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode())
        h.update(b"\0")
    return h.hexdigest()


@dataclass
class IngestReport:
    documents: int
    chunks: int
    embedded: int
    deleted_chunks: int
    deleted_documents: int


def ingest(session: Session, chunks: list[Chunk], embedder) -> IngestReport:
    """Bring the database index in line with `chunks`. Embeds only what changed."""
    now = datetime.now(UTC)
    by_doc: dict[str, list[Chunk]] = {}
    for c in chunks:
        by_doc.setdefault(c.path, []).append(c)

    # corpus sync never touches uploaded documents
    existing_docs = {d.path: d for d in session.scalars(
        select(RagDocument).where(RagDocument.source == "corpus"))}
    existing = {c.id: c for c in session.scalars(
        select(RagChunk).join(RagDocument).where(RagDocument.source == "corpus"))}
    to_embed: list[tuple[RagChunk, str]] = []
    wanted_ids: set[str] = set()

    for path, doc_chunks in by_doc.items():
        doc = existing_docs.get(path)
        content_hash = sha(*(f"{c.id}{c.text}" for c in doc_chunks))
        if doc is None:
            doc = RagDocument(path=path, title=doc_chunks[0].title.split(" › ")[0],
                              content_hash=content_hash, chunk_count=len(doc_chunks),
                              indexed_at=now)
            session.add(doc)
            session.flush()
        elif doc.content_hash != content_hash:
            doc.content_hash, doc.chunk_count, doc.indexed_at = content_hash, len(doc_chunks), now
        for pos, c in enumerate(doc_chunks):
            wanted_ids.add(c.id)
            text_hash = sha(c.title, c.text)
            row = existing.get(c.id)
            if row is None:
                row = RagChunk(id=c.id, document_id=doc.id, position=pos, title=c.title,
                               text=c.text, text_hash="", embedding_model="")
                session.add(row)
            row.document_id, row.position, row.title, row.text = doc.id, pos, c.title, c.text
            if row.text_hash != text_hash or row.embedding_model != embedder.name:
                row.text_hash, row.embedding_model = text_hash, embedder.name
                to_embed.append((row, f"{c.title}\n{c.text}"))

    if to_embed:
        vectors = embedder.documents([t for _, t in to_embed])
        for (row, _), v in zip(to_embed, vectors, strict=True):
            row.embedding = [float(x) for x in v]

    stale_chunks = [cid for cid in existing if cid not in wanted_ids]
    if stale_chunks:
        session.execute(delete(RagChunk).where(RagChunk.id.in_(stale_chunks)))
    stale_docs = [d.id for p, d in existing_docs.items() if p not in by_doc]
    if stale_docs:
        session.execute(delete(RagDocument).where(RagDocument.id.in_(stale_docs)))
    session.flush()
    return IngestReport(len(by_doc), len(chunks), len(to_embed), len(stale_chunks),
                        len(stale_docs))


def replace_chunks(session: Session, doc: RagDocument, chunks: list[Chunk], embedder) -> None:
    """Index one uploaded document: its passages replace any previous ones."""
    session.execute(delete(RagChunk).where(RagChunk.document_id == doc.id))
    vectors = embedder.documents([f"{c.title}\n{c.text}" for c in chunks]) if chunks else []
    for pos, (c, v) in enumerate(zip(chunks, vectors, strict=True)):
        session.add(RagChunk(
            id=c.id, document_id=doc.id, position=pos, title=c.title, text=c.text,
            text_hash=sha(c.title, c.text), embedding_model=embedder.name,
            embedding=[float(x) for x in v],
        ))
    doc.chunk_count = len(chunks)
    doc.content_hash = sha(*(f"{c.id}{c.text}" for c in chunks))
    session.flush()


LEXICAL_SQL = text("""
    WITH q AS (
        -- the question's stemmed terms joined with OR: AND would demand every word of a
        -- natural-language question in one passage
        SELECT replace(plainto_tsquery('english', :query)::text, '&', '|')::tsquery AS tsq
    )
    SELECT id FROM rag_chunks, q
    WHERE q.tsq::text <> '' AND tsv @@ q.tsq
    ORDER BY ts_rank_cd(tsv, q.tsq) DESC, id
    LIMIT :n
""")


class PgIndex:
    """Same interface as retrieval.Index, backed by PostgreSQL."""

    def __init__(self, sessions: sessionmaker, embedder=None):
        self.sessions = sessions
        self.embedder = embedder

    @property
    def chunks(self) -> list[Chunk]:
        with self.sessions() as s:
            rows = s.scalars(select(RagChunk).order_by(RagChunk.id)).all()
            return [Chunk(r.id, r.id.split("#")[0], r.title, r.text) for r in rows]

    def search(
        self, query: str, k: int = 5, candidates: int = 20, mode: str = "hybrid"
    ) -> list[Hit]:
        """mode: "hybrid" (default), "bm25" (here: full-text search) or "dense"."""
        with self.sessions() as s:
            lexical: list[str] = []
            dense: list[str] = []
            if mode != "dense":
                lexical = list(s.scalars(LEXICAL_SQL, {"query": query, "n": candidates}))
            if mode != "bm25" and self.embedder is not None:
                qv = [float(x) for x in self.embedder.query(query)]
                dense = list(s.scalars(
                    select(RagChunk.id)
                    .order_by(RagChunk.embedding.cosine_distance(qv), RagChunk.id)
                    .limit(candidates)
                ))
            fused = rrf([r for r in (lexical, dense) if r])
            best = sorted(fused, key=lambda i: (-fused[i], i))[:k]
            rows = {r.id: r for r in s.scalars(select(RagChunk).where(RagChunk.id.in_(best)))}
            return [
                Hit(
                    chunk=Chunk(i, i.split("#")[0], rows[i].title, rows[i].text),
                    score=fused[i],
                    bm25_rank=lexical.index(i) + 1 if i in lexical else None,
                    dense_rank=dense.index(i) + 1 if i in dense else None,
                )
                for i in best
            ]
