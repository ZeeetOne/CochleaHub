"""PostgreSQL retrieval index (pgvector + full-text search): ingestion and search.

Runs against a throwaway database `cochleahub_test` on the server from DATABASE_URL; skipped
when PostgreSQL with pgvector is not reachable. A deterministic fake embedder replaces the
embedding model."""

import pytest
from conftest import FakeEmbedder
from sqlalchemy import func, select

from cochleahub.assistant.retrieval import Chunk

store = pytest.importorskip("cochleahub.assistant.store")


@pytest.fixture
def sessions(pg_sessions):
    return pg_sessions


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


def test_full_text_search_matches_codes_and_stems(sessions):
    with sessions.begin() as s:
        store.ingest(s, CORPUS, FakeEmbedder())
    index = store.PgIndex(sessions, FakeEmbedder())
    [hit] = index.search("What does OUT_OF_PUBLISHED_RANGE mean?", k=1, mode="bm25")
    assert hit.chunk.id == "docs/a.md#flags"
    # stemming: "changing" matches "changes"; OR-semantics: not every word must appear
    assert index.search("changing the window please", k=1, mode="bm25")[0].chunk.id == (
        "docs/b.md#viewer")


def test_hybrid_search_fuses_both_rankings(sessions):
    with sessions.begin() as s:
        store.ingest(s, CORPUS, FakeEmbedder())
    index = store.PgIndex(sessions, FakeEmbedder())
    hits = index.search("facial nerve cochlea", k=2)
    assert hits[0].chunk.id == "docs/a.md#distances"
    assert hits[0].bm25_rank == 1 and hits[0].dense_rank == 1
    assert hits[0].chunk.title == "Measurements › Distances"
    assert len(index.chunks) == 3
