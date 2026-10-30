"""Measurement checks on synthetic shapes with known geometry (no dataset needed)."""

import math

import numpy as np
import pytest

from cochleahub.pipeline.distance import min_distance
from cochleahub.pipeline.measure import cochlear_dimensions, shape_metrics
from cochleahub.pipeline.mesh import mask_to_mesh
from cochleahub.pipeline.segmentation import Mask

SPACING = 0.125
LPS_FLIP = (-1.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 1.0)  # same direction as OpenEar


def ellipsoid_mask(radii_mm, center_mm=(0.0, 0.0, 0.0), shape=(120, 120, 120)) -> Mask:
    z, y, x = np.indices(shape) * SPACING
    c = np.array(shape) * SPACING / 2 + np.array(center_mm)[::-1]
    rx, ry, rz = radii_mm
    inside = ((x - c[2]) / rx) ** 2 + ((y - c[1]) / ry) ** 2 + ((z - c[0]) / rz) ** 2 <= 1
    return Mask(
        name="test",
        color=(1, 1, 1),
        array=inside.astype(np.uint8),
        offset=(0, 0, 0),
        spacing=(SPACING,) * 3,
        origin=(0.0, 0.0, 0.0),
        direction=LPS_FLIP,
    )


def test_sphere_volume_and_area():
    r = 5.0
    mask = ellipsoid_mask((r, r, r))
    m = shape_metrics(mask)
    assert m["volume_mm3"] == pytest.approx(4 / 3 * math.pi * r**3, rel=0.01)
    assert m["connected_components"] == 1

    mesh = mask_to_mesh(mask)
    assert mesh.volume == pytest.approx(m["volume_mm3"], rel=0.01)
    # raw marching cubes overestimates area by ~8%; smoothing brings it within 2%
    assert mesh.area == pytest.approx(4 * math.pi * r**2, rel=0.02)


def test_cochlear_dimensions_follow_principal_axes():
    dims = cochlear_dimensions(ellipsoid_mask((4.5, 3.4, 2.2)))
    assert dims["a_mm"] == pytest.approx(9.0, abs=0.3)
    assert dims["b_mm"] == pytest.approx(6.8, abs=0.3)
    assert dims["height_mm"] == pytest.approx(4.4, abs=0.3)


def test_min_distance_between_spheres():
    a = mask_to_mesh(ellipsoid_mask((2, 2, 2), center_mm=(-3.5, 0, 0)))
    b = mask_to_mesh(ellipsoid_mask((2, 2, 2), center_mm=(3.5, 0, 0)))
    # centres 7 mm apart, radii 2 mm -> 3 mm gap, within one voxel
    assert min_distance(a, b)["distance_mm"] == pytest.approx(3.0, abs=SPACING)
