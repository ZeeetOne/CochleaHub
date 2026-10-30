"""Minimum distances between critical structures (D6).

The facial recess, bounded by the facial nerve and chorda tympani, is the surgical
access route to the cochlea [Noble2008]; the gaps between these structures are
therefore reported. Distances are vertex-to-vertex on the marching-cubes meshes, so
their resolution is about one voxel (0.125 mm for OpenEar).
"""

import numpy as np
import trimesh
from scipy.spatial import cKDTree


def min_distance(a: trimesh.Trimesh, b: trimesh.Trimesh) -> dict:
    tree = cKDTree(b.vertices)
    dist, idx = tree.query(a.vertices)
    i = int(np.argmin(dist))
    return {
        "distance_mm": float(dist[i]),
        "point_a_lps_mm": a.vertices[i].tolist(),
        "point_b_lps_mm": b.vertices[idx[i]].tolist(),
    }
