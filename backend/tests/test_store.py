"""PostgreSQL retrieval index (pgvector + full-text search): ingestion and search.

Runs against a throwaway database `cochleahub_test` on the server from DATABASE_URL; skipped
when PostgreSQL with pgvector is not reachable. A deterministic fake embedder replaces the
embedding model."""

import hashlib

import numpy as np
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from cochleahub.assistant.retrieval import Chunk
from cochleahub.config import settings

store = pytest.importorskip("cochleahub.assistant.store")
TEST_DB = "cochleahub_test"


class FakeEmbedder:
    """Bag-of-words hashing into 384 dimensions: similar texts get similar vectors."""

    name = "fake-hash-384"

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(store.EMBED_DIM)
        for word in text.lower().split():
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % store.EMBED_DIM] += 1
        return v / (np.linalg.norm(v) or 1)

    def documents(self, texts):
        return np.array([self._vec(t) for t in texts])

    def query(self, text):
        return self._vec(text)


@pytest.fixture(scope="module")
def sessions():
    url = make_url(settings.database_url)
    try:
        admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as c:
            if not c.scalar(text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": TEST_DB}):
                c.execute(text(f"CREATE DATABASE {TEST_DB}"))
    except Exception as e:  # noqa: BLE001 - no server: skip, not fail
        pytest.skip(f"PostgreSQL not reachable: {type(e).__name__}")
    engine = create_engine(url.set(database=TEST_DB))
    with engine.begin() as c:
        try:
            c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception:  # noqa: BLE001
            pytest.skip("pgvector extension not available")
    store.RagBase.metadata.drop_all(engine)
    store.RagBase.metadata.create_all(engine)
    yield sessionmaker(engine)
    store.RagBase.metadata.drop_all(engine)
    engine.dispose()
    admin.dispose()


CORPUS = [
    Chunk("docs/a.md#flags", "docs/a.md", "Measurements › QC flags",
          "OUT_OF_PUBLISHED_RANGE marks a value outside a published population range."),
    Chunk("docs/a.md#distances", "docs/a.md", "Measurements › Distances",
          "The facial nerve runs close to the scala tympani of the cochlea."),
    Chunk("docs/b.md#viewer", "docs/b.md", "User guide › CT viewer",
          "Left drag changes the window level; the wheel changes the slice."),
]


def count(sessions, model):
    with sessions() as s:
        return s.scalar(select(func.count()).select_from(model))


def test_ingest_is_idempotent_and_tracks_changes(sessions):
    emb = FakeEmbedder()
    with sessions.begin() as s:
        first = store.ingest(s, CORPUS, emb)
    assert (first.documents, first.chunks, first.embedded) == (2, 3, 3)

    with sessions.begin() as s:
        again = store.ingest(s, CORPUS, emb)
    assert again.embedded == 0 and again.deleted_chunks == 0

    edited = [*CORPUS[:2], Chunk("docs/b.md#viewer", "docs/b.md", "User guide › CT viewer",
                                 "Left drag changes window and level.")]
    with sessions.begin() as s:
        changed = store.ingest(s, edited, emb)
    assert changed.embedded == 1  # only the edited passage

    with sessions.begin() as s:
        removed = store.ingest(s, CORPUS[:2], emb)  # docs/b.md left the corpus
    assert (removed.deleted_chunks, removed.deleted_documents) == (1, 1)
    assert count(sessions, store.RagChunk) == 2 and count(sessions, store.RagDocument) == 1

    with sessions.begin() as s:
        store.ingest(s, CORPUS, emb)  # restore for the search tests


def test_full_text_search_matches_codes_and_stems(sessions):
    index = store.PgIndex(sessions, FakeEmbedder())
    [hit] = index.search("What does OUT_OF_PUBLISHED_RANGE mean?", k=1, mode="bm25")
    assert hit.chunk.id == "docs/a.md#flags"
    # stemming: "changing" matches "changes"; OR-semantics: not every word must appear
    assert index.search("changing the window please", k=1, mode="bm25")[0].chunk.id == (
        "docs/b.md#viewer")


def test_hybrid_search_fuses_both_rankings(sessions):
    index = store.PgIndex(sessions, FakeEmbedder())
    hits = index.search("facial nerve cochlea", k=2)
    assert hits[0].chunk.id == "docs/a.md#distances"
    assert hits[0].bm25_rank == 1 and hits[0].dense_rank == 1
    assert hits[0].chunk.title == "Measurements › Distances"
    assert len(index.chunks) == 3
