import argparse
import json
import sys

from cochleahub.config import settings
from cochleahub.pipeline.dataset import find_specimen, manifest


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


def main() -> None:
    parser = argparse.ArgumentParser(prog="cochleahub")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("inspect", help="Verify dataset files and write a manifest JSON")
    p.add_argument("--specimen", default=settings.specimen_id)
    p.set_defaults(func=cmd_inspect)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
