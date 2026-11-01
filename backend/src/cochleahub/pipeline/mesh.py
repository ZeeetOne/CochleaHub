"""Surface meshes from binary masks (D13).

Marching cubes [Lorensen1987] on a binary mask produces a staircase surface that
overestimates area by ~8% (measured on synthetic spheres, see tests). Taubin
smoothing [Taubin1995] removes the staircase while preserving volume, bringing the
area error below 1%, so the smoothed mesh is used for area and distances. A
decimated copy is exported as glTF binary for the web viewer.
"""

from pathlib import Path

import numpy as np
import trimesh
from skimage import measure

from cochleahub.pipeline.segmentation import Mask

SMOOTHING_ITERATIONS = 20
# Display meshes above this face count are decimated to keep .glb files small
MAX_DISPLAY_FACES = 150_000


def mask_to_mesh(mask: Mask, step: int = 1) -> trimesh.Trimesh:
    padded = np.pad(mask.array, 1)
    verts, faces, _, _ = measure.marching_cubes(padded, level=0.5, step_size=step)
    # marching_cubes returns (z, y, x) indices of the padded array
    ijk = verts[:, ::-1] - 1.0
    mesh = trimesh.Trimesh(mask.index_to_physical(ijk), faces, process=True)
    trimesh.repair.fix_normals(mesh)
    trimesh.smoothing.filter_taubin(mesh, iterations=SMOOTHING_ITERATIONS)
    return mesh


def edge_topology(mesh: trimesh.Trimesh) -> dict:
    """Open edges (used by one face: a hole) vs non-manifold edges (used by more than two).

    scikit-image's marching cubes (Lewiner et al. variant) joins two voxels that touch only
    along an edge with an edge shared by four faces. Such a surface is still closed, so its
    volume is valid; only open edges mean a hole."""
    _, uses = np.unique(mesh.edges_sorted, axis=0, return_counts=True)
    return {"open_edges": int((uses == 1).sum()), "nonmanifold_edges": int((uses > 2).sum())}


def closed_volume(mesh: trimesh.Trimesh, topology: dict) -> float | None:
    if mesh.is_watertight or (topology["open_edges"] == 0 and mesh.is_winding_consistent):
        return float(mesh.volume)
    return None


def export_display_mesh(mesh: trimesh.Trimesh, path: Path) -> dict:
    display = mesh
    if len(display.faces) > MAX_DISPLAY_FACES:
        display = display.simplify_quadric_decimation(face_count=MAX_DISPLAY_FACES)
    path.parent.mkdir(parents=True, exist_ok=True)
    display.export(path, file_type="glb")
    return {"path": path.name, "faces": len(display.faces), "bytes": path.stat().st_size}
