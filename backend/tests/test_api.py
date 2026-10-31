"""Read-only API on SQLite with a fake object store: run selection, provenance, abstention."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from cochleahub.api.deps import get_session, get_store
from cochleahub.api.main import app
from cochleahub.db.load import load_run, upsert_specimen
from cochleahub.db.models import Base

V1 = "/api/v1"


@pytest.fixture
def client(tmp_path, measurements, validation, store):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        old, _ = load_run(session, "zeta", measurements, validation, tmp_path, store)
        # a later run that failed must not replace the completed one as "latest"
        failed = {**measurements, "run": {**measurements["run"], "status": "failed",
                                          "started_at": "2026-10-31T09:00:00+00:00"}}
        new, _ = load_run(session, "zeta", failed, validation, tmp_path, store)
        upsert_specimen(session, "empty")
        ids = {"completed": str(old.id), "failed": str(new.id)}

    make_session = sessionmaker(engine)

    def session_override():
        with make_session() as s:
            yield s

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_store] = lambda: store
    with TestClient(app) as c:
        c.run_ids = ids
        yield c
    app.dependency_overrides.clear()


def test_specimen_list_shows_latest_completed_run(client):
    body = client.get(f"{V1}/specimens").json()
    by_id = {s["id"]: s for s in body}
    assert by_id["zeta"]["latest_run"]["id"] == client.run_ids["completed"]
    assert by_id["empty"]["latest_run"] is None


def test_results_carry_provenance(client):
    body = client.get(f"{V1}/specimens/zeta/measurements").json()
    assert body["provenance"]["pipeline_version"] == "0.1.0"
    assert body["provenance"]["run_id"] == client.run_ids["completed"]
    assert body["structures"][0]["name"] == "Scala Tympani"


def test_run_can_be_pinned(client):
    rid = client.run_ids["failed"]
    body = client.get(f"{V1}/specimens/zeta/distances", params={"run_id": rid}).json()
    assert body["provenance"]["run_id"] == rid


def test_missing_data_says_what_is_missing(client):
    r = client.get(f"{V1}/specimens/nope/measurements")
    assert r.status_code == 404 and "Unknown specimen" in r.json()["detail"]
    r = client.get(f"{V1}/specimens/empty/cochlea")
    assert r.status_code == 404 and "no completed pipeline run" in r.json()["detail"]
    r = client.get(
        f"{V1}/specimens/empty/measurements", params={"run_id": client.run_ids["completed"]}
    )
    assert r.status_code == 404 and "does not exist for specimen 'empty'" in r.json()["detail"]


def test_cochlea_is_checked_against_published_range(client):
    body = client.get(f"{V1}/specimens/zeta/cochlea").json()
    assert body["a"]["in_range"] is True
    assert body["height"]["in_range"] is False
    assert body["height"]["reference"]["source"] == "Zahara2019"


def test_compare_keeps_specimens_without_value(client):
    r = client.get(f"{V1}/compare", params={"metric": "volume_mm3", "structure": "Scala Tympani"})
    body = r.json()
    assert body["reference"]["source"] == "Dhanasingh2021"
    values = {v["specimen_id"]: v["value"] for v in body["values"]}
    assert values == {"empty": None, "zeta": 34.65}
    assert client.get(f"{V1}/compare", params={"metric": "volume_mm3"}).status_code == 422


def test_meshes_are_presigned(client):
    body = client.get(f"{V1}/specimens/zeta/meshes").json()
    [mesh] = body["meshes"]
    assert mesh["url"].startswith("https://s3.test/meshes/zeta/")
    assert body["coordinate_system"] == "LPS"


def test_qc_flags_and_filter(client):
    rid = client.run_ids["completed"]
    body = client.get(f"{V1}/runs/{rid}/qc").json()
    assert body["counts"] == {"error": 0, "warning": 1, "info": 0}
    assert client.get(f"{V1}/runs/{rid}/qc", params={"severity": "error"}).json()["flags"] == []


def test_runs_listed_newest_first(client):
    body = client.get(f"{V1}/runs", params={"specimen_id": "zeta"}).json()
    assert [r["status"] for r in body] == ["failed", "completed"]


def test_api_is_read_only(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {m for ops in paths.values() for m in ops} == {"get"}
    assert client.post(f"{V1}/specimens").status_code == 405
