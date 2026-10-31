"""Response models (D9, D17).

Every result that comes from a pipeline run carries a `Provenance` block, so the dashboard and
the assistant can always say which run and pipeline version produced a number [Margeta2022].
The models also define the OpenAPI schema the frontend types are generated from.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Orm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Provenance(Orm):
    run_id: uuid.UUID
    specimen_id: str
    pipeline_version: str
    started_at: datetime
    qc_status: str | None


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    pipeline_version: str
    checks: dict[str, str] = Field(
        default_factory=dict, description="Per dependency: 'ok' or the error message."
    )


# --- runs -----------------------------------------------------------------------------------


class RunSummary(Orm):
    id: uuid.UUID
    specimen_id: str
    pipeline_version: str
    status: str
    started_at: datetime
    duration_s: float
    voxel_size_mm: float | None
    qc_status: str | None
    qc_errors: int
    qc_warnings: int
    qc_info: int
    loaded_at: datetime


class Run(RunSummary):
    errors: list


class QcFlag(Orm):
    severity: Literal["error", "warning", "info"]
    code: str
    structure: str | None
    message: str
    value: float | None
    threshold: float | None
    source: str | None = Field(description="Reference key (docs/REFERENCES.md) behind the check.")


class QcReport(BaseModel):
    provenance: Provenance
    status: str | None
    counts: dict[str, int]
    flags: list[QcFlag]


class ValidationRow(Orm):
    reference: Literal["slicer", "dataset_mesh"]
    reference_detail: str
    structure: str
    volume_rel_diff: float | None
    surface_area_rel_diff: float | None
    mean_distance_mm: float | None
    p95_distance_mm: float | None
    max_distance_mm: float | None


class ValidationReport(BaseModel):
    provenance: Provenance
    results: list[ValidationRow]


# --- specimens and measurements -------------------------------------------------------------


class ImagingSeries(Orm):
    label: str
    modality: str
    study_instance_uid: str
    series_instance_uid: str
    n_instances: int
    rows: int
    columns: int
    pixel_spacing_mm: float
    slice_thickness_mm: float


class SpecimenSummary(Orm):
    id: str
    dataset: str
    side: str | None
    description: str | None
    latest_run: RunSummary | None = None


class Specimen(SpecimenSummary):
    series: list[ImagingSeries]
    n_runs: int


class Structure(Orm):
    name: str
    segment_id: str
    color: list[float]
    voxel_count: int
    volume_mm3: float
    surface_area_mm2: float | None
    length_mm: float = Field(description="Longest oriented-bounding-box edge.")
    width_mm: float
    thickness_mm: float
    centroid_lps_mm: list[float]
    connected_components: int
    largest_component_fraction: float


class Measurements(BaseModel):
    provenance: Provenance
    structures: list[Structure]


class ReferenceRange(BaseModel):
    low: float
    high: float
    unit: str
    source: str
    population: str


class CochleaValue(BaseModel):
    value_mm: float
    reference: ReferenceRange | None
    in_range: bool | None


class Cochlea(BaseModel):
    provenance: Provenance
    method: str
    a: CochleaValue
    b: CochleaValue
    height: CochleaValue


class Distance(Orm):
    from_structure: str
    to_structure: str
    meaning: str
    distance_mm: float
    point_a_lps_mm: list[float]
    point_b_lps_mm: list[float]


class Distances(BaseModel):
    provenance: Provenance
    distances: list[Distance]


class Mesh(BaseModel):
    structure: str
    color: list[float]
    url: str = Field(description="Presigned GET URL for the glTF binary; expires.")
    expires_in_s: int
    faces: int | None
    bytes: int | None


class Meshes(BaseModel):
    provenance: Provenance
    coordinate_system: Literal["LPS"] = "LPS"
    meshes: list[Mesh]


class DicomWeb(BaseModel):
    dicomweb_root: str = Field(description="Base URL for QIDO-RS / WADO-RS, as seen by a browser.")
    series: list[ImagingSeries]


# --- comparison -----------------------------------------------------------------------------


class ComparedValue(BaseModel):
    specimen_id: str
    value: float | None
    provenance: Provenance | None


class Comparison(BaseModel):
    metric: str
    unit: str
    structure: str | None
    reference: ReferenceRange | None
    values: list[ComparedValue]
