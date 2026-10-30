"""Per-segment binary masks from a 3D Slicer multi-layer segmentation (D3).

The .seg.nrrd is a vector image with one 0/1 component per segment. Each mask is
cropped to the segment's Slicer extent (plus a margin) so that downstream steps
work on small arrays while keeping exact physical placement.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import SimpleITK as sitk

from cochleahub.pipeline.dataset import Segment, read_segments


@dataclass
class Mask:
    name: str
    color: tuple[float, float, float]
    array: np.ndarray  # uint8, indexed [z, y, x]
    offset: tuple[int, int, int]  # (x, y, z) index of array[0, 0, 0] in the full image
    spacing: tuple[float, float, float]
    origin: tuple[float, float, float]
    direction: tuple[float, ...]  # 3x3 row-major

    @property
    def voxel_volume(self) -> float:
        return float(np.prod(self.spacing))

    def to_sitk(self) -> sitk.Image:
        img = sitk.GetImageFromArray(self.array)
        img.SetSpacing(self.spacing)
        img.SetDirection(self.direction)
        img.SetOrigin(self.index_to_physical(np.array([[0.0, 0.0, 0.0]]))[0])
        return img

    def index_to_physical(self, ijk: np.ndarray) -> np.ndarray:
        """Map (N, 3) local (x, y, z) indices to physical LPS coordinates in mm."""
        d = np.array(self.direction).reshape(3, 3)
        idx = (ijk + np.array(self.offset)) * np.array(self.spacing)
        return np.array(self.origin) + idx @ d.T


class Segmentation:
    def __init__(self, path: Path):
        self.segments: list[Segment] = read_segments(path)
        self.image = sitk.ReadImage(str(path))
        self._voxels = sitk.GetArrayViewFromImage(self.image)  # [z, y, x, component]

    def mask(self, name: str, margin: int = 2) -> Mask:
        seg = next(s for s in self.segments if s.name.lower() == name.lower())
        size = self.image.GetSize()
        x0, x1, y0, y1, z0, z1 = seg.extent
        lo = [max(v - margin, 0) for v in (x0, y0, z0)]
        hi = [min(v + margin + 1, n) for v, n in zip((x1, y1, z1), size)]
        arr = np.ascontiguousarray(
            self._voxels[lo[2] : hi[2], lo[1] : hi[1], lo[0] : hi[0], seg.index]
        )
        return Mask(
            name=seg.name,
            color=seg.color,
            array=(arr > 0).astype(np.uint8),
            offset=tuple(lo),
            spacing=self.image.GetSpacing(),
            origin=self.image.GetOrigin(),
            direction=self.image.GetDirection(),
        )
