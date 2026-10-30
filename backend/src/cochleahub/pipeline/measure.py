"""Global shape metrics per structure (D5), following the Nautilus metric set
[Margeta2022]: volume, surface area, principal dimensions, and cochlear A/B/height."""

import SimpleITK as sitk

from cochleahub.pipeline.segmentation import Mask


def shape_metrics(mask: Mask) -> dict:
    stats = sitk.LabelShapeStatisticsImageFilter()
    stats.ComputeOrientedBoundingBoxOn()
    stats.Execute(sitk.ConnectedComponent(mask.to_sitk()))
    components = len(stats.GetLabels())
    sizes = [stats.GetNumberOfPixels(label) for label in stats.GetLabels()]

    stats.Execute(mask.to_sitk())
    voxels = int(stats.GetNumberOfPixels(1))
    # Oriented bounding box along the structure's principal axes, largest first
    dims = sorted(stats.GetOrientedBoundingBoxSize(1), reverse=True)
    return {
        "voxel_count": voxels,
        "volume_mm3": voxels * mask.voxel_volume,
        "length_mm": dims[0],
        "width_mm": dims[1],
        "thickness_mm": dims[2],
        "centroid_lps_mm": list(stats.GetCentroid(1)),
        "connected_components": components,
        "largest_component_fraction": max(sizes) / voxels,
    }


def cochlear_dimensions(scala_tympani: Mask) -> dict:
    """Landmark-free proxy of cochlear A, B and height.

    A is classically the largest basal-turn diameter through the modiolus and B the
    width perpendicular to it, with height along the modiolar axis. Without round
    window / modiolus landmarks [Stebani2023] we approximate them with the oriented
    bounding box of the scala tympani, whose shortest principal axis follows the
    modiolar axis of the flattened spiral.
    """
    m = shape_metrics(scala_tympani)
    return {
        "a_mm": m["length_mm"],
        "b_mm": m["width_mm"],
        "height_mm": m["thickness_mm"],
        "method": "scala tympani oriented bounding box (landmark-free proxy)",
    }
