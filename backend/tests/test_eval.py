"""Programmatic graders of the assistant evaluation: an oracle answer passes, a made-up or empty
one fails."""

from cochleahub.assistant.grounding import grounded, numbers_in
from cochleahub.evaluation.assistant_eval import citation_ok, wilson

SOURCES = '{"from_structure": "Facial Nerve", "distance_mm": 1.1801} {"rel": 0.1526} 2.80-3.72'


def test_numbers_skip_ids_versions_and_markers():
    text = "1.18 mm [S3], run 19ac527c, pipeline v0.1.0, range 23-50"
    assert numbers_in(text) == [1.18, 23.0, 50.0]


def test_oracle_answer_is_grounded():
    ok, missing = grounded("About 1.2 mm; area +15.3 % vs Slicer; range 2.8-3.72 mm.", SOURCES, "")
    assert ok and missing == []


def test_made_up_number_is_not_grounded():
    ok, missing = grounded("The cochlear duct length is 31.5 mm.", SOURCES, "")
    assert not ok and missing == [31.5]


def test_counts_and_years_are_not_values():
    assert grounded("5 warnings, 0 errors (Zahara et al., 2019).", SOURCES, "")[0]


def test_citation_check():
    case = {"sources": ["distances", "Facial Nerve-Scala Tympani"]}
    hit = [{"source": "api:/api/v1/specimens/zeta/distances?run_id=x#Facial Nerve-Scala Tympani"}]
    miss = [{"source": "api:/api/v1/specimens/zeta/distances?run_id=x#Facial Nerve-Chorda Tympani"}]
    assert citation_ok(case, hit) and not citation_ok(case, miss)
    assert citation_ok({"sources": ["docs/"]}, [{"source": "docs/DECISIONS.md#d6"}])
    assert citation_ok({"sources": []}, []) is None


def test_wilson_interval():
    lo, hi = wilson(20, 25)
    assert 0.6 < lo < 0.8 and 0.85 < hi < 0.95


def test_decimal_comma_and_thousands_dot():
    # Indonesian: "34,65 mm3 dari 17.741 voxel"
    ok, missing = grounded("Volume 34,65 mm3 dari 17.741 voxel.", '{"volume_mm3": 34.6504, '
                           '"voxel_count": 17741}', "")
    assert ok, missing


def test_difference_of_shown_values_is_grounded():
    assert grounded("about 0.64 mm above the upper limit", '{"value_mm": 4.359, "high": 3.72}',
                    "")[0]
