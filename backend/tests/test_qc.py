"""QC flag rules on hand-made measurement/validation records."""

from cochleahub.pipeline.qc import quality_flags, summarize


def structure(**overrides) -> dict:
    s = {
        "voxel_count": 17408,
        "volume_mm3": 34.0,
        "mesh_volume_mm3": 34.0,
        "connected_components": 1,
        "largest_component_fraction": 1.0,
        "mesh": {"step_voxels": 1},
    }
    return s | overrides


def records(structures: dict, cochlea: dict | None = None, slicer_rows: dict | None = None):
    measurements = {
        "run": {"status": "completed", "errors": [], "voxel_size_mm": 0.125},
        "structures": structures,
        "cochlea": cochlea,
    }
    validation = {
        "slicer": {"structures": slicer_rows} if slicer_rows is not None else None,
        "dataset_meshes": {"structures": {}},
    }
    return measurements, validation


def codes(flags: list[dict]) -> set[tuple[str, str]]:
    return {(f["severity"], f["code"]) for f in flags}


def test_clean_record_passes():
    m, v = records({"Scala Tympani": structure()}, slicer_rows={})
    flags = quality_flags(m, v)
    assert summarize(flags)["status"] == "pass"


def test_fragment_severity_depends_on_largest_share():
    m, v = records(
        {
            "A": structure(connected_components=3, largest_component_fraction=0.999),
            "B": structure(connected_components=2, largest_component_fraction=0.80),
        },
        slicer_rows={},
    )
    found = {(f["structure"], f["severity"]) for f in quality_flags(m, v) if f["code"] == "FRAGMENTED"}
    assert found == {("A", "info"), ("B", "warning")}


def test_slicer_volume_disagreement_is_an_error():
    rows = {
        "A": {
            "voxel_count_ours": 100,
            "voxel_count_slicer": 90,
            "volume_rel_diff": 0.11,
            "surface_area_rel_diff": 0.02,
        }
    }
    m, v = records({"A": structure()}, slicer_rows=rows)
    flags = quality_flags(m, v)
    assert {("error", "SLICER_VOXEL_MISMATCH"), ("error", "SLICER_VOLUME_MISMATCH")} <= codes(flags)
    assert summarize(flags)["status"] == "fail"


def test_out_of_published_range_is_a_warning_with_source():
    cochlea = {"a_mm": 9.0, "b_mm": 6.8, "height_mm": 4.4}
    m, v = records({}, cochlea=cochlea, slicer_rows={})
    flags = [f for f in quality_flags(m, v) if f["code"] == "OUT_OF_PUBLISHED_RANGE"]
    assert [(f["severity"], f["source"]) for f in flags] == [("warning", "Zahara2019")]
    assert "height_mm" in flags[0]["message"]
