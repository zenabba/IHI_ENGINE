"""Map an IHI percentage to a health class and a recommended action.

The bands themselves live in config/classification.yaml (sourced from the
classification and intervention-level tables of ARCHITECTURE_IHI.docx).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..config import load_yaml, resolve_config_dir


@dataclass(frozen=True)
class HealthBand:
    level: int        # 0 = best band, increasing towards the worst
    lower: float      # inclusive lower bound, in IHI %
    upper: float      # upper bound, in IHI % (the previous band's lower, or 100)
    label: str        # health state
    action: str       # recommended maintenance action

    @property
    def band(self) -> str:
        return f"{self.lower:g}–{self.upper:g}%"


@dataclass
class Classification:
    label: str        # health state
    action: str       # recommended maintenance action
    band: str         # numeric band, for display
    level: int = 0    # 0 = best; lets a UI order or colour classes without string matching


@lru_cache(maxsize=None)
def _load_bands(config_dir: str) -> tuple[HealthBand, ...]:
    raw = load_yaml("classification.yaml", config_dir)["bands"]
    lowers = [float(b["lower"]) for b in raw]
    if lowers != sorted(lowers, reverse=True) or lowers[-1] != 0:
        raise ValueError("classification bands must be ordered best -> worst and end at lower: 0")

    bands = []
    upper = 100.0
    for level, b in enumerate(raw):
        bands.append(HealthBand(level, float(b["lower"]), upper, b["label"], b["action"]))
        upper = float(b["lower"])
    return tuple(bands)


def health_bands(config_dir: str | Path | None = None) -> tuple[HealthBand, ...]:
    """All health bands from config, best first."""
    return _load_bands(str(resolve_config_dir(config_dir).resolve()))


def classify(ihi_percent: float, config_dir: str | Path | None = None) -> Classification:
    bands = health_bands(config_dir)
    for b in bands:
        if ihi_percent >= b.lower:
            return Classification(label=b.label, action=b.action, band=b.band, level=b.level)
    # ihi_percent < 0 should never happen, but stay safe: worst band
    worst = bands[-1]
    return Classification(label=worst.label, action=worst.action, band=worst.band, level=worst.level)
