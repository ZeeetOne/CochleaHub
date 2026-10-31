"""Loading a run into the database (SQLite in memory, fake S3) and idempotency."""

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from cochleahub.db.load import load_run
from cochleahub.db.models import Base, PipelineRun, QcFlag, StructureMeasurement


def test_load_run_stores_everything_once(tmp_path, measurements, validation, store):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session, session.begin():
        run, created = load_run(session, "zeta", measurements, validation, tmp_path, store)
        assert created
        assert store.keys == [f"meshes/zeta/{run.id}/scala_tympani.glb"]

    with Session(engine) as session, session.begin():
        _, created = load_run(session, "zeta", measurements, validation, tmp_path, store)
        assert not created
        assert session.scalar(select(func.count()).select_from(PipelineRun)) == 1
        assert session.scalar(select(func.count()).select_from(StructureMeasurement)) == 1
        flag = session.scalar(select(QcFlag))
        assert (flag.code, flag.source) == ("OUT_OF_PUBLISHED_RANGE", "Zahara2019")
