"""Missing-data handling: "was this measured?" masks and opt-in imputation.

Missing measurements are normal: DGA is sampled monthly, oil tests yearly,
some units never get certain tests. The engine already copes with that by
dropping missing parameters (and renormalizing family weights). This module
adds two things on top, mainly for the ML tier:

  * a binary mask {parameter: 1 if measured else 0}, because *whether* a test
    was run is itself information a model can use;
  * imputation that is strictly opt-in and always recorded. By default
    nothing is filled. When a baseline is supplied (typically the same
    transformer's previous reading), it only fills gaps, never overwrites a
    real measurement, and every filled value is listed with its source.

The mask always describes the *original* input: an imputed value is never
reported as measured.

Parameters are the ones in config/thresholds.yaml (via the reading schema).
Keys outside that list are ignored here; the schema is where they get flagged.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from .schema import ReadingBase, get_reading_model


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _as_values(source: Mapping[str, Any] | ReadingBase | None) -> Mapping[str, Any]:
    """Accept either a plain {parameter: value} dict or a validated reading."""
    if source is None:
        return {}
    if isinstance(source, ReadingBase):
        return source.measured()
    return source


def _present(value: Any) -> bool:
    """True if a value counts as measured (not None, not NaN)."""
    if value is None:
        return False
    return not (isinstance(value, float) and math.isnan(value))


def _parameters(
    parameters: Iterable[str] | None, config_dir: str | Path | None
) -> list[str]:
    if parameters is not None:
        return list(parameters)
    return get_reading_model(config_dir).parameter_names()


# ---------------------------------------------------------------------------
# Mask
# ---------------------------------------------------------------------------
def measurement_mask(
    reading: Mapping[str, Any] | ReadingBase,
    *,
    parameters: Iterable[str] | None = None,
    config_dir: str | Path | None = None,
) -> dict[str, int]:
    """{parameter: 1 if measured else 0} for every configured parameter.

    A parameter that is absent, None or NaN counts as not measured.
    """
    values = _as_values(reading)
    return {p: int(_present(values.get(p))) for p in _parameters(parameters, config_dir)}


# ---------------------------------------------------------------------------
# Imputation
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ImputationResult:
    # Every configured parameter. None = still missing (the engine will drop it).
    values: dict[str, Optional[float]]
    # 1 if the parameter was measured in the ORIGINAL input, whatever was filled after.
    measured: dict[str, int]
    # Only the parameters that were filled: {parameter: source label}. This is the audit record.
    imputed: dict[str, str] = field(default_factory=dict)

    def measured_values(self) -> dict[str, float]:
        """Non-missing values (measured + imputed): the flat dict IHIEngine.compute() takes."""
        return {p: v for p, v in self.values.items() if v is not None}

    def imputed_mask(self) -> dict[str, int]:
        """{parameter: 1 if imputed else 0}, the companion to `measured` for ML features."""
        return {p: int(p in self.imputed) for p in self.values}


def impute(
    reading: Mapping[str, Any] | ReadingBase,
    baseline: Mapping[str, Any] | ReadingBase | None = None,
    *,
    source: str = "baseline",
    parameters: Iterable[str] | None = None,
    config_dir: str | Path | None = None,
) -> ImputationResult:
    """Return the reading with a documented, opt-in fill for missing values.

    Strategy:
      * baseline is None (default): nothing is filled. Missing stays None.
      * baseline given: each parameter missing from `reading` but present in
        `baseline` takes the baseline value, and is recorded in
        `result.imputed` under `source` (e.g. "previous reading 2026-06-15").
        Measured values are never replaced. Baseline None/NaN are not used.

    Neither input is modified.
    """
    values = _as_values(reading)
    fallback = _as_values(baseline)
    params = _parameters(parameters, config_dir)

    filled: dict[str, Optional[float]] = {}
    measured: dict[str, int] = {}
    imputed: dict[str, str] = {}

    for p in params:
        if _present(values.get(p)):
            filled[p] = float(values[p])
            measured[p] = 1
            continue

        measured[p] = 0
        if _present(fallback.get(p)):
            filled[p] = float(fallback[p])
            imputed[p] = source
        else:
            filled[p] = None

    return ImputationResult(values=filled, measured=measured, imputed=imputed)
