"""Post-generation check of an LLM narrative (A9): every number it writes and every channel it names must come from
the payload the engine published. Pure functions over text."""

import re
from typing import Any

SCALES = {
    "mil": 1e3,
    "k": 1e3,
    "m": 1e6,
    "mi": 1e6,
    "milhão": 1e6,
    "milhões": 1e6,
    "milhao": 1e6,
    "milhoes": 1e6,
    "bi": 1e9,
    "bilhão": 1e9,
    "bilhões": 1e9,
    "bilhao": 1e9,
    "bilhoes": 1e9,
}
# pt-BR numbers: "R$ 3,4M", "-31,1%", "-0,17x", "1.234", "3,41 milhões". A dot followed by groups of 3 digits is a
# thousands separator; any other dot or comma is the decimal one.
NUMBER = re.compile(
    r"(?<![\w.,])(?P<sign>[-−+]?)\s?(?P<currency>R\$\s?)?(?P<sign2>[-−]?)"
    r"(?P<int>\d{1,3}(?:\.\d{3})+(?!\d)|\d+)(?:[,.](?P<dec>\d+))?"
    r"(?:\s?(?P<unit>%|x\b|(?i:milh(?:ões|ão|oes|ao)|bilh(?:ões|ão|oes|ao)|mil|mi|bi|k|m)\b))?"
)
DATE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b|\b\d{4}-\d{2}-\d{2}\b")
ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
SMALL_COUNT = 12


def _leaves(obj: Any, numbers: list[float], days: set[str]) -> None:
    if isinstance(obj, dict):
        for value in obj.values():
            _leaves(value, numbers, days)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            _leaves(value, numbers, days)
    elif isinstance(obj, bool):
        return
    elif isinstance(obj, (int, float)):
        numbers.append(float(obj))
    elif isinstance(obj, str) and ISO_DAY.match(obj):
        days.add(obj[:10])
        numbers.append(float(obj[:4]))  # the year of a published date may be written on its own


def _matches(written: float, decimals: int, scale: float, percent: bool, numbers: list[float]) -> bool:
    tolerance = 0.5 * 10**-decimals + 1e-9  # the written number is the payload value rounded to the digits shown
    for value in numbers:
        candidates = [value, abs(value)] + ([value * 100, abs(value * 100)] if percent else [])
        if any(abs(c / scale - written) <= tolerance for c in candidates):
            return True
    return False


def check(text: str, payload: Any, published: set[str], universe: set[str]) -> list[dict]:
    """Issues found in `text`: numbers not in `payload` and channels of `universe` outside `published`. Empty = passed."""
    numbers: list[float] = []
    days: set[str] = set()
    _leaves(payload, numbers, days)
    issues: list[dict] = []

    def drop_date(m: re.Match) -> str:
        day = f"{m[3]}-{m[2]}-{m[1]}" if m[1] else m[0]
        if day not in days:
            issues.append({"kind": "number", "value": m[0]})
        return " "

    rest = DATE.sub(drop_date, text)
    for m in NUMBER.finditer(rest):
        decimals = len(m["dec"] or "")
        digits = m["int"].replace(".", "")
        written = float(f"{digits}.{m['dec']}" if m["dec"] else digits)
        unit = (m["unit"] or "").lower()
        # ponytail: small bare integers are counts and ordinals ("3 canais", "2 semanas"); an invented one passes
        if not unit and not m["currency"] and not decimals and written <= SMALL_COUNT:
            continue
        if any(s in "-−" for s in (m["sign"] + m["sign2"])):
            written = -written
        if not _matches(written, decimals, SCALES.get(unit, 1), unit == "%", numbers):
            issues.append({"kind": "number", "value": m[0].strip()})

    for name in sorted(universe - published):
        # ponytail: only channels the run knows; an invented one ("Meta") is not caught
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.IGNORECASE):
            issues.append({"kind": "channel", "value": name})
    return issues
