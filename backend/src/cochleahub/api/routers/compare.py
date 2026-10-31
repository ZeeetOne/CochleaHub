"""Cross-specimen comparison against published ranges (D5, D14).

Each specimen contributes the value from its latest completed run. Specimens without that
value are listed with `value: null` instead of being dropped, so a chart or the assistant can
tell "not measured" from "not present".
"""

from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from cochleahub.api import schemas
from cochleahub.api.deps import get_session
from cochleahub.api.queries import latest_run, provenance
from cochleahub.db.models import PipelineRun, Specimen
from cochleahub.pipeline.reference_ranges import COCHLEA, SCALA_TYMPANI_VOLUME, ReferenceRange

router = APIRouter(tags=["compare"])

SessionDep = Annotated[Session, Depends(get_session)]


class Metric(StrEnum):
    volume_mm3 = "volume_mm3"
    surface_area_mm2 = "surface_area_mm2"
    length_mm = "length_mm"
    width_mm = "width_mm"
    thickness_mm = "thickness_mm"
    cochlea_a_mm = "cochlea_a_mm"
    cochlea_b_mm = "cochlea_b_mm"
    cochlea_height_mm = "cochlea_height_mm"


UNITS = {Metric.volume_mm3: "mm3", Metric.surface_area_mm2: "mm2"}


def is_cochlea(metric: Metric) -> bool:
    return metric.startswith("cochlea_")


def reference_for(metric: Metric, structure: str | None) -> ReferenceRange | None:
    if is_cochlea(metric):
        return COCHLEA.get(metric.removeprefix("cochlea_"))
    if metric is Metric.volume_mm3 and structure == "Scala Tympani":
        return SCALA_TYMPANI_VOLUME
    return None


def value_of(run: PipelineRun, metric: Metric, structure: str | None) -> float | None:
    if is_cochlea(metric):
        return getattr(run.cochlea, metric.removeprefix("cochlea_"), None)
    s = next((s for s in run.structures if s.name == structure), None)
    return getattr(s, metric.value) if s else None


@router.get("/compare", response_model=schemas.Comparison)
def compare(
    session: SessionDep,
    metric: Metric,
    structure: Annotated[
        str | None, Query(description="Required for per-structure metrics, e.g. 'Scala Tympani'.")
    ] = None,
    specimens: Annotated[list[str] | None, Query(description="Default: all specimens.")] = None,
):
    if not is_cochlea(metric) and not structure:
        raise HTTPException(422, f"Metric '{metric}' needs a 'structure' parameter.")
    q = select(Specimen).order_by(Specimen.id)
    if specimens:
        q = q.where(Specimen.id.in_(specimens))
    values = []
    for s in session.scalars(q):
        run = latest_run(session, s.id)
        values.append(schemas.ComparedValue(
            specimen_id=s.id,
            value=value_of(run, metric, structure) if run else None,
            provenance=provenance(run) if run else None,
        ))
    ref = reference_for(metric, structure)
    return schemas.Comparison(
        metric=metric,
        unit=UNITS.get(metric, "mm"),
        structure=None if is_cochlea(metric) else structure,
        reference=schemas.ReferenceRange(**vars(ref)) if ref else None,
        values=values,
    )


@router.get("/reference-ranges", response_model=dict[str, schemas.ReferenceRange])
def reference_ranges():
    """Published ranges the QC and comparison views use, with their source keys."""
    ranges = {f"cochlea_{k}": v for k, v in COCHLEA.items()}
    ranges["scala_tympani_volume_mm3"] = SCALA_TYMPANI_VOLUME
    return {k: schemas.ReferenceRange(**vars(v)) for k, v in ranges.items()}
