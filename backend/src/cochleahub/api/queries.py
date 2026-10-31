"""Run selection shared by the routers.

By default a specimen's results come from its latest *completed* run; a client can pin an
older run with `run_id`. Missing data raise 404 with a message that says what is missing
(unknown specimen, no completed run, run of another specimen), so callers such as the
assistant can abstain instead of guessing [Lee2022].
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from cochleahub.api.schemas import Provenance
from cochleahub.db.models import PipelineRun, Specimen


def get_specimen(session: Session, specimen_id: str) -> Specimen:
    specimen = session.get(Specimen, specimen_id)
    if specimen is None:
        raise HTTPException(404, f"Unknown specimen '{specimen_id}'.")
    return specimen


def latest_run(session: Session, specimen_id: str) -> PipelineRun | None:
    return session.scalar(
        select(PipelineRun)
        .where(PipelineRun.specimen_id == specimen_id, PipelineRun.status == "completed")
        .order_by(PipelineRun.started_at.desc())
        .limit(1)
    )


def resolve_run(session: Session, specimen_id: str, run_id: uuid.UUID | None) -> PipelineRun:
    get_specimen(session, specimen_id)
    if run_id is None:
        run = latest_run(session, specimen_id)
        if run is None:
            raise HTTPException(404, f"Specimen '{specimen_id}' has no completed pipeline run.")
        return run
    run = session.get(PipelineRun, run_id)
    if run is None or run.specimen_id != specimen_id:
        raise HTTPException(404, f"Run {run_id} does not exist for specimen '{specimen_id}'.")
    return run


def get_run(session: Session, run_id: uuid.UUID) -> PipelineRun:
    run = session.get(PipelineRun, run_id)
    if run is None:
        raise HTTPException(404, f"Unknown run {run_id}.")
    return run


def provenance(run: PipelineRun) -> Provenance:
    return Provenance(
        run_id=run.id,
        specimen_id=run.specimen_id,
        pipeline_version=run.pipeline_version,
        started_at=run.started_at,
        qc_status=run.qc_status,
    )
