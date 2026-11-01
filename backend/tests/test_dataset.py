import pytest

from cochleahub.config import settings
from cochleahub.pipeline.dataset import find_specimen, read_segments

files = find_specimen(settings.dataset_path, settings.specimen_id)
pytestmark = pytest.mark.skipif(
    not files.segmentation.exists(), reason="OpenEar dataset not available"
)
SPECIMENS = sorted(p.name.lower() for p in settings.dataset_path.iterdir()
                   if (p / "06_Segmentation").is_dir()) if settings.dataset_path.is_dir() else []

CRITICAL_STRUCTURES = {"Scala Tympani", "Scala Vestibuli", "Facial Nerve", "Chorda Tympani"}


def test_segmentation_has_critical_structures():
    names = {s.name for s in read_segments(files.segmentation)}
    assert CRITICAL_STRUCTURES <= names


def test_registered_volumes_present():
    assert files.missing() == []


@pytest.mark.parametrize("specimen", SPECIMENS)
def test_every_specimen_maps_onto_the_catalogue(specimen):
    from cochleahub.pipeline.dataset import axial_series, canonical_segments

    f = find_specimen(settings.dataset_path, specimen)
    assert f.missing() == []
    _, resolution = canonical_segments(read_segments(f.segmentation))
    assert not resolution.unmapped and not resolution.duplicates and not resolution.missing
    assert len(f.meshes) == 13 and not f.mesh_resolution.unmapped
    assert axial_series(f, "01_CBCT_Unembedded") and axial_series(f, "02_CBCT_Embedded")
