"""Reference measurements from 3D Slicer's Segment Statistics module (D7).

Runs inside 3D Slicer's Python, headless:
    Slicer.exe --no-splash --no-main-window --python-script slicer_segment_statistics.py \
        <Segmentation.seg.nrrd> <output.json>

Always exits Slicer, with code 1 on error, so a caller never hangs on a failed run.
"""

import json
import sys
import traceback

import slicer


def main(seg_path: str, out_path: str) -> None:
    from SegmentStatistics import SegmentStatisticsLogic

    node = slicer.util.loadSegmentation(seg_path)
    logic = SegmentStatisticsLogic()
    params = logic.getParameterNode()
    params.SetParameter("Segmentation", node.GetID())
    params.SetParameter("LabelmapSegmentStatisticsPlugin.enabled", "True")
    params.SetParameter("ClosedSurfaceSegmentStatisticsPlugin.enabled", "True")
    logic.computeStatistics()
    stats = logic.getStatistics()

    # Plain labelmaps (e.g. synthetic test shapes) carry no surface conversion settings, so
    # Slicer skips surface statistics. Creating surfaces up front works but is slow on the
    # full temporal bone (hours instead of < 1 min), so only do it when they are missing.
    surface_key = "ClosedSurfaceSegmentStatisticsPlugin.surface_mm2"
    if any((sid, surface_key) not in stats for sid in stats["SegmentIDs"]):
        node.CreateClosedSurfaceRepresentation()
        logic.computeStatistics()
        stats = logic.getStatistics()

    segmentation = node.GetSegmentation()
    rows = []
    for sid in stats["SegmentIDs"]:
        rows.append(
            {
                "segment_id": sid,
                "name": segmentation.GetSegment(sid).GetName(),
                "voxel_count": stats[sid, "LabelmapSegmentStatisticsPlugin.voxel_count"],
                "volume_mm3": stats[sid, "LabelmapSegmentStatisticsPlugin.volume_mm3"],
                "surface_volume_mm3": stats[sid, "ClosedSurfaceSegmentStatisticsPlugin.volume_mm3"],
                "surface_area_mm2": stats[sid, "ClosedSurfaceSegmentStatisticsPlugin.surface_mm2"],
            }
        )

    with open(out_path, "w") as f:
        json.dump(
            {
                "tool": "3D Slicer Segment Statistics",
                "slicer_version": slicer.app.applicationVersion,
                "closed_surface_smoothing": segmentation.GetConversionParameter("Smoothing factor"),
                "segments": rows,
            },
            f,
            indent=2,
        )


try:
    main(sys.argv[1], sys.argv[2])
    slicer.util.exit(0)
except Exception:  # noqa: BLE001 - always exit Slicer, report the error
    traceback.print_exc()
    slicer.util.exit(1)
