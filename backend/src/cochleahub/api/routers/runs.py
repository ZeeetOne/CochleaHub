"""Pipeline runs with their QC flags and validation results (operations view, D14, D16)."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from cochleahub.api import schemas
from cochleahub.api.deps import get_session
from cochleahub.api.queries import get_run, provenance
from cochleahub.db.models import PipelineRun, QcFlag

router = APIRouter(prefix="/runs", tags=["runs"])

SessionDep = Annotated[Session, Depends(get_session)]
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


@router.get("", response_model=list[schemas.RunSummary])
def list_runs(
    session: SessionDep,
    specimen_id: str | None = None,
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Most recent first."""
    q = select(PipelineRun).order_by(PipelineRun.started_at.desc())
    if specimen_id:
        q = q.where(PipelineRun.specimen_id == specimen_id)
    if status:
        q = q.where(PipelineRun.status == status)
    return session.scalars(q.limit(limit).offset(offset)).all()


@router.get("/{run_id}", response_model=schemas.Run)
def run_detail(run_id: uuid.UUID, session: SessionDep):
    return get_run(session, run_id)


@router.get("/{run_id}/qc", response_model=schemas.QcReport)
def qc(
    run_id: uuid.UUID,
    session: SessionDep,
    severity: Literal["error", "warning", "info"] | None = None,
):
    """Flags sorted by severity (errors first); counts always cover the whole run."""
    run = get_run(session, run_id)
    q = select(QcFlag).where(QcFlag.run_id == run.id)
    if severity:
        q = q.where(QcFlag.severity == severity)
    flags = sorted(session.scalars(q), key=lambda f: (SEVERITY_ORDER[f.severity], f.id))
    return schemas.QcReport(
        provenance=provenance(run),
        status=run.qc_status,
        counts={"error": run.qc_errors, "warning": run.qc_warnings, "info": run.qc_info},
        flags=flags,
    )


@router.get("/{run_id}/validation", response_model=schemas.ValidationReport)
def validation(
    run_id: uuid.UUID,
    session: SessionDep,
    reference: Literal["slicer", "dataset_mesh"] | None = None,
):
    run = get_run(session, run_id)
    rows = [v for v in run.validations if reference is None or v.reference == reference]
    return schemas.ValidationReport(
        provenance=provenance(run),
        results=sorted(rows, key=lambda v: (v.reference, v.structure)),
    )
