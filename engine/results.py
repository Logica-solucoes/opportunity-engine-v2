"""Builds, sanitizes and writes results.json from what `compute()` produced. No statistics happen here."""

import math
from typing import Any


def sanitize(obj: Any) -> Any:
    """A copy of `obj` where every NaN/inf float, at any depth, is None (JSON has no such numbers)."""
    if isinstance(obj, dict):
        return {key: sanitize(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(value) for value in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj
