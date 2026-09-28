"""Map an IHI percentage to a health class and a recommended action.

Bands from the classification table in ARCHITECTURE_IHI.docx (image13),
actions from the intervention-level table (section H).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Classification:
    label: str        # health state
    action: str       # recommended maintenance action
    band: str         # numeric band, for display


# ordered high -> low; first band whose lower bound is met wins
_BANDS = [
    (80, "Excellent",     "Surveillance normale"),
    (60, "Bon",           "Surveillance normale"),
    (40, "Dégradé",       "Surveillance renforcée"),
    (20, "Critique",      "Maintenance préventive"),
    (0,  "Très critique", "Intervention prioritaire"),
]


def classify(ihi_percent: float) -> Classification:
    for lower, label, action in _BANDS:
        if ihi_percent >= lower:
            upper = 100 if lower == 80 else lower + 20
            return Classification(label=label, action=action, band=f"{lower}\u2013{upper}%")
    # ihi_percent < 0 should never happen, but stay safe
    return Classification(label="Très critique", action="Intervention prioritaire", band="0\u201320%")
