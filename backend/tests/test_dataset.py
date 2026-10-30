import pytest

from cochleahub.config import settings
from cochleahub.pipeline.dataset import find_specimen, read_segments

files = find_specimen(settings.dataset_path, settings.specimen_id)
pytestmark = pytest.mark.skipif(
    not files.segmentation.exists(), reason="OpenEar dataset not available"
)

CRITICAL_STRUCTURES = {"Scala Tympani", "Scala Vestibuli", "Facial Nerve", "Chorda Tympani"}


def test_segmentation_has_critical_structures():
    names = {s.name for s in read_segments(files.segmentation)}
    assert CRITICAL_STRUCTURES <= names


def test_registered_volumes_present():
    assert files.missing() == []
