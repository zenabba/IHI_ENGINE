"""Validated input schema for one transformer snapshot.

A snapshot is one timestamp plus whatever measurements were available at that
moment. The set of allowed parameters is NOT written here: the model is built
from config/thresholds.yaml, so adding a parameter to the config is enough to
make it accepted (and range-checked) at the input boundary.

Validation rules:
  * every parameter is optional (None = not measured, which is normal);
  * values must be finite numbers;
  * values must be >= 0 unless the parameter sets `allow_negative: true`
    in thresholds.yaml (e.g. temperatures in degC);
  * `timestamp` is required;
  * unknown fields are rejected by the model itself. `reading_from_dict()` is
    the lenient entry point: it drops unknown keys with a warning instead.
"""
from __future__ import annotations

import math
import warnings
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, create_model

from ..config import load_thresholds, resolve_config_dir


class UnknownParameterWarning(UserWarning):
    """Raised (as a warning) when an input contains keys the config doesn't know."""


class ReadingBase(BaseModel):
    """Common base for the config-generated reading models."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: datetime

    @classmethod
    def parameter_names(cls) -> list[str]:
        """All measurement fields, i.e. every field except the timestamp."""
        return [name for name in cls.model_fields if name != "timestamp"]

    def measured(self) -> dict[str, float]:
        """Return only the parameters that were actually measured.

        This is the flat {parameter: value} shape IHIEngine.compute() expects.
        """
        return {
            name: value
            for name in self.parameter_names()
            if (value := getattr(self, name)) is not None
        }


def _parameter_specs(config_dir: str | Path | None) -> dict[str, dict]:
    """Flatten thresholds.yaml into {parameter: spec}, checking names are unique.

    Readings are flat dicts, so the same parameter name in two families would
    be ambiguous. Fail loudly on that instead of silently keeping one.
    """
    specs: dict[str, dict] = {}
    for family, family_spec in load_thresholds(config_dir).items():
        for param, spec in (family_spec.get("parameters") or {}).items():
            if param in specs or param == "timestamp":
                raise ValueError(
                    f"parameter {param!r} in family {family!r} clashes with an "
                    f"existing field; parameter names must be unique"
                )
            specs[param] = spec
    return specs


@lru_cache(maxsize=None)
def _build_model(config_dir: str) -> type[ReadingBase]:
    fields: dict[str, Any] = {}
    for param, spec in _parameter_specs(config_dir).items():
        lower_bound = None if spec.get("allow_negative", False) else 0.0
        fields[param] = (
            Optional[float],
            Field(
                default=None,
                ge=lower_bound,
                allow_inf_nan=False,
                description=spec.get("unit"),
            ),
        )
    return create_model("TransformerReading", __base__=ReadingBase, **fields)


def get_reading_model(config_dir: str | Path | None = None) -> type[ReadingBase]:
    """Return the reading model for a config directory (built once, then cached)."""
    # Cache on the resolved absolute path so "config" and "./config" share an entry.
    return _build_model(str(resolve_config_dir(config_dir).resolve()))


def _is_nan(value: Any) -> bool:
    return isinstance(value, float) and math.isnan(value)


def reading_from_dict(
    data: Mapping[str, Any], *, config_dir: str | Path | None = None
) -> ReadingBase:
    """Build a validated reading from a plain dict (e.g. one CSV row).

    Differences from constructing the model directly:
      * unknown keys are dropped with an UnknownParameterWarning, so one stray
        column doesn't reject a whole reading;
      * NaN is read as "not measured" (None), because that is how pandas spells
        a missing value. This does not invent a value, it only removes one.

    Raises pydantic.ValidationError for bad values (negative, non-numeric,
    infinite) or a missing timestamp.
    """
    model = get_reading_model(config_dir)
    allowed = set(model.parameter_names()) | {"timestamp"}

    unknown = sorted(key for key in data if key not in allowed)
    if unknown:
        warnings.warn(
            f"ignoring unknown parameter(s): {', '.join(unknown)}",
            UnknownParameterWarning,
            stacklevel=2,
        )

    cleaned = {
        key: None if _is_nan(value) else value
        for key, value in data.items()
        if key in allowed
    }
    return model(**cleaned)


# The model for the default repo config, under the name used across the project.
TransformerReading = get_reading_model()
