"""Shared fixtures: a small pipeline output and a fake object store."""

import copy
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from cochleahub.api.deps import get_session, get_store
from cochleahub.api.main import app
from cochleahub.db.load import load_run, upsert_specimen
from cochleahub.db.models import Base


class FakeStore:
    def __init__(self):
        self.keys = []

    def ensure_bucket(self):
        pass

    def upload(self, path, key, content_type="model/gltf-binary"):
        self.keys.append(key)
        return key

    def presigned_url(self, key, expires_s=3600):
        return f"https://s3.test/{key}?expires={expires_s}"


MEASUREMENTS = {
    "run": {
        "pipeline_version": "0.1.0",
        "started_at": "2026-10-30T16:48:27+00:00",
        "status": "completed",
        "errors": [],
        "duration_s": 17.5,
        "voxel_size_mm": 0.125,
    },
    "structures": {
        "Scala Tympani": {
            "segment_id": "Segment_1",
            "color": [0.5, 0.7, 0.5],
            "voxel_count": 17741,
            "volume_mm3": 34.65,
            "surface_area_mm2": 119.4,
            "length_mm": 8.97,
            "width_mm": 6.81,
            "thickness_mm": 4.36,
            "centroid_lps_mm": [-21.8, -23.0, 39.0],
            "connected_components": 1,
            "largest_component_fraction": 1.0,
            "mesh_volume_mm3": 34.4,
            "mesh": {"step_voxels": 1, "path": "scala_tympani.glb", "faces": 22726, "bytes": 409796},
        }
    },
    "cochlea": {"a_mm": 8.97, "b_mm": 6.81, "height_mm": 4.36, "method": "proxy"},
    "distances": [
        {
            "from": "Facial Nerve",
            "to": "Scala Tympani",
            "meaning": "facial nerve to cochlea",
            "distance_mm": 1.18,
            "point_a_lps_mm": [0, 0, 0],
            "point_b_lps_mm": [1, 0, 0],
        }
    ],
}

VALIDATION = {
    "qc": {
        "summary": {"status": "pass_with_warnings", "error": 0, "warning": 1, "info": 0},
        "flags": [
            {
                "severity": "warning",
                "code": "OUT_OF_PUBLISHED_RANGE",
                "structure": "Cochlea",
                "message": "height",
                "value": 4.36,
                "threshold": None,
                "source": "Zahara2019",
            }
        ],
    },
    "slicer": None,
    "dataset_meshes": {"reference": "ply", "structures": {}},
}



@pytest.fixture
def measurements():
    return copy.deepcopy(MEASUREMENTS)


@pytest.fixture
def validation():
    return copy.deepcopy(VALIDATION)


@pytest.fixture
def store():
    return FakeStore()


@pytest.fixture
def seeded_api(tmp_path, measurements, validation, store):
    """The app on an in-memory SQLite database holding ZETA (a completed and a later failed
    run) and a specimen without runs."""
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
    yield SimpleNamespace(run_ids=ids, sessionmaker=make_session)
    app.dependency_overrides.clear()


# --- PostgreSQL with pgvector (retrieval index, document library) -----------------------------

PG_TEST_DB = "cochleahub_test"


class FakeEmbedder:
    """Bag-of-words hashing into 384 dimensions: similar texts get similar vectors."""

    name = "fake-hash-384"

    def _vec(self, text):
        import hashlib

        import numpy as np

        v = np.zeros(384)
        for word in text.lower().split():
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % 384] += 1
        return v / (np.linalg.norm(v) or 1)

    def documents(self, texts):
        import numpy as np

        return np.array([self._vec(t) for t in texts])

    def query(self, text):
        return self._vec(text)


@pytest.fixture(scope="session")
def pg_engine():
    """A throwaway database `cochleahub_test` on the server from DATABASE_URL; tests using it
    are skipped when PostgreSQL with pgvector is not reachable."""
    from sqlalchemy import text
    from sqlalchemy.engine import make_url

    from cochleahub.config import settings

    store = pytest.importorskip("cochleahub.assistant.store")
    url = make_url(settings.database_url)
    try:
        admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as c:
            if not c.scalar(text("SELECT 1 FROM pg_database WHERE datname = :d"),
                            {"d": PG_TEST_DB}):
                c.execute(text(f"CREATE DATABASE {PG_TEST_DB}"))
        admin.dispose()
    except Exception as e:  # noqa: BLE001 - no server: skip, not fail
        pytest.skip(f"PostgreSQL not reachable: {type(e).__name__}")
    engine = create_engine(url.set(database=PG_TEST_DB))
    with engine.begin() as c:
        try:
            c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception:  # noqa: BLE001
            pytest.skip("pgvector extension not available")
    store.RagBase.metadata.drop_all(engine)
    store.RagBase.metadata.create_all(engine)
    yield engine
    store.RagBase.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def pg_sessions(pg_engine):
    """Empty retrieval tables for each test."""
    from sqlalchemy import text

    with pg_engine.begin() as c:
        c.execute(text("TRUNCATE rag_chunks, rag_documents RESTART IDENTITY CASCADE"))
    return sessionmaker(pg_engine)
