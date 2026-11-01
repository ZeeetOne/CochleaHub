"""Document library: extraction (tables kept), upload pipeline, search, deletion (D25)."""

import io
from pathlib import Path

import pytest
from conftest import FakeEmbedder
from fastapi.testclient import TestClient

from cochleahub.api.deps import get_store
from cochleahub.api.main import app
from cochleahub.api.routers import documents as route
from cochleahub.documents.extract import ExtractionError, file_type, split, to_chunks

V1 = "/api/v1"
PDF = (Path(__file__).parent / "fixtures" / "specimen_protocol.pdf").read_bytes()


# --- extraction --------------------------------------------------------------------------------


def test_pdf_pages_become_passages_and_tables_stay_tables():
    chunks, pages = to_chunks(7, "Protocol", "specimen_protocol.pdf", PDF)
    assert pages == 2 and [c.id for c in chunks] == ["upload:7#p1", "upload:7#p2"]
    assert chunks[0].title == "Protocol › page 1"
    assert "| Storage before CBCT | 4 °C | 30 days |" in chunks[0].text
    assert "0.125 mm" in chunks[1].text


def test_docx_headings_and_tables():
    import docx

    d = docx.Document()
    d.add_heading("Scanning", level=1)
    d.add_paragraph("Each specimen is scanned twice.")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Scan", "Voxel"
    t.cell(1, 0).text, t.cell(1, 1).text = "CBCT", "0.125 mm"
    buf = io.BytesIO()
    d.save(buf)
    chunks, sections = to_chunks(3, "Handbook", "handbook.docx", buf.getvalue())
    assert sections == 1 and chunks[0].title == "Handbook › Scanning"
    assert "| CBCT | 0.125 mm |" in chunks[0].text


def test_type_must_match_content():
    with pytest.raises(ExtractionError, match="not a PDF"):
        file_type("fake.pdf", b"hello")
    with pytest.raises(ExtractionError, match="Unsupported"):
        file_type("run.exe", b"MZ")
    assert file_type("notes.md", b"# Notes") == ".md"


def test_long_text_is_split_at_paragraphs():
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 100 for i in range(10))
    parts = split(text, limit=1200)
    assert len(parts) > 1 and all(len(p) <= 1300 for p in parts)
    assert parts[0].startswith("Paragraph 0.")


# --- upload pipeline (PostgreSQL) ----------------------------------------------------------------


class MemoryStore:
    def __init__(self):
        self.objects = {}

    def put_bytes(self, data, key, content_type):
        self.objects[key] = data
        return key

    def delete(self, key):
        self.objects.pop(key, None)

    def presigned_url(self, key, expires_s=3600):
        return f"https://s3.test/{key}"


@pytest.fixture
def library(pg_sessions):
    store = MemoryStore()
    app.dependency_overrides[route.get_rag_sessions] = lambda: pg_sessions
    app.dependency_overrides[route.get_embedder] = FakeEmbedder
    app.dependency_overrides[get_store] = lambda: store
    with TestClient(app) as c:
        c.store, c.sessions = store, pg_sessions
        yield c
    app.dependency_overrides.clear()


def upload(client, name, data, attest=True, title=None):
    form = {"no_patient_data": "true" if attest else "false"}
    if title:
        form["title"] = title
    return client.post(f"{V1}/documents", files={"file": (name, data)}, data=form)


def test_upload_is_indexed_searchable_and_deletable(library):
    r = upload(library, "specimen_protocol.pdf", PDF, title="Specimen handling protocol")
    assert r.status_code == 202 and r.json()["status"] == "queued"
    doc_id = r.json()["id"]
    assert list(library.store.objects) == [k for k in library.store.objects
                                           if k.endswith("/specimen_protocol.pdf")]

    # background processing has run by the time TestClient returns
    detail = library.get(f"{V1}/documents/{doc_id}").json()
    assert detail["status"] == "indexed" and detail["sections"] == 2
    assert [p["id"] for p in detail["passages"]] == [f"upload:{doc_id}#p1",
                                                     f"upload:{doc_id}#p2"]
    assert detail["download_url"].startswith("https://s3.test/documents/")

    from cochleahub.assistant.store import PgIndex

    hits = PgIndex(library.sessions, FakeEmbedder()).search("resin embedding temperature", k=1)
    assert hits[0].chunk.id == f"upload:{doc_id}#p1"
    assert hits[0].chunk.title == "Specimen handling protocol › page 1"

    assert library.delete(f"{V1}/documents/{doc_id}").status_code == 204
    assert library.get(f"{V1}/documents/{doc_id}").status_code == 404
    assert PgIndex(library.sessions, FakeEmbedder()).search("resin embedding", k=1) == []
    assert library.store.objects == {}


def test_upload_requires_the_no_patient_data_attestation(library):
    r = upload(library, "notes.md", b"# Notes\n\nText.", attest=False)
    assert r.status_code == 422 and "patient" in r.json()["detail"]


def test_duplicates_and_wrong_types_are_rejected(library):
    assert upload(library, "notes.md", b"# Notes\n\nSome text.").status_code == 202
    dup = upload(library, "copy.md", b"# Notes\n\nSome text.")
    assert dup.status_code == 409 and "already uploaded" in dup.json()["detail"]
    assert upload(library, "fake.pdf", b"not a pdf").status_code == 415


def test_unreadable_pdf_is_marked_failed_with_a_reason(library):
    r = upload(library, "broken.pdf", b"%PDF-1.4 garbage")
    doc = library.get(f"{V1}/documents/{r.json()['id']}").json()
    assert doc["status"] == "failed" and doc["error"]


def test_built_in_documentation_cannot_be_deleted(library):
    from cochleahub.assistant.retrieval import Chunk
    from cochleahub.assistant.store import RagDocument, ingest

    with library.sessions.begin() as s:
        ingest(s, [Chunk("docs/a.md#x", "docs/a.md", "A", "text")], FakeEmbedder())
    with library.sessions() as s:
        doc_id = s.query(RagDocument).one().id
    assert library.delete(f"{V1}/documents/{doc_id}").status_code == 409
    listed = library.get(f"{V1}/documents").json()
    assert [d["source"] for d in listed] == ["corpus"]
