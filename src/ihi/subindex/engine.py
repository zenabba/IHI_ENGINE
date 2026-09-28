"""Tier-1 deterministic IHI engine.

Pipeline:  raw reading -> per-parameter sub-indices -> family indices
           -> weighted aggregation (weights renormalized over available
           families) -> IHI in [0, 1].

No training data required. Fully driven by config/ and fully auditable:
every number in the result carries its provenance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import load_family_weights, load_thresholds
from .normalize import sub_index


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------
@dataclass
class FamilyResult:
    name: str
    label: str
    index: float | None                       # family health index in [0, 1], or None if no data
    weight_effective: float                    # weight after renormalization
    sub_indices: dict = field(default_factory=dict)   # param -> sub-index
    missing: list = field(default_factory=list)        # params with no measurement


@dataclass
class IHIResult:
    ihi: float                                 # 0..1
    ihi_percent: float                         # 0..100
    families: dict = field(default_factory=dict)  # name -> FamilyResult
    notes: list = field(default_factory=list)

    def top_drivers(self, n: int = 3):
        """Return the n parameters dragging the score down the most."""
        scored = []
        for fam in self.families.values():
            for param, si in fam.sub_indices.items():
                if si is not None:
                    scored.append((f"{fam.name}.{param}", si))
        scored.sort(key=lambda kv: kv[1])   # lowest (worst) first
        return scored[:n]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
class IHIEngine:
    def __init__(self, config_dir: str | Path | None = None):
        # config_dir=None -> repo_root/config (see ihi.config)
        self.thresholds = load_thresholds(config_dir)
        self.weights = load_family_weights(config_dir)

    # -- family-level -------------------------------------------------------
    def _family_index(self, name: str, reading: dict) -> FamilyResult:
        spec = self.thresholds.get(name, {})
        params = spec.get("parameters", {}) or {}
        sub_indices, missing = {}, []

        for param, p in params.items():
            value = reading.get(param)
            si = sub_index(value, p["normal"], p["critical"], p["polarity"])
            sub_indices[param] = si
            if si is None:
                missing.append(param)

        measured = [si for si in sub_indices.values() if si is not None]
        # Equal weighting within a family (per-parameter weights can be added later).
        index = sum(measured) / len(measured) if measured else None

        return FamilyResult(
            name=name,
            label=spec.get("label", name),
            index=index,
            weight_effective=0.0,   # set during aggregation
            sub_indices=sub_indices,
            missing=missing,
        )

    # -- top-level ----------------------------------------------------------
    def compute(self, reading: dict) -> IHIResult:
        """`reading` is a flat dict of {parameter_name: value}. Missing keys are
        treated as not-measured and excluded (with weight redistribution)."""
        families = {name: self._family_index(name, reading) for name in self.weights}

        available = {n: f for n, f in families.items() if f.index is not None}
        total_w = sum(self.weights[n] for n in available)
        notes = []
        if not available:
            raise ValueError("no measured parameters in reading — cannot compute IHI")

        dropped = [n for n in families if n not in available]
        if dropped:
            notes.append(
                f"No data for: {', '.join(dropped)}. Weights renormalized over "
                f"{len(available)} remaining families."
            )

        ihi = 0.0
        for name, fam in available.items():
            fam.weight_effective = self.weights[name] / total_w
            ihi += fam.weight_effective * fam.index

        return IHIResult(
            ihi=round(ihi, 4),
            ihi_percent=round(ihi * 100, 1),
            families=families,
            notes=notes,
        )
