"""Rewriting a bare DICOM dataset (no preamble, no File Meta) as Part 10."""

import numpy as np
import pydicom
from pydicom.dataset import Dataset
from pydicom.uid import CTImageStorage, ImplicitVRLittleEndian, generate_uid

from cochleahub.storage.dicom import prepare_series


def bare_ct_slice(path, series_uid: str, instance: int) -> bytes:
    ds = Dataset()
    ds.SOPClassUID = CTImageStorage
    ds.SOPInstanceUID = generate_uid()
    ds.StudyInstanceUID = "1.2.3.4"
    ds.SeriesInstanceUID = series_uid
    ds.Modality = "CT"
    ds.InstanceNumber = instance
    ds.Rows = ds.Columns = 4
    ds.PixelSpacing = [0.125, 0.125]
    ds.SliceThickness = 0.125
    ds.BitsAllocated = ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 1
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelData = np.arange(16, dtype=np.int16).tobytes()
    # what OpenEar ships: the bare dataset, implicit VR little endian, nothing in front
    ds.save_as(path, implicit_vr=True, little_endian=True, enforce_file_format=False)
    return ds.PixelData


def test_prepare_series_writes_valid_part10(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    series_uid = generate_uid()
    pixels = [bare_ct_slice(src / f"SLZ+{i:03d}.dcm", series_uid, i) for i in range(3)]
    assert (src / "SLZ+000.dcm").read_bytes()[128:132] != b"DICM"

    info = prepare_series(src, dst, "test_axial")

    assert info.n_instances == 3
    assert info.series_instance_uid == series_uid
    for i, f in enumerate(sorted(dst.glob("*.dcm"))):
        assert f.read_bytes()[128:132] == b"DICM"
        ds = pydicom.dcmread(f)  # no force needed any more
        assert ds.file_meta.TransferSyntaxUID == ImplicitVRLittleEndian
        assert ds.file_meta.MediaStorageSOPInstanceUID == ds.SOPInstanceUID
        assert ds.PixelData == pixels[i]
