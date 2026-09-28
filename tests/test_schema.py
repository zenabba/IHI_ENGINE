import math
import sys
import warnings
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ihi.features.schema import (
    TransformerReading,
    UnknownParameterWarning,
    get_reading_model,
    reading_from_dict,
)
from ihi.subindex.engine import IHIEngine

TS = datetime(2026, 1, 15, 8, 30)

# Same snapshot as run_example.py, so the end result is a known number (83.4 %).
SAMPLE = {
    "H2": 90, "CH4": 300, "C2H6": 70, "C2H4": 120,
    "C2H2": 2, "CO": 400, "CO2": 3200, "TDCG": 1100,
    "top_oil": 82, "winding": 98, "hot_spot": 118, "load": 75,
    "water": 18, "acidity": 0.12, "dielectric_strength": 30,
    "interfacial_tension": 28, "tan_delta_oil": 0.6,
    "polarization_index": 1.8, "pf_tan_delta": 0.7, "insulation_resistance": 120,
    "age_years": 22,
}


def test_valid_reading_round_trips_into_engine():
    reading = TransformerReading(timestamp=TS, **SAMPLE)
    assert reading.measured() == {k: float(v) for k, v in SAMPLE.items()}
    # Validation must not change the result the engine gives on the raw dict.
    assert IHIEngine().compute(reading.measured()).ihi_percent == 83.4


def test_fields_come_from_config():
    names = set(TransformerReading.parameter_names())
    assert set(SAMPLE) <= names
    assert "timestamp" not in names


def test_missing_parameters_are_none_and_excluded():
    reading = TransformerReading(timestamp=TS, H2=90, water=18)
    assert reading.CH4 is None
    assert reading.measured() == {"H2": 90.0, "water": 18.0}


def test_timestamp_is_required():
    with pytest.raises(ValidationError, match="timestamp"):
        TransformerReading(H2=90)


def test_negative_value_is_rejected():
    with pytest.raises(ValidationError, match="H2"):
        TransformerReading(timestamp=TS, H2=-5)


def test_negative_temperature_is_allowed():
    # top_oil has allow_negative: true in thresholds.yaml (cold-climate start-up)
    assert TransformerReading(timestamp=TS, top_oil=-12.0).top_oil == -12.0


def test_non_finite_and_non_numeric_values_are_rejected():
    with pytest.raises(ValidationError):
        TransformerReading(timestamp=TS, H2=math.inf)
    with pytest.raises(ValidationError):
        TransformerReading(timestamp=TS, H2="lots")


def test_model_itself_rejects_unknown_fields():
    # direct construction is strict, so a typo can't silently disappear
    with pytest.raises(ValidationError):
        TransformerReading(timestamp=TS, H22=90)


def test_from_dict_drops_unknown_keys_with_warning():
    with pytest.warns(UnknownParameterWarning, match="serial_no"):
        reading = reading_from_dict({"timestamp": TS, "H2": 90, "serial_no": "T-01"})
    assert reading.measured() == {"H2": 90.0}


def test_from_dict_without_unknown_keys_is_silent():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        reading_from_dict({"timestamp": TS, "H2": 90})


def test_from_dict_reads_nan_as_missing():
    reading = reading_from_dict({"timestamp": TS, "H2": float("nan"), "CH4": 300})
    assert reading.H2 is None
    assert reading.measured() == {"CH4": 300.0}


def test_from_dict_parses_strings_like_csv_cells():
    reading = reading_from_dict({"timestamp": "2026-01-15T08:30:00", "H2": "90.5"})
    assert reading.timestamp == TS
    assert reading.H2 == 90.5


def test_duplicate_parameter_names_across_families_fail(tmp_path):
    (tmp_path / "thresholds.yaml").write_text(
        "families:\n"
        "  a: {parameters: {x: {normal: 1, critical: 2, polarity: low_good}}}\n"
        "  b: {parameters: {x: {normal: 1, critical: 2, polarity: low_good}}}\n"
    )
    with pytest.raises(ValueError, match="unique"):
        get_reading_model(tmp_path)
