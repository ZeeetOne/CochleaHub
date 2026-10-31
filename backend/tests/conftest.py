"""Shared fixtures: a small pipeline output and a fake object store."""

import copy

import pytest


class FakeStore:
    def __init__(self):
        self.keys = []

    def ensure_bucket(self):
        pass

    def upload(self, path, key, content_type="model/gltf-binary"):
        self.keys.append(key)
        return key

    def presigned_url(self, key, expires_s=3600):
        return f"https://s3.test/{key}?expires={expires_s}"


MEASUREMENTS = {
    "run": {
        "pipeline_version": "0.1.0",
        "started_at": "2026-10-30T16:48:27+00:00",
        "status": "completed",
        "errors": [],
        "duration_s": 17.5,
        "voxel_size_mm": 0.125,
    },
    "structures": {
        "Scala Tympani": {
            "segment_id": "Segment_1",
            "color": [0.5, 0.7, 0.5],
            "voxel_count": 17741,
            "volume_mm3": 34.65,
            "surface_area_mm2": 119.4,
            "length_mm": 8.97,
            "width_mm": 6.81,
            "thickness_mm": 4.36,
            "centroid_lps_mm": [-21.8, -23.0, 39.0],
            "connected_components": 1,
            "largest_component_fraction": 1.0,
            "mesh_volume_mm3": 34.4,
            "mesh": {"step_voxels": 1, "path": "scala_tympani.glb", "faces": 22726, "bytes": 409796},
        }
    },
    "cochlea": {"a_mm": 8.97, "b_mm": 6.81, "height_mm": 4.36, "method": "proxy"},
    "distances": [
        {
            "from": "Facial Nerve",
            "to": "Scala Tympani",
            "meaning": "facial nerve to cochlea",
            "distance_mm": 1.18,
            "point_a_lps_mm": [0, 0, 0],
            "point_b_lps_mm": [1, 0, 0],
        }
    ],
}

VALIDATION = {
    "qc": {
        "summary": {"status": "pass_with_warnings", "error": 0, "warning": 1, "info": 0},
        "flags": [
            {
                "severity": "warning",
                "code": "OUT_OF_PUBLISHED_RANGE",
                "structure": "Cochlea",
                "message": "height",
                "value": 4.36,
                "threshold": None,
                "source": "Zahara2019",
            }
        ],
    },
    "slicer": None,
    "dataset_meshes": {"reference": "ply", "structures": {}},
}



@pytest.fixture
def measurements():
    return copy.deepcopy(MEASUREMENTS)


@pytest.fixture
def validation():
    return copy.deepcopy(VALIDATION)


@pytest.fixture
def store():
    return FakeStore()
