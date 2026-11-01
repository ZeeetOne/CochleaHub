"""Canonical structure catalogue and label mapping (D26)."""

import pytest

from cochleahub.pipeline import qc
from cochleahub.pipeline.dataset import side_from_names
from cochleahub.pipeline.structures import CATALOG, canonical, normalise, resolve

ZETA_SEGMENTS = ["Scala Tympani", "Scala Vestibuli", "Malleus", "Incus", "Stapes",
                 "Cochleovestibular nerve", "Facial Nerve", "Chorda Tympani", "Bone",
                 "Tympanic Membrane", "External Auditory Canal", "Sinus Dura", "Carotis Interna"]
EPSILON_SEGMENTS = ["Bone", "Scala Tympani", "Scala Vestibuli", "Malleus", "Incus", "Stapes",
                    "Vestibulcochlear Nerve", "Facial Nerve", "Carotis", "Chorda Tympani",
                    "Tympanic Membrane", "Sinus - Dura", "EAC"]
EPSILON_MESHES = ["Bone", "Carotis", "Chorda_Tympani", "Cochleo_Vestibular_Nerve",
                  "External_Auditory_Canal", "Facial_Nerve", "Incus", "Malleus",
                  "Scala_Tympani", "Scala_Vestibuli", "Sinus_Dura", "Stapes",
                  "Tympanic_Membrane"]


@pytest.mark.parametrize(("label", "expected"), [
    ("01_Scala Tympani", "scala tympani"),
    ("Scala_Tympani", "scala tympani"),
    ("Sinus - Dura", "sinus dura"),
    ("  EAC ", "eac"),
])
def test_normalise(label, expected):
    assert normalise(label) == expected


def test_every_structure_has_an_ontology_code():
    assert len(CATALOG) == 13
    assert all(s.uberon and all(c.startswith("UBERON:") for c in s.uberon) for s in CATALOG)


@pytest.mark.parametrize("labels", [ZETA_SEGMENTS, EPSILON_SEGMENTS, EPSILON_MESHES])
def test_both_specimens_map_completely(labels):
    r = resolve(labels)
    assert not r.unmapped and not r.duplicates and not r.missing
    assert sorted(r.mapping.values()) == sorted(ZETA_SEGMENTS)


def test_epsilon_renames_are_reported():
    r = resolve(EPSILON_SEGMENTS)
    assert r.renamed == {"Vestibulcochlear Nerve": "Cochleovestibular nerve",
                         "Carotis": "Carotis Interna", "Sinus - Dura": "Sinus Dura",
                         "EAC": "External Auditory Canal"}


def test_unknown_labels_are_not_guessed():
    r = resolve(["Scala Tympany", "Round Window", "Facial Nerve"])
    assert canonical("Scala Tympany") is None  # a typo is suggested, never auto-applied
    assert "Scala Tympani" in r.unmapped["Scala Tympany"]
    assert "Round Window" in r.unmapped
    assert r.mapping == {"Facial Nerve": "Facial Nerve"}


def test_two_labels_for_one_structure_are_both_rejected():
    r = resolve(["Carotis", "Carotis Interna"])
    assert r.duplicates == {"Carotis Interna": ["Carotis", "Carotis Interna"]}
    assert r.mapping == {}


def test_mapping_problems_become_qc_flags():
    run = {"status": "completed", "errors": [],
           "structure_mapping": resolve(["Scala Tympany", "Carotis", "Carotis Interna"]).as_dict()}
    flags = qc.quality_flags({"run": run, "structures": {}, "cochlea": None},
                             {"slicer": None, "dataset_meshes": {"structures": {}}})
    codes = {(f["code"], f["severity"]) for f in flags}
    assert ("UNMAPPED_STRUCTURE", "warning") in codes
    assert ("DUPLICATE_STRUCTURE", "error") in codes
    assert ("STRUCTURE_NOT_SEGMENTED", "info") in codes


@pytest.mark.parametrize(("names", "side"), [
    (["DICOM_rechts_20150826_Z", "DICOM_zeta_20150917_Z"], "right"),
    (["DICOM_links_2015_Z"], "left"),
    (["DICOM_Epsilon_20150826_Z"], None),
    (["DICOM_left_Z", "DICOM_rechts_Z"], None),  # contradictory: unknown, not a guess
])
def test_side_comes_from_the_dataset_or_stays_unknown(names, side):
    assert side_from_names(names) == side
