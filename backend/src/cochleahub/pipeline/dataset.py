"""Locate and describe the files of one extracted OpenEar specimen.

OpenEar layout (Sieber et al., 2019), as extracted for ZETA:
    01_CBCT_Unembedded/DICOM_*_{X,Y,Z}/   CBCT before embedding (DICOM)
    02_CBCT_Embedded/DICOM_*_{X,Y,Z}/     CBCT after embedding (DICOM)
    03_Microslicing_Raw/*.tif             micro-slicing photographs
    04_Reconstruction_Microslicing/       stacked micro-slicing volume (.nrrd)
    05_Registred_Slicer_Volumes/          CBCT registered to micro-slicing (.nrrd) + transforms
    06_Segmentation/Segmentation.seg.nrrd 3D Slicer multi-layer segmentation
    07_3D_Models/*.ply                    surface meshes per structure
"""

from dataclasses import asdict, dataclass, field
from pathlib import Path

import SimpleITK as sitk


@dataclass
class Segment:
    index: int  # component index in the .seg.nrrd vector image
    segment_id: str
    name: str
    color: tuple[float, float, float]
    extent: tuple[int, ...]  # voxel bounding box: x0 x1 y0 y1 z0 z1


@dataclass
class VolumeInfo:
    path: str
    size: tuple[int, ...]
    spacing_mm: tuple[float, ...]
    origin: tuple[float, ...]
    pixel_type: str
    components: int


@dataclass
class SpecimenFiles:
    specimen_id: str
    root: Path
    segmentation: Path
    registered_volumes: dict[str, Path] = field(default_factory=dict)
    dicom_series: dict[str, Path] = field(default_factory=dict)
    meshes: dict[str, Path] = field(default_factory=dict)
    accuracy_report: Path | None = None

    def missing(self) -> list[str]:
        problems = []
        if not self.segmentation.exists():
            problems.append(str(self.segmentation))
        problems += [str(p) for p in self.registered_volumes.values() if not p.exists()]
        return problems


def find_specimen(root: Path, specimen_id: str) -> SpecimenFiles:
    reg = root / "05_Registred_Slicer_Volumes"
    files = SpecimenFiles(
        specimen_id=specimen_id,
        root=root,
        segmentation=root / "06_Segmentation" / "Segmentation.seg.nrrd",
        registered_volumes={
            "cbct_embedded": reg / "CBCT_Embedded.nrrd",
            "cbct_unembedded": reg / "CBCT_Unembedded.nrrd",
        },
    )
    for group in ("01_CBCT_Unembedded", "02_CBCT_Embedded"):
        for d in sorted((root / group).glob("DICOM_*")):
            files.dicom_series[f"{group}/{d.name}"] = d
    for ply in sorted((root / "07_3D_Models").glob("*.ply")):
        files.meshes[ply.stem] = ply
    acc = reg / "Accuracy Analysis"
    reports = list(acc.glob("Volumetric Error*.txt")) if acc.exists() else []
    files.accuracy_report = reports[0] if reports else None
    return files


def _header(path: Path) -> sitk.ImageFileReader:
    reader = sitk.ImageFileReader()
    reader.SetFileName(str(path))
    reader.ReadImageInformation()  # header only, no voxel data
    return reader


def volume_info(path: Path) -> VolumeInfo:
    r = _header(path)
    return VolumeInfo(
        path=str(path),
        size=r.GetSize(),
        spacing_mm=r.GetSpacing(),
        origin=r.GetOrigin(),
        pixel_type=sitk.GetPixelIDValueAsString(r.GetPixelID()),
        components=r.GetNumberOfComponents(),
    )


def read_segments(seg_path: Path) -> list[Segment]:
    """Parse the Segment<N>_* metadata that 3D Slicer writes into .seg.nrrd headers."""
    r = _header(seg_path)
    meta = {k: r.GetMetaData(k) for k in r.GetMetaDataKeys()}
    segments = []
    n = 0
    while f"Segment{n}_ID" in meta:
        p = f"Segment{n}_"
        segments.append(
            Segment(
                index=n,
                segment_id=meta[p + "ID"],
                name=meta[p + "Name"],
                color=tuple(float(c) for c in meta[p + "Color"].split()),
                extent=tuple(int(e) for e in meta.get(p + "Extent", "").split()),
            )
        )
        n += 1
    return segments


def manifest(files: SpecimenFiles) -> dict:
    return {
        "specimen_id": files.specimen_id,
        "segmentation": asdict(volume_info(files.segmentation)),
        "segments": [asdict(s) for s in read_segments(files.segmentation)],
        "registered_volumes": {
            k: asdict(volume_info(p)) for k, p in files.registered_volumes.items()
        },
        "dicom_series": {
            k: {"path": str(p), "n_files": len(list(p.glob("*.dcm")))}
            for k, p in files.dicom_series.items()
        },
        "meshes": {k: str(p) for k, p in files.meshes.items()},
        "accuracy_report": str(files.accuracy_report) if files.accuracy_report else None,
    }
