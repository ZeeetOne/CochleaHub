"""Canonical anatomical structures and the mapping of source labels onto them (D26).

Segment and mesh names are free text typed by whoever segmented a specimen, so they differ
between specimens of the same dataset (ZETA "Carotis Interna", EPSILON "Carotis"; EPSILON even
has "Vestibulcochlear Nerve"). The terminology tags 3D Slicer stores with each segment are the
default "Tissue" (SRT T-D0050) for all 13 segments of both specimens, so they cannot be used.

The approach follows how radiation oncology handles the same problem across clinics: one
standard list of structure names, and source names mapped onto it [Mayo2018]. Each canonical
structure carries ontology codes, as DICOM Segmentation objects do with coded terminology
instead of free text [Fedorov2016]:

- UBERON ids (open anatomy ontology), verified through the EBI Ontology Lookup Service;
- SNOMED CT ids where the DICOM anatomic code list shipped with 3D Slicer has the structure.

Matching is deterministic: labels are normalised (case, numeric prefixes, "_" and "-", spacing)
and compared with the canonical name and its reviewed synonyms. Nothing is guessed. A label
that matches nothing is reported as unmapped with the closest canonical names as suggestions;
a person reviews it once and adds it to SYNONYMS, after which every specimen using that label
maps automatically. In production, segmentations produced by our own model carry its fixed
label set (e.g. nnU-Net [Isensee2021]; for the cochlea [Noble2011]), so mapping is only needed
at the boundary for external data.

Canonical names are the names already used in measurements, the API and the dashboard.
"""

import difflib
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Structure:
    name: str
    uberon: tuple[str, ...]
    snomed: str | None = None  # SNOMED CT, only when in the DICOM anatomic code list
    synonyms: tuple[str, ...] = ()
    note: str = ""


CATALOG: tuple[Structure, ...] = (
    Structure("Scala Tympani", ("UBERON:0001864",)),
    Structure(
        "Scala Vestibuli", ("UBERON:0001863",),
        note="OpenEar's label also covers the vestibule and semicircular canals (D5)",
    ),
    Structure("Malleus", ("UBERON:0001689",)),
    Structure("Incus", ("UBERON:0001688",)),
    Structure("Stapes", ("UBERON:0001687",)),
    Structure(
        "Cochleovestibular nerve", ("UBERON:0001648",),
        synonyms=("vestibulocochlear nerve", "cochleo vestibular nerve",
                  "vestibulcochlear nerve"),  # EPSILON's spelling, reviewed 2026-11-01
    ),
    Structure("Facial Nerve", ("UBERON:0001647",)),
    Structure("Chorda Tympani", ("UBERON:0009675",)),
    Structure("Tympanic Membrane", ("UBERON:0002364",)),
    Structure(
        "External Auditory Canal", ("UBERON:0001352",), snomed="84301002",
        synonyms=("eac", "external acoustic meatus"),
    ),
    Structure(
        "Sinus Dura", ("UBERON:0005475", "UBERON:0002363"),
        synonyms=("sigmoid sinus and dura",),
        note="sigmoid sinus and adjacent dura in one label [Sieber2019]",
    ),
    Structure(
        "Carotis Interna", ("UBERON:0001532",), snomed="86117002",
        synonyms=("carotis", "internal carotid artery", "carotid artery"),
    ),
    Structure("Bone", ("UBERON:0001678",), snomed="60911003", synonyms=("temporal bone",),
              note="temporal bone specimen"),
)

BY_NAME = {s.name: s for s in CATALOG}


def normalise(label: str) -> str:
    """'01_Scala Tympani' -> 'scala tympani'; 'Sinus - Dura' -> 'sinus dura'."""
    s = re.sub(r"^\d+[_\s-]*", "", label.strip())
    s = re.sub(r"[_\-]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


_LOOKUP: dict[str, str] = {}
for _s in CATALOG:
    for _alias in (_s.name, *_s.synonyms):
        key = normalise(_alias)
        assert _LOOKUP.get(key, _s.name) == _s.name, f"ambiguous synonym {_alias!r}"
        _LOOKUP[key] = _s.name


def canonical(label: str) -> str | None:
    return _LOOKUP.get(normalise(label))


@dataclass
class Resolution:
    mapping: dict[str, str] = field(default_factory=dict)  # source label -> canonical name
    unmapped: dict[str, list[str]] = field(default_factory=dict)  # label -> suggestions
    duplicates: dict[str, list[str]] = field(default_factory=dict)  # canonical -> labels
    missing: list[str] = field(default_factory=list)  # canonical names with no label

    @property
    def renamed(self) -> dict[str, str]:
        return {k: v for k, v in self.mapping.items() if k != v}

    def as_dict(self) -> dict:
        return {"renamed": self.renamed, "unmapped": self.unmapped,
                "duplicates": self.duplicates, "missing": self.missing}


def resolve(labels: list[str]) -> Resolution:
    """Map source labels onto the catalogue. Two labels claiming one structure are both left
    unmapped (we cannot tell which is right)."""
    r = Resolution()
    claims: dict[str, list[str]] = {}
    for label in labels:
        name = canonical(label)
        if name is None:
            names = [s.name for s in CATALOG]
            r.unmapped[label] = difflib.get_close_matches(label, names, n=2, cutoff=0.4)
        else:
            claims.setdefault(name, []).append(label)
    for name, claimed in claims.items():
        if len(claimed) == 1:
            r.mapping[claimed[0]] = name
        else:
            r.duplicates[name] = claimed
    r.missing = [s.name for s in CATALOG if s.name not in claims]
    return r
