"""Relational schema (D8, D16).

Every measurement, distance, QC flag and validation row belongs to a pipeline run, and every
run records the pipeline version that produced it, so each number shown in the dashboard or
quoted by the assistant can be traced back [Margeta2022].
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Specimen(Base):
    __tablename__ = "specimens"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    dataset: Mapped[str] = mapped_column(String(64))
    side: Mapped[str | None] = mapped_column(String(8))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    runs: Mapped[list["PipelineRun"]] = relationship(back_populates="specimen")
    series: Mapped[list["ImagingSeries"]] = relationship(back_populates="specimen")


class ImagingSeries(Base):
    """A CT series archived in Orthanc and reachable over DICOMweb."""

    __tablename__ = "imaging_series"

    id: Mapped[int] = mapped_column(primary_key=True)
    specimen_id: Mapped[str] = mapped_column(ForeignKey("specimens.id"))
    label: Mapped[str] = mapped_column(String(64))
    modality: Mapped[str] = mapped_column(String(8))
    study_instance_uid: Mapped[str] = mapped_column(String(64))
    series_instance_uid: Mapped[str] = mapped_column(String(64), unique=True)
    orthanc_series_id: Mapped[str] = mapped_column(String(64))
    n_instances: Mapped[int] = mapped_column(Integer)
    rows: Mapped[int] = mapped_column(Integer)
    columns: Mapped[int] = mapped_column(Integer)
    pixel_spacing_mm: Mapped[float] = mapped_column(Float)
    slice_thickness_mm: Mapped[float] = mapped_column(Float)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    specimen: Mapped[Specimen] = relationship(back_populates="series")


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = (UniqueConstraint("specimen_id", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    specimen_id: Mapped[str] = mapped_column(ForeignKey("specimens.id"))
    pipeline_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_s: Mapped[float] = mapped_column(Float)
    voxel_size_mm: Mapped[float | None] = mapped_column(Float)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    qc_status: Mapped[str | None] = mapped_column(String(32))
    qc_errors: Mapped[int] = mapped_column(Integer, default=0)
    qc_warnings: Mapped[int] = mapped_column(Integer, default=0)
    qc_info: Mapped[int] = mapped_column(Integer, default=0)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    specimen: Mapped[Specimen] = relationship(back_populates="runs")
    structures: Mapped[list["StructureMeasurement"]] = relationship(cascade="all, delete-orphan")
    cochlea: Mapped["CochleaDimensions | None"] = relationship(cascade="all, delete-orphan")
    distances: Mapped[list["Distance"]] = relationship(cascade="all, delete-orphan")
    qc_flags: Mapped[list["QcFlag"]] = relationship(cascade="all, delete-orphan")
    validations: Mapped[list["ValidationResult"]] = relationship(cascade="all, delete-orphan")


class StructureMeasurement(Base):
    __tablename__ = "structure_measurements"
    __table_args__ = (UniqueConstraint("run_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(64))
    segment_id: Mapped[str] = mapped_column(String(32))
    color: Mapped[list] = mapped_column(JSON)
    voxel_count: Mapped[int] = mapped_column(Integer)
    volume_mm3: Mapped[float] = mapped_column(Float)
    surface_area_mm2: Mapped[float | None] = mapped_column(Float)
    length_mm: Mapped[float] = mapped_column(Float)
    width_mm: Mapped[float] = mapped_column(Float)
    thickness_mm: Mapped[float] = mapped_column(Float)
    centroid_lps_mm: Mapped[list] = mapped_column(JSON)
    connected_components: Mapped[int] = mapped_column(Integer)
    largest_component_fraction: Mapped[float] = mapped_column(Float)
    mesh_key: Mapped[str | None] = mapped_column(String(256))
    mesh_faces: Mapped[int | None] = mapped_column(Integer)
    mesh_bytes: Mapped[int | None] = mapped_column(Integer)


class CochleaDimensions(Base):
    __tablename__ = "cochlea_dimensions"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"), primary_key=True
    )
    a_mm: Mapped[float] = mapped_column(Float)
    b_mm: Mapped[float] = mapped_column(Float)
    height_mm: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(Text)


class Distance(Base):
    __tablename__ = "distances"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"))
    from_structure: Mapped[str] = mapped_column(String(64))
    to_structure: Mapped[str] = mapped_column(String(64))
    meaning: Mapped[str] = mapped_column(Text)
    distance_mm: Mapped[float] = mapped_column(Float)
    point_a_lps_mm: Mapped[list] = mapped_column(JSON)
    point_b_lps_mm: Mapped[list] = mapped_column(JSON)


class QcFlag(Base):
    __tablename__ = "qc_flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"))
    severity: Mapped[str] = mapped_column(String(16))
    code: Mapped[str] = mapped_column(String(64))
    structure: Mapped[str | None] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    value: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(String(64))


class ValidationResult(Base):
    """One structure compared with one reference (Slicer or the dataset's meshes)."""

    __tablename__ = "validation_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"))
    reference: Mapped[str] = mapped_column(String(32))
    reference_detail: Mapped[str] = mapped_column(Text)
    structure: Mapped[str] = mapped_column(String(64))
    volume_rel_diff: Mapped[float | None] = mapped_column(Float)
    surface_area_rel_diff: Mapped[float | None] = mapped_column(Float)
    mean_distance_mm: Mapped[float | None] = mapped_column(Float)
    p95_distance_mm: Mapped[float | None] = mapped_column(Float)
    max_distance_mm: Mapped[float | None] = mapped_column(Float)
