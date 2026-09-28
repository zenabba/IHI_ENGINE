"""Per-parameter normalization into a health sub-index in [0, 1].

Implements the two piecewise-linear functions from ARCHITECTURE_IHI.docx:

  low_good  (a low value is healthy, e.g. dissolved gases, acidity, water):
      I = 1                                   if X <= X_normal
      I = (X_critical - X)/(X_critical - X_normal)  if in between
      I = 0                                   if X >= X_critical

  high_good (a high value is healthy, e.g. dielectric strength, PI):
      I = 1                                   if X >= X_normal
      I = (X - X_critical)/(X_normal - X_critical)   if in between
      I = 0                                   if X <= X_critical

1.0 = perfectly healthy, 0.0 = fully degraded.
"""
from __future__ import annotations

LOW_GOOD = "low_good"
HIGH_GOOD = "high_good"


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def sub_index(value, normal: float, critical: float, polarity: str):
    """Return a health sub-index in [0, 1], or None if the value is missing."""
    if value is None:
        return None

    if polarity == LOW_GOOD:
        if normal >= critical:
            raise ValueError("low_good expects normal < critical")
        if value <= normal:
            return 1.0
        if value >= critical:
            return 0.0
        return _clip01((critical - value) / (critical - normal))

    if polarity == HIGH_GOOD:
        if normal <= critical:
            raise ValueError("high_good expects normal > critical")
        if value >= normal:
            return 1.0
        if value <= critical:
            return 0.0
        return _clip01((value - critical) / (normal - critical))

    raise ValueError(f"unknown polarity: {polarity!r}")
