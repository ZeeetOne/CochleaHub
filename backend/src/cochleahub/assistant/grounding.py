"""Is every number in an answer backed by a source the model was shown? (D20, D21)

Used twice: at run time, the agent asks the model to correct an answer with unbacked numbers
(a guard that does not depend on the model), and in the evaluation, as the "grounded" grade.
A number counts as backed if it appears in a source or the question, as a percentage of a
shown fraction, or as the difference of two shown values ("0.64 mm above the upper limit").
Counts, list numbers and years are ignored. Decimal commas are read as in Indonesian/European
writing.
"""

import re

NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?!\w)")


def number_close(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.011, 0.025 * abs(b))


def _clean(text: str) -> str:
    text = re.sub(r"\[S\d+\]", " ", text)
    text = re.sub(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){0,4}\b", " ", text)  # run ids
    text = re.sub(r"\bv?\d+\.\d+\.\d+\b", " ", text)  # versions
    # Indonesian/European decimal comma ("34,65") -> "34.65"; a list keeps its space ("5, 6")
    return re.sub(r"(?<=\d),(?=\d)", ".", text)


def numbers_in(text: str) -> list[float]:
    """Numbers a reader would take as values; skips run ids, versions and [S#] markers."""
    return [float(m) for m in NUMBER.findall(_clean(text))]


def readings(text: str) -> list[tuple[float, ...]]:
    """Each number with its possible readings: "17.741" is 17.741, or 17741 written with an
    Indonesian thousands separator."""
    out = []
    for m in NUMBER.findall(_clean(text)):
        v = float(m)
        alt = (v * 1000,) if re.fullmatch(r"-?\d{1,3}\.\d{3}", m) else ()
        out.append((v, *alt))
    return out


def grounded(answer: str, sources_text: str, question: str) -> tuple[bool, list[float]]:
    """Every non-trivial number in the answer must come from what the model was shown: a value
    in a tool result, that value as a percentage, or the difference of two shown values
    ("0.64 mm above the upper limit")."""
    shown = numbers_in(sources_text) + numbers_in(question)
    allowed = shown + [v * 100 for v in shown]
    small = sorted({v for v in shown if abs(v) < 1000})
    allowed += [abs(a - b) for i, a in enumerate(small) for b in small[i + 1:]]
    allowed = sorted(set(allowed))
    missing = []
    for options in readings(answer):
        v = options[0]
        if v == int(v) and (abs(v) <= 13 or 1900 <= v <= 2100):
            continue  # counts, list numbers ("5 warnings", "13 structures") and years
        if not any(number_close(o, a) for o in options for a in allowed):
            missing.append(v)
    return not missing, missing
