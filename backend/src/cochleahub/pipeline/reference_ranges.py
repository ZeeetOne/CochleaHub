"""Published ranges used by the out-of-range QC flag (D14).

A value outside these ranges is a warning, not an error: each source covers one
population and one measurement method, which may differ from ours.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReferenceRange:
    low: float
    high: float
    unit: str
    source: str  # key in docs/REFERENCES.md
    population: str


SCALA_TYMPANI_VOLUME = ReferenceRange(
    23.0, 50.0, "mm3", "Dhanasingh2021", "30 adult cadaveric temporal bones, micro-CT"
)

# HRCT of 36 ears of cochlear implant candidates aged 2-17 (min-max of Table 1)
COCHLEA = {
    "a_mm": ReferenceRange(8.17, 9.33, "mm", "Zahara2019", "36 ears, HRCT, ages 2-17"),
    "b_mm": ReferenceRange(5.73, 7.50, "mm", "Zahara2019", "36 ears, HRCT, ages 2-17"),
    "height_mm": ReferenceRange(2.80, 3.72, "mm", "Zahara2019", "36 ears, HRCT, ages 2-17"),
}
