import argparse
import json
import sys

from cochleahub.config import REPO_ROOT, settings
from cochleahub.pipeline.dataset import find_specimen, manifest
from cochleahub.pipeline.qc import quality_flags, summarize
from cochleahub.pipeline.report import validation_markdown
from cochleahub.pipeline.run import measure_specimen
from cochleahub.pipeline.validate import validate_specimen


def cmd_inspect(args: argparse.Namespace) -> int:
    files = find_specimen(settings.dataset_path, args.specimen)
    missing = files.missing()
    if missing:
        print("Missing files:\n  " + "\n  ".join(missing), file=sys.stderr)
        return 1

    m = manifest(files)
    seg = m["segmentation"]
    print(f"Specimen {m['specimen_id']}  ({files.root})")
    print(
        f"Segmentation: size {seg['size']}, spacing {seg['spacing_mm']} mm, "
        f"{seg['components']} layers"
    )
    for s in m["segments"]:
        print(f"  [{s['index']:2d}] {s['segment_id']:<11} {s['name']}")
    for k, v in m["registered_volumes"].items():
        print(f"Volume {k}: size {v['size']}, spacing {v['spacing_mm']} mm, {v['pixel_type']}")
    for k, v in m["dicom_series"].items():
        print(f"DICOM {k}: {v['n_files']} files")
    print(f"Meshes: {len(m['meshes'])} .ply")

    out = settings.output_path / "outputs" / f"{args.specimen}_manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(m, indent=2))
    print(f"\nWrote {out}")
    return 0


def cmd_measure(args: argparse.Namespace) -> int:
    files = find_specimen(settings.dataset_path, args.specimen)
    result = measure_specimen(files, settings.output_path)
    run = result["run"]
    print(f"Run {run['status']} in {run['duration_s']} s (pipeline {run['pipeline_version']})")
    for e in run["errors"]:
        print(f"  ERROR {e['structure']}: {e['error']}", file=sys.stderr)

    print(f"\n{'Structure':<26}{'Volume mm3':>12}{'Area mm2':>10}{'L x W x T mm':>22}")
    for name, s in result["structures"].items():
        area = f"{s['surface_area_mm2']:.1f}" if s["surface_area_mm2"] else "-"
        dims = f"{s['length_mm']:.2f} x {s['width_mm']:.2f} x {s['thickness_mm']:.2f}"
        print(f"{name:<26}{s['volume_mm3']:>12.2f}{area:>10}{dims:>22}")

    if c := result["cochlea"]:
        print(f"\nCochlea A {c['a_mm']:.2f} mm, B {c['b_mm']:.2f} mm, height {c['height_mm']:.2f} mm")
    for d in result["distances"]:
        print(f"{d['from']} -> {d['to']}: {d['distance_mm']:.2f} mm ({d['meaning']})")
    return 0 if run["status"] != "failed" else 1


def cmd_validate(args: argparse.Namespace) -> int:
    files = find_specimen(settings.dataset_path, args.specimen)
    outputs = settings.output_path / "outputs"
    measurements = json.loads((outputs / f"{args.specimen}_measurements.json").read_text())

    validation = validate_specimen(files, settings.output_path, settings.slicer_exe)
    flags = quality_flags(measurements, validation)
    validation["qc"] = {"summary": summarize(flags), "flags": flags}
    (outputs / f"{args.specimen}_validation.json").write_text(json.dumps(validation, indent=2))

    report = REPO_ROOT / "docs" / "validation" / f"{args.specimen}.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(validation_markdown(measurements, validation), encoding="utf-8")

    s = validation["qc"]["summary"]
    print(f"QC {s['status']}: {s['error']} errors, {s['warning']} warnings, {s['info']} info")
    for f in flags:
        if f["severity"] != "info":
            print(f"  {f['severity']:<7} {f['code']:<34} {f['structure'] or '-':<24} {f['message']}")
    print(f"\nWrote {report}")
    return 1 if s["status"] == "fail" else 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="cochleahub")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("inspect", help="Verify dataset files and write a manifest JSON")
    p.add_argument("--specimen", default=settings.specimen_id)
    p.set_defaults(func=cmd_inspect)
    p = sub.add_parser("measure", help="Measure structures, export meshes, compute distances")
    p.add_argument("--specimen", default=settings.specimen_id)
    p.set_defaults(func=cmd_measure)
    p = sub.add_parser("validate", help="Compare with Slicer and dataset meshes, raise QC flags")
    p.add_argument("--specimen", default=settings.specimen_id)
    p.set_defaults(func=cmd_validate)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
