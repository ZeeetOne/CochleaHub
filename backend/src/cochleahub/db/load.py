"""Load pipeline outputs (JSON + meshes) into PostgreSQL and S3 (stage 4)."""

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from cochleahub.db.models import (
    CochleaDimensions,
    Distance,
    ImagingSeries,
    PipelineRun,
    QcFlag,
    Specimen,
    StructureMeasurement,
    ValidationResult,
)
from cochleahub.storage.dicom import SeriesInfo
from cochleahub.storage.objects import ObjectStore

# Specimen facts not contained in the pipeline outputs. ZETA's side comes from its CBCT
# folder name "rechts" (German: right).
SPECIMENS = {
    "zeta": {
        "dataset": "OpenEar",
        "side": "right",
        "description": "Cadaveric temporal bone; CBCT before/after embedding, micro-slicing, "
        "13-structure segmentation [Sieber2019].",
    }
}


def upsert_specimen(session: Session, specimen_id: str) -> Specimen:
    specimen = session.get(Specimen, specimen_id)
    if specimen is None:
        facts = SPECIMENS.get(specimen_id, {"dataset": "unknown"})
        specimen = Specimen(id=specimen_id, created_at=datetime.now(UTC), **facts)
        session.add(specimen)
    return specimen


def load_run(
    session: Session,
    specimen_id: str,
    measurements: dict,
    validation: dict,
    mesh_dir: Path,
    store: ObjectStore,
) -> tuple[PipelineRun, bool]:
    """Insert one pipeline run with all its results. Returns (run, created)."""
    upsert_specimen(session, specimen_id)
    r = measurements["run"]
    started_at = datetime.fromisoformat(r["started_at"])
    existing = session.scalar(
        select(PipelineRun).where(
            PipelineRun.specimen_id == specimen_id, PipelineRun.started_at == started_at
        )
    )
    if existing:
        return existing, False

    qc = validation["qc"]["summary"]
    run = PipelineRun(
        specimen_id=specimen_id,
        pipeline_version=r["pipeline_version"],
        status=r["status"],
        started_at=started_at,
        duration_s=r["duration_s"],
        voxel_size_mm=r.get("voxel_size_mm"),
        errors=r["errors"],
        qc_status=qc["status"],
        qc_errors=qc["error"],
        qc_warnings=qc["warning"],
        qc_info=qc["info"],
        loaded_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()  # assigns run.id, used in mesh keys

    store.ensure_bucket()
    for name, s in measurements["structures"].items():
        mesh = s["mesh"]
        key = store.upload(mesh_dir / mesh["path"], f"meshes/{specimen_id}/{run.id}/{mesh['path']}")
        run.structures.append(StructureMeasurement(
            name=name,
            segment_id=s["segment_id"],
            color=s["color"],
            voxel_count=s["voxel_count"],
            volume_mm3=s["volume_mm3"],
            surface_area_mm2=s["surface_area_mm2"],
            length_mm=s["length_mm"],
            width_mm=s["width_mm"],
            thickness_mm=s["thickness_mm"],
            centroid_lps_mm=s["centroid_lps_mm"],
            connected_components=s["connected_components"],
            largest_component_fraction=s["largest_component_fraction"],
            mesh_key=key,
            mesh_faces=mesh["faces"],
            mesh_bytes=mesh["bytes"],
        ))

    if c := measurements.get("cochlea"):
        run.cochlea = CochleaDimensions(
            a_mm=c["a_mm"], b_mm=c["b_mm"], height_mm=c["height_mm"], method=c["method"]
        )
    for d in measurements["distances"]:
        run.distances.append(Distance(
            from_structure=d["from"],
            to_structure=d["to"],
            meaning=d["meaning"],
            distance_mm=d["distance_mm"],
            point_a_lps_mm=d["point_a_lps_mm"],
            point_b_lps_mm=d["point_b_lps_mm"],
        ))
    for f in validation["qc"]["flags"]:
        run.qc_flags.append(QcFlag(**f))

    if slicer := validation.get("slicer"):
        for name, v in slicer["structures"].items():
            run.validations.append(ValidationResult(
                reference="slicer",
                reference_detail=slicer["tool"],
                structure=name,
                volume_rel_diff=v["volume_rel_diff"],
                surface_area_rel_diff=v["surface_area_rel_diff"],
            ))
    meshes = validation["dataset_meshes"]
    for name, v in meshes["structures"].items():
        run.validations.append(ValidationResult(
            reference="dataset_mesh",
            reference_detail=meshes["reference"],
            structure=name,
            volume_rel_diff=v["volume_rel_diff"],
            surface_area_rel_diff=v["surface_area_rel_diff"],
            mean_distance_mm=v["mean_mm"],
            p95_distance_mm=v["p95_mm"],
            max_distance_mm=v["max_mm"],
        ))
    return run, True


def record_series(session: Session, specimen_id: str, info: SeriesInfo) -> ImagingSeries:
    upsert_specimen(session, specimen_id)
    row = session.scalar(
        select(ImagingSeries).where(ImagingSeries.series_instance_uid == info.series_instance_uid)
    )
    if row is None:
        row = ImagingSeries(specimen_id=specimen_id, modality="CT", **vars(info))
        session.add(row)
    else:
        for k, v in vars(info).items():
            setattr(row, k, v)
    row.uploaded_at = datetime.now(UTC)
    return row
