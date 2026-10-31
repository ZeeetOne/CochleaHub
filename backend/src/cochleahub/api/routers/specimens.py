"""Specimens and their latest (or a pinned) run's results."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cochleahub.api import schemas
from cochleahub.api.deps import get_session, get_store
from cochleahub.api.queries import get_specimen, latest_run, provenance, resolve_run
from cochleahub.config import settings
from cochleahub.db.models import PipelineRun, Specimen
from cochleahub.pipeline.reference_ranges import COCHLEA
from cochleahub.storage.objects import ObjectStore

router = APIRouter(prefix="/specimens", tags=["specimens"])

SessionDep = Annotated[Session, Depends(get_session)]
RunParam = Annotated[
    uuid.UUID | None, Query(description="Pin a run; default is the latest completed run.")
]
MESH_URL_TTL_S = 3600


def in_range(value: float, low: float, high: float) -> bool:
    return low <= value <= high


@router.get("", response_model=list[schemas.SpecimenSummary])
def list_specimens(session: SessionDep):
    specimens = session.scalars(select(Specimen).order_by(Specimen.id)).all()
    return [
        schemas.SpecimenSummary(
            id=s.id,
            dataset=s.dataset,
            side=s.side,
            description=s.description,
            latest_run=latest_run(session, s.id),
        )
        for s in specimens
    ]


@router.get("/{specimen_id}", response_model=schemas.Specimen)
def specimen_detail(specimen_id: str, session: SessionDep):
    s = get_specimen(session, specimen_id)
    n_runs = session.scalar(
        select(func.count()).select_from(PipelineRun).where(PipelineRun.specimen_id == s.id)
    )
    return schemas.Specimen(
        id=s.id,
        dataset=s.dataset,
        side=s.side,
        description=s.description,
        latest_run=latest_run(session, s.id),
        series=s.series,
        n_runs=n_runs,
    )


@router.get("/{specimen_id}/measurements", response_model=schemas.Measurements)
def measurements(specimen_id: str, session: SessionDep, run_id: RunParam = None):
    run = resolve_run(session, specimen_id, run_id)
    return schemas.Measurements(
        provenance=provenance(run),
        structures=sorted(run.structures, key=lambda s: s.name),
    )


@router.get("/{specimen_id}/cochlea", response_model=schemas.Cochlea)
def cochlea(specimen_id: str, session: SessionDep, run_id: RunParam = None):
    """Cochlear A, B and height with the published range each is checked against (D5, D14)."""
    run = resolve_run(session, specimen_id, run_id)
    c = run.cochlea
    if c is None:
        raise HTTPException(404, f"Run {run.id} has no cochlear dimensions.")

    def value(key: str, v: float) -> schemas.CochleaValue:
        ref = COCHLEA.get(key)
        return schemas.CochleaValue(
            value_mm=v,
            reference=schemas.ReferenceRange(**vars(ref)) if ref else None,
            in_range=in_range(v, ref.low, ref.high) if ref else None,
        )

    return schemas.Cochlea(
        provenance=provenance(run),
        method=c.method,
        a=value("a_mm", c.a_mm),
        b=value("b_mm", c.b_mm),
        height=value("height_mm", c.height_mm),
    )


@router.get("/{specimen_id}/distances", response_model=schemas.Distances)
def distances(specimen_id: str, session: SessionDep, run_id: RunParam = None):
    run = resolve_run(session, specimen_id, run_id)
    return schemas.Distances(provenance=provenance(run), distances=run.distances)


@router.get("/{specimen_id}/meshes", response_model=schemas.Meshes)
def meshes(
    specimen_id: str,
    session: SessionDep,
    store: Annotated[ObjectStore, Depends(get_store)],
    run_id: RunParam = None,
):
    """Short-lived presigned URLs: the browser downloads meshes from S3 directly, the bucket
    stays private (D8)."""
    run = resolve_run(session, specimen_id, run_id)
    return schemas.Meshes(
        provenance=provenance(run),
        meshes=[
            schemas.Mesh(
                structure=s.name,
                color=s.color,
                url=store.presigned_url(s.mesh_key, expires_s=MESH_URL_TTL_S),
                expires_in_s=MESH_URL_TTL_S,
                faces=s.mesh_faces,
                bytes=s.mesh_bytes,
            )
            for s in sorted(run.structures, key=lambda s: s.name)
            if s.mesh_key
        ],
    )


@router.get("/{specimen_id}/imaging", response_model=schemas.DicomWeb)
def imaging(specimen_id: str, session: SessionDep):
    """Where a DICOMweb viewer finds this specimen's CT series (D8, D10)."""
    s = get_specimen(session, specimen_id)
    return schemas.DicomWeb(dicomweb_root=settings.dicomweb_public_root, series=s.series)
