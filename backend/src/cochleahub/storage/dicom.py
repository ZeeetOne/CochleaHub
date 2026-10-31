"""Prepare OpenEar CBCT files for a DICOM archive and upload them to Orthanc (D8, D15).

The OpenEar CBCT files are bare datasets: no 128-byte preamble, no "DICM" prefix and no
File Meta Information, which the DICOM file format (PS3.10) requires. They are rewritten
with a File Meta header built from their own SOP Class/Instance UIDs. Pixel data and all
other elements are kept byte-identical (verified on ZETA), except the retired group-length
elements (gggg,0000), which pydicom drops when writing Part 10. Orthanc then serves the
files over DICOMweb [Jodogne2018].
"""

from dataclasses import dataclass
from pathlib import Path

import httpx
import pydicom
from pydicom.dataset import FileMetaDataset
from pydicom.uid import PYDICOM_IMPLEMENTATION_UID, ImplicitVRLittleEndian


@dataclass
class SeriesInfo:
    label: str
    study_instance_uid: str
    series_instance_uid: str
    n_instances: int
    rows: int
    columns: int
    pixel_spacing_mm: float
    slice_thickness_mm: float
    orthanc_series_id: str | None = None


def to_part10(src: Path, dst: Path) -> pydicom.Dataset:
    ds = pydicom.dcmread(src, force=True)
    if not ds.is_implicit_VR or not ds.is_little_endian:
        raise ValueError(f"{src}: unexpected encoding; only implicit VR little endian is handled")
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = ds.SOPClassUID
    meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    meta.TransferSyntaxUID = ImplicitVRLittleEndian
    meta.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID
    ds.file_meta = meta
    dst.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(dst, enforce_file_format=True)
    return ds


def prepare_series(src_dir: Path, dst_dir: Path, label: str) -> SeriesInfo:
    files = sorted(src_dir.glob("*.dcm"))
    first = None
    for f in files:
        ds = to_part10(f, dst_dir / f.name)
        first = first or ds
    if first is None:
        raise FileNotFoundError(f"no .dcm files in {src_dir}")
    return SeriesInfo(
        label=label,
        study_instance_uid=str(first.StudyInstanceUID),
        series_instance_uid=str(first.SeriesInstanceUID),
        n_instances=len(files),
        rows=int(first.Rows),
        columns=int(first.Columns),
        pixel_spacing_mm=float(first.PixelSpacing[0]),
        slice_thickness_mm=float(first.SliceThickness),
    )


class Orthanc:
    def __init__(self, url: str):
        self.client = httpx.Client(base_url=url, timeout=60)

    def upload_series(self, directory: Path) -> str:
        """Upload every file of a series; returns Orthanc's series id."""
        series_id = None
        for f in sorted(directory.glob("*.dcm")):
            r = self.client.post("/instances", content=f.read_bytes(),
                                 headers={"Content-Type": "application/dicom"})
            r.raise_for_status()
            series_id = r.json()["ParentSeries"]
        if series_id is None:
            raise FileNotFoundError(f"no .dcm files in {directory}")
        return series_id

    def series_instance_count(self, series_id: str) -> int:
        r = self.client.get(f"/series/{series_id}")
        r.raise_for_status()
        return len(r.json()["Instances"])
