"""Locate and describe the files of one extracted OpenEar specimen.

One folder per specimen, `Dataset/<SPECIMEN>/`, in the OpenEar layout (Sieber et al., 2019):
    01_CBCT_Unembedded/DICOM_*_{X,Y,Z}/   CBCT before embedding (DICOM)
    02_CBCT_Embedded/DICOM_*_{X,Y,Z}/     CBCT after embedding (DICOM)
    05_Registred_Slicer_Volumes/          CBCT registered to micro-slicing (.nrrd) + transforms
    06_Segmentation/Segmentation.seg.nrrd 3D Slicer multi-layer segmentation
    07_3D_Models/*.ply                    surface meshes per structure
(03/04, the micro-slicing photographs and their reconstruction, are not used and not kept.)

File names vary between specimens (`CBCT_Embedded.nrrd` vs `CBCT_EMBEDDED.nrrd`,
`01_Scala Tympani.ply` vs `Scala_Tympani.ply`): files are found case-insensitively and
structure names are mapped onto the canonical catalogue (structures.py, D26).
"""

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import SimpleITK as sitk

from cochleahub.pipeline.structures import Resolution, resolve


@dataclass
class Segment:
    index: int  # component index in the .seg.nrrd vector image
    segment_id: str
    name: str  # canonical name when the label maps onto the catalogue, else the label
    color: tuple[float, float, float]
    extent: tuple[int, ...]  # voxel bounding box: x0 x1 y0 y1 z0 z1
    label: str = ""  # name as written in the segmentation file


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
    meshes: dict[str, Path] = field(default_factory=dict)  # canonical name -> .ply
    mesh_resolution: Resolution | None = None
    accuracy_report: Path | None = None
    side: str | None = None  # "left"/"right" when the dataset states it, else unknown

    def missing(self) -> list[str]:
        problems = []
        if not self.segmentation.exists():
            problems.append(str(self.segmentation))
        problems += [str(p) for p in self.registered_volumes.values() if not p.exists()]
        return problems


# words for the ear side in folder names; OpenEar ZETA's CBCT folder says "rechts" (German)
SIDE_WORDS = {"rechts": "right", "right": "right", "links": "left", "left": "left"}


def child(parent: Path, name: str) -> Path:
    """`parent/name`, matching the name case-insensitively; the plain path if absent."""
    if parent.is_dir():
        for p in parent.iterdir():
            if p.name.lower() == name.lower():
                return p
    return parent / name


def specimen_root(dataset: Path, specimen_id: str) -> Path:
    return child(dataset, specimen_id)


def side_from_names(names: list[str]) -> str | None:
    words = {w for n in names for w in re.split(r"[^a-z]+", n.lower())}
    sides = {SIDE_WORDS[w] for w in words if w in SIDE_WORDS}
    return sides.pop() if len(sides) == 1 else None


def find_specimen(dataset: Path, specimen_id: str) -> SpecimenFiles:
    root = specimen_root(dataset, specimen_id)
    reg = child(root, "05_Registred_Slicer_Volumes")
    files = SpecimenFiles(
        specimen_id=specimen_id,
        root=root,
        segmentation=child(child(root, "06_Segmentation"), "Segmentation.seg.nrrd"),
        registered_volumes={
            "cbct_embedded": child(reg, "CBCT_Embedded.nrrd"),
            "cbct_unembedded": child(reg, "CBCT_Unembedded.nrrd"),
        },
    )
    for group in ("01_CBCT_Unembedded", "02_CBCT_Embedded"):
        for d in sorted(child(root, group).glob("DICOM_*")):
            files.dicom_series[f"{group}/{d.name}"] = d
    plys = {p.stem: p for p in sorted(child(root, "07_3D_Models").glob("*.ply"))}
    files.mesh_resolution = resolve(list(plys))
    files.meshes = {name: plys[stem] for stem, name in files.mesh_resolution.mapping.items()}
    acc = child(reg, "Accuracy Analysis")
    reports = list(acc.glob("Volumetric Error*.txt")) if acc.exists() else []
    files.accuracy_report = reports[0] if reports else None
    files.side = side_from_names([p.name for p in files.dicom_series.values()])
    return files


def axial_series(files: SpecimenFiles, group: str) -> Path | None:
    """The axial (Z) reslice of a CBCT series; X, Y and Z hold the same scan."""
    return next((p for k, p in files.dicom_series.items()
                 if k.startswith(group) and k.upper().endswith("_Z")), None)


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
                label=meta[p + "Name"],
            )
        )
        n += 1
    return segments


def canonical_segments(segments: list[Segment]) -> tuple[list[Segment], Resolution]:
    """Rename segments to canonical structure names; unmapped ones keep their label."""
    resolution = resolve([s.label for s in segments])
    for s in segments:
        s.name = resolution.mapping.get(s.label, s.label)
    return segments, resolution


def manifest(files: SpecimenFiles) -> dict:
    segments, resolution = canonical_segments(read_segments(files.segmentation))
    return {
        "specimen_id": files.specimen_id,
        "root": str(files.root),
        "side": files.side,
        "segmentation": asdict(volume_info(files.segmentation)),
        "segments": [asdict(s) for s in segments],
        "structure_mapping": {
            "segments": resolution.as_dict(),
            "meshes": files.mesh_resolution.as_dict() if files.mesh_resolution else None,
        },
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
