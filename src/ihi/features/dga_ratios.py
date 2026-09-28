"""DGA diagnostic features: gas ratios, Duval triangle coordinates, rates of change.

Absolute gas thresholds (what the Tier-1 sub-indices use) say *how much* gas
there is. The ratios and triangle coordinates say *what kind* of fault is
producing it (partial discharge, arcing, thermal fault at a given temperature,
paper involvement), and the rates say *how fast* it is getting worse. Both are
signals the absolute thresholds miss, so they're exposed here as extra features
for the ML tier. They do NOT change the IHI formula.

Note: IEC 60599 only considers ratios meaningful once the gases are above
typical/detection levels. That gating is an interpretation rule with its own
limits, so it belongs in config alongside the fault-zone boundaries once those
are added, not here. These functions only compute the raw numbers.

All functions accept a plain {gas: ppm} mapping (e.g. `reading.measured()`).
A gas that is absent, None or NaN counts as not measured. Any feature that
needs it comes back as None instead of raising.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from ..config import load_thresholds, resolve_config_dir
from .schema import ReadingBase

SECONDS_PER_DAY = 86_400.0


# ---------------------------------------------------------------------------
# Ratio definitions
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GasRatio:
    name: str          # feature key suffix -> "ratio_<name>"
    numerator: str
    denominator: str
    source: str        # where the ratio comes from, for traceability


GAS_RATIOS: tuple[GasRatio, ...] = (
    # The three basic ratios of IEC 60599 (also R2, R1, R5 in Rogers' method).
    GasRatio("C2H2_C2H4", "C2H2", "C2H4", "IEC 60599 basic ratio; Rogers R2"),
    GasRatio("CH4_H2",    "CH4",  "H2",   "IEC 60599 basic ratio; Rogers R1"),
    GasRatio("C2H4_C2H6", "C2H4", "C2H6", "IEC 60599 basic ratio; Rogers R5"),
    # Fourth ratio of the original Rogers method (low-temperature thermal faults).
    GasRatio("C2H6_CH4",  "C2H6", "CH4",  "Rogers (original 4-ratio method)"),
    # Carbon oxides: a low CO2/CO points to cellulose (paper) degradation.
    GasRatio("CO2_CO",    "CO2",  "CO",   "IEC 60599 carbon-oxide ratio"),
)

# Duval triangle 1: the three gases whose relative shares locate the fault zone.
DUVAL_GASES: tuple[str, ...] = ("CH4", "C2H4", "C2H2")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _gas(reading: Mapping[str, Any], gas: str) -> Optional[float]:
    """Return a gas concentration, or None if it wasn't measured."""
    value = reading.get(gas)
    if value is None:
        return None
    value = float(value)
    return None if math.isnan(value) else value


def safe_ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    """numerator / denominator, or None if either side is missing or the denominator is 0."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


# ---------------------------------------------------------------------------
# Ratios and triangle coordinates (single reading)
# ---------------------------------------------------------------------------
def dga_ratios(reading: Mapping[str, Any]) -> dict[str, Optional[float]]:
    """Compute every ratio in GAS_RATIOS as {"ratio_<name>": value or None}."""
    return {
        f"ratio_{r.name}": safe_ratio(_gas(reading, r.numerator), _gas(reading, r.denominator))
        for r in GAS_RATIOS
    }


def duval_triangle(reading: Mapping[str, Any]) -> dict[str, Optional[float]]:
    """Duval triangle 1 coordinates: each gas as a % of CH4 + C2H4 + C2H2.

    All three gases are needed. If one is missing or the total is 0, every
    coordinate is None, because a partial triangle point would be wrong
    rather than just incomplete.
    """
    keys = [f"duval_pct_{gas}" for gas in DUVAL_GASES]
    values = [_gas(reading, gas) for gas in DUVAL_GASES]
    if any(v is None for v in values):
        return dict.fromkeys(keys)

    total = sum(values)
    if total == 0:
        return dict.fromkeys(keys)
    return {key: 100.0 * v / total for key, v in zip(keys, values)}


def dga_features(reading: Mapping[str, Any]) -> dict[str, Optional[float]]:
    """All single-reading DGA features (ratios + Duval coordinates) in one flat dict."""
    return {**dga_ratios(reading), **duval_triangle(reading)}


# ---------------------------------------------------------------------------
# Rates of change (pair of readings)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=None)
def _dga_gas_names(config_dir: str) -> tuple[str, ...]:
    params = load_thresholds(config_dir).get("dga", {}).get("parameters") or {}
    return tuple(params)


def dga_gas_names(config_dir: str | Path | None = None) -> tuple[str, ...]:
    """The DGA parameters defined in thresholds.yaml (includes TDCG)."""
    return _dga_gas_names(str(resolve_config_dir(config_dir).resolve()))


def gas_rates(
    current: Mapping[str, Any],
    current_time: datetime,
    previous: Mapping[str, Any],
    previous_time: datetime,
    *,
    gases: Iterable[str] | None = None,
    config_dir: str | Path | None = None,
) -> dict[str, Optional[float]]:
    """Rate of change of each gas between two readings, in ppm per day.

    Returns {"rate_<gas>_ppm_per_day": value}. A value is None when the gas is
    missing from either reading. A negative rate means the concentration
    dropped (e.g. after oil degassing), which is kept as-is.

    `gases` defaults to the DGA family in thresholds.yaml.

    Raises ValueError if `current_time` is not strictly after `previous_time`.
    Out-of-order or duplicate timestamps are a data problem the caller must fix,
    not something to paper over with a zero or infinite rate.
    """
    elapsed_days = (current_time - previous_time).total_seconds() / SECONDS_PER_DAY
    if elapsed_days <= 0:
        raise ValueError(
            f"current reading ({current_time}) must be after the previous one ({previous_time})"
        )

    if gases is None:
        gases = dga_gas_names(config_dir)

    rates: dict[str, Optional[float]] = {}
    for gas in gases:
        now, before = _gas(current, gas), _gas(previous, gas)
        rates[f"rate_{gas}_ppm_per_day"] = (
            None if now is None or before is None else (now - before) / elapsed_days
        )
    return rates


def gas_rates_between(
    previous: ReadingBase,
    current: ReadingBase,
    *,
    config_dir: str | Path | None = None,
) -> dict[str, Optional[float]]:
    """gas_rates() for two validated readings, using their own timestamps."""
    return gas_rates(
        current.measured(), current.timestamp,
        previous.measured(), previous.timestamp,
        config_dir=config_dir,
    )
