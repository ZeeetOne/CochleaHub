"""Surface-area accuracy of our mesh vs. 3D Slicer on spheres of known area (D7).

    python scripts/area_benchmark.py "<path to Slicer.exe>" <work dir>
"""

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import SimpleITK as sitk

from cochleahub.pipeline.mesh import mask_to_mesh
from cochleahub.pipeline.segmentation import Mask

SPACING = 0.125
SCRIPT = Path(__file__).with_name("slicer_segment_statistics.py")


def sphere(radius_mm: float) -> np.ndarray:
    n = int(2 * radius_mm / SPACING) + 20
    z, y, x = np.indices((n, n, n)) * SPACING
    c = n * SPACING / 2
    return (((x - c) ** 2 + (y - c) ** 2 + (z - c) ** 2) <= radius_mm**2).astype(np.uint8)


def main(slicer_exe: str, work: Path) -> None:
    work.mkdir(parents=True, exist_ok=True)
    print(f"{'radius':>8}{'true mm2':>11}{'Slicer':>16}{'CochleaHub':>16}")
    for r in (1.0, 2.0, 5.0):
        arr = sphere(r)
        img = sitk.GetImageFromArray(arr)
        img.SetSpacing((SPACING,) * 3)
        seg, out = work / f"sphere_{r}.seg.nrrd", work / f"sphere_{r}.json"
        sitk.WriteImage(img, str(seg), True)
        subprocess.run(
            [slicer_exe, "--no-splash", "--no-main-window", "--python-script",
             str(SCRIPT), str(seg), str(out)],
            check=True, capture_output=True, timeout=600,
        )
        slicer_area = json.loads(out.read_text())["segments"][0]["surface_area_mm2"]
        mask = Mask("sphere", (1, 1, 1), arr, (0, 0, 0), (SPACING,) * 3, (0, 0, 0),
                    (1, 0, 0, 0, 1, 0, 0, 0, 1))
        ours = mask_to_mesh(mask).area
        true = 4 * math.pi * r**2
        print(f"{r:>6.1f}mm{true:>11.2f}{slicer_area:>9.2f} ({slicer_area / true - 1:+.1%})"
              f"{ours:>9.2f} ({ours / true - 1:+.1%})")


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2]))
