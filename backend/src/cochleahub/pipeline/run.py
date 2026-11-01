"""Stage 2 orchestration: measure every segment, export meshes, compute distances,
and record the run with the pipeline version [Margeta2022]."""

import json
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

from cochleahub import __version__
from cochleahub.pipeline.dataset import SpecimenFiles
from cochleahub.pipeline.distance import min_distance
from cochleahub.pipeline.measure import cochlear_dimensions, shape_metrics
from cochleahub.pipeline.mesh import (
    closed_volume,
    edge_topology,
    export_display_mesh,
    mask_to_mesh,
)
from cochleahub.pipeline.segmentation import Segmentation

# Large structures are meshed on a coarser grid; their exact surface is not measured
COARSE_STEP = {"bone": 3, "sinus dura": 2}

# (structure A, structure B, why it matters)
DISTANCE_PAIRS = [
    # The chorda tympani branches off the facial nerve, so their minimum gap is ~0 mm;
    # the recess width further up needs landmarks and is not measured here.
    ("Facial Nerve", "Chorda Tympani", "branch point (0 mm expected), not the recess width"),
    ("Facial Nerve", "Scala Tympani", "facial nerve to cochlea"),
    ("Facial Nerve", "Scala Vestibuli", "facial nerve to labyrinth"),
    ("Chorda Tympani", "Scala Tympani", "chorda tympani to cochlea"),
]


def slug(name: str) -> str:
    return name.lower().replace(" ", "_")


def measure_specimen(files: SpecimenFiles, output_dir: Path) -> dict:
    started = time.perf_counter()
    run = {
        "specimen_id": files.specimen_id,
        "pipeline_version": __version__,
        "started_at": datetime.now(UTC).isoformat(),
        "status": "running",
        "errors": [],
    }
    structures, meshes = {}, {}
    try:
        seg = Segmentation(files.segmentation)
        run["voxel_size_mm"] = min(seg.image.GetSpacing())
        mesh_dir = output_dir / "meshes" / files.specimen_id
        for s in seg.segments:
            try:
                mask = seg.mask(s.name)
                step = COARSE_STEP.get(s.name.lower(), 1)
                mesh = mask_to_mesh(mask, step=step)
                meshes[s.name] = mesh
                structures[s.name] = {
                topology = edge_topology(mesh)
                    "segment_id": s.segment_id,
                    "color": list(s.color),
                    **shape_metrics(mask),
                    # surface area only on full-resolution meshes
                    "surface_area_mm2": float(mesh.area) if step == 1 else None,
                    "mesh_volume_mm3": closed_volume(mesh, topology),
                    "mesh": {
                        "step_voxels": step,
                        **export_display_mesh(mesh, mesh_dir / f"{slug(s.name)}.glb"),
                    },
                        **topology,
                }
            except Exception as e:  # noqa: BLE001 - record and keep measuring the others
                run["errors"].append({"structure": s.name, "error": repr(e)})

        cochlea = cochlear_dimensions(seg.mask("Scala Tympani"))
        distances = [
            {"from": a, "to": b, "meaning": why, **min_distance(meshes[a], meshes[b])}
            for a, b, why in DISTANCE_PAIRS
            if a in meshes and b in meshes
        ]
        run["status"] = "completed_with_errors" if run["errors"] else "completed"
    except Exception:  # noqa: BLE001 - a failed run is recorded, not raised
        run["status"] = "failed"
        run["errors"].append({"structure": None, "error": traceback.format_exc()})
        cochlea, distances = None, []

    run["duration_s"] = round(time.perf_counter() - started, 2)
    result = {
        "run": run,
        "structures": structures,
        "cochlea": cochlea,
        "distances": distances,
    }
    out = output_dir / "outputs" / f"{files.specimen_id}_measurements.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2))
    return result
