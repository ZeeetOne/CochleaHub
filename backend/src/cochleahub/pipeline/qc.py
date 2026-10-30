"""Automatic quality-control flags (D14).

Nautilus flags failures at each pipeline stage so that faulty cases can be excluded
from analysis [Margeta2022]. Each flag carries a severity:
    error   - the number should not be used (e.g. disagreement with a reference tool)
    warning - usable, but read with care (method-sensitive, outside a published range)
    info    - context, no action needed
Thresholds below are engineering choices documented in D14, except published ranges.
"""

from dataclasses import asdict, dataclass

from cochleahub.pipeline import reference_ranges as ref

VOLUME_TOLERANCE = 0.01  # vs. Slicer: same voxels, so volumes must agree
AREA_TOLERANCE = 0.10  # vs. Slicer: area depends on smoothing (see D14)
MESH_VOLUME_TOLERANCE = 0.02  # our mesh vs. our voxel volume
FRAGMENT_THRESHOLD = 0.99  # largest connected component share of the volume


@dataclass
class Flag:
    severity: str
    code: str
    structure: str | None
    message: str
    value: float | None = None
    threshold: float | None = None
    source: str | None = None


def _range_flag(structure: str, metric: str, value: float, r: ref.ReferenceRange) -> Flag | None:
    if r.low <= value <= r.high:
        return None
    return Flag(
        "warning", "OUT_OF_PUBLISHED_RANGE", structure,
        f"{metric} {value:.2f} {r.unit} outside {r.low}-{r.high} {r.unit} ({r.population})",
        value, None, r.source,
    )


def quality_flags(measurements: dict, validation: dict) -> list[dict]:
    flags: list[Flag] = []
    run = measurements["run"]
    if run["status"] != "completed":
        flags.append(Flag("error", "RUN_NOT_COMPLETED", None, f"run status {run['status']}"))
    for e in run["errors"]:
        flags.append(Flag("error", "STRUCTURE_FAILED", e["structure"], e["error"]))

    for name, s in measurements["structures"].items():
        frac = s["largest_component_fraction"]
        if s["connected_components"] > 1:
            severity = "warning" if frac < FRAGMENT_THRESHOLD else "info"
            stray = round(s["voxel_count"] * (1 - frac))
            flags.append(Flag(
                severity, "FRAGMENTED", name,
                f"{s['connected_components']} connected components; {stray} voxels outside the "
                f"largest ({frac:.2%} in it)",
                frac, FRAGMENT_THRESHOLD,
            ))
        if s["mesh_volume_mm3"] is None and s["mesh"]["step_voxels"] == 1:
            flags.append(Flag("error", "MESH_NOT_WATERTIGHT", name, "surface mesh is not closed"))
        elif s["mesh_volume_mm3"] is not None:
            d = abs(s["mesh_volume_mm3"] - s["volume_mm3"]) / s["volume_mm3"]
            if d > MESH_VOLUME_TOLERANCE:
                flags.append(Flag(
                    "warning", "MESH_VOLUME_MISMATCH", name,
                    f"mesh volume differs from voxel volume by {d:.1%}", d, MESH_VOLUME_TOLERANCE,
                ))

    if slicer := validation.get("slicer"):
        for name, r in slicer["structures"].items():
            if r["voxel_count_ours"] != r["voxel_count_slicer"]:
                flags.append(Flag(
                    "error", "SLICER_VOXEL_MISMATCH", name,
                    f"{r['voxel_count_ours']} voxels vs {r['voxel_count_slicer']} in Slicer",
                ))
            if r["volume_rel_diff"] is not None and abs(r["volume_rel_diff"]) > VOLUME_TOLERANCE:
                flags.append(Flag(
                    "error", "SLICER_VOLUME_MISMATCH", name,
                    f"volume differs from Slicer by {r['volume_rel_diff']:+.1%}",
                    r["volume_rel_diff"], VOLUME_TOLERANCE,
                ))
            a = r["surface_area_rel_diff"]
            if a is not None and abs(a) > AREA_TOLERANCE:
                flags.append(Flag(
                    "warning", "AREA_METHOD_SENSITIVE", name,
                    f"surface area differs from Slicer by {a:+.1%}; thin structures depend on "
                    "smoothing",
                    a, AREA_TOLERANCE,
                ))
    else:
        flags.append(Flag("info", "SLICER_REFERENCE_MISSING", None, "no Slicer comparison run"))

    # one voxel of mean deviation per meshing step is accepted
    for name, r in validation["dataset_meshes"]["structures"].items():
        limit = measurements["structures"][name]["mesh"]["step_voxels"] * run["voxel_size_mm"]
        if r["mean_mm"] > limit:
            flags.append(Flag(
                "warning", "SURFACE_DEVIATES_FROM_DATASET_MESH", name,
                f"mean surface distance to the published mesh {r['mean_mm']:.3f} mm",
                r["mean_mm"], limit, "Sieber2019",
            ))

    st = measurements["structures"].get("Scala Tympani")
    if st:
        flags.append(_range_flag("Scala Tympani", "volume", st["volume_mm3"],
                                 ref.SCALA_TYMPANI_VOLUME))
    if cochlea := measurements.get("cochlea"):
        for metric, r in ref.COCHLEA.items():
            flags.append(_range_flag("Cochlea", metric, cochlea[metric], r))

    return [asdict(f) for f in flags if f is not None]


def summarize(flags: list[dict]) -> dict:
    counts = {s: sum(f["severity"] == s for f in flags) for s in ("error", "warning", "info")}
    status = "fail" if counts["error"] else "pass_with_warnings" if counts["warning"] else "pass"
    return {"status": status, **counts}
