import argparse
import json
import sys

from cochleahub.config import settings
from cochleahub.pipeline.dataset import find_specimen, manifest
from cochleahub.pipeline.run import measure_specimen


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


def main() -> None:
    parser = argparse.ArgumentParser(prog="cochleahub")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("inspect", help="Verify dataset files and write a manifest JSON")
    p.add_argument("--specimen", default=settings.specimen_id)
    p.set_defaults(func=cmd_inspect)
    p = sub.add_parser("measure", help="Measure structures, export meshes, compute distances")
    p.add_argument("--specimen", default=settings.specimen_id)
    p.set_defaults(func=cmd_measure)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
