"""Stage 3 validation (D7): compare our measurements with two independent references.

1. 3D Slicer Segment Statistics on the same segmentation [Fedorov2012].
2. The surface meshes published with the dataset (07_3D_Models, RAS coordinates)
   [Sieber2019].

Nautilus reports the accuracy of each pipeline stage the same way [Margeta2022].
"""

import json
import re
import subprocess
from pathlib import Path

import numpy as np
import trimesh
from scipy.spatial import cKDTree

from cochleahub.pipeline.dataset import SpecimenFiles

SLICER_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "slicer_segment_statistics.py"
RAS_TO_LPS = np.diag([-1.0, -1.0, 1.0, 1.0])


def rel_diff(ours: float | None, ref: float | None) -> float | None:
    if ours is None or ref is None or ref == 0:
        return None
    return (ours - ref) / ref


def run_slicer_statistics(slicer_exe: Path, segmentation: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(slicer_exe), "--no-splash", "--no-main-window",
            "--python-script", str(SLICER_SCRIPT), str(segmentation), str(out),
        ],
        check=True,
        timeout=1800,
    )


def compare_with_slicer(measurements: dict, slicer: dict) -> dict:
    rows = {}
    for ref in slicer["segments"]:
        ours = measurements["structures"].get(ref["name"])
        if ours is None:
            continue
        rows[ref["name"]] = {
            "voxel_count_ours": ours["voxel_count"],
            "voxel_count_slicer": ref["voxel_count"],
            "volume_rel_diff": rel_diff(ours["volume_mm3"], ref["volume_mm3"]),
            "surface_area_rel_diff": rel_diff(ours["surface_area_mm2"], ref["surface_area_mm2"]),
        }
    return {
        "tool": f"{slicer['tool']} {slicer['slicer_version']}",
        "closed_surface_smoothing": slicer["closed_surface_smoothing"],
        "structures": rows,
    }


def surface_distance(a: trimesh.Trimesh, b: trimesh.Trimesh) -> dict:
    """Symmetric vertex-to-vertex surface distance between two meshes."""
    d_ab = cKDTree(b.vertices).query(a.vertices)[0]
    d_ba = cKDTree(a.vertices).query(b.vertices)[0]
    d = np.concatenate([d_ab, d_ba])
    return {
        "mean_mm": float(d.mean()),
        "p95_mm": float(np.percentile(d, 95)),
        "max_mm": float(d.max()),  # Hausdorff distance
    }


def compare_with_dataset_meshes(
    measurements: dict, files: SpecimenFiles, mesh_dir: Path
) -> dict:
    by_name = {n.lower(): n for n in measurements["structures"]}
    rows = {}
    for stem, ply in files.meshes.items():
        name = by_name.get(re.sub(r"^\d+_", "", stem).lower())
        if name is None:
            continue
        ours_meta = measurements["structures"][name]
        ref = trimesh.load(ply, force="mesh")
        ref.apply_transform(RAS_TO_LPS)
        ours = trimesh.load(mesh_dir / ours_meta["mesh"]["path"], force="mesh")
        rows[name] = {
            "reference_faces": len(ref.faces),
            "volume_rel_diff": rel_diff(
                ours_meta["volume_mm3"], float(ref.volume) if ref.is_watertight else None
            ),
            "surface_area_rel_diff": rel_diff(ours_meta["surface_area_mm2"], float(ref.area)),
            **surface_distance(ours, ref),
        }
    return {"reference": "OpenEar 07_3D_Models (.ply, RAS converted to LPS)", "structures": rows}


def read_dataset_accuracy(report: Path | None) -> dict | None:
    """Parse the dataset's own CBCT-vs-histology accuracy report [Sieber2019]."""
    if report is None:
        return None
    text = report.read_text(errors="ignore")

    def num(label: str) -> float | None:
        m = re.search(rf"{label}\s*:\s*([\d.,]+)", text)
        return float(m.group(1).replace(",", ".")) if m else None

    return {
        "hausdorff_mean": num("Mean"),
        "hausdorff_max": num("Max"),
        "volume_error_percent": num("Volume error"),
        "source": report.name,
    }


def validate_specimen(
    files: SpecimenFiles, output_dir: Path, slicer_exe: Path | None = None
) -> dict:
    measurements = json.loads(
        (output_dir / "outputs" / f"{files.specimen_id}_measurements.json").read_text()
    )
    slicer_json = output_dir / "reference" / f"{files.specimen_id}_slicer_statistics.json"
    if not slicer_json.exists() and slicer_exe:
        run_slicer_statistics(slicer_exe, files.segmentation, slicer_json)

    return {
        "specimen_id": files.specimen_id,
        "pipeline_version": measurements["run"]["pipeline_version"],
        "slicer": (
            compare_with_slicer(measurements, json.loads(slicer_json.read_text()))
            if slicer_json.exists()
            else None
        ),
        "dataset_meshes": compare_with_dataset_meshes(
            measurements, files, output_dir / "meshes" / files.specimen_id
        ),
        "dataset_accuracy_report": read_dataset_accuracy(files.accuracy_report),
    }
