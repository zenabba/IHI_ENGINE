import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ihi.features.missing import impute, measurement_mask
from ihi.features.schema import TransformerReading
from ihi.subindex.engine import IHIEngine

TS = datetime(2026, 1, 15)

DGA = {"H2": 90, "CH4": 300, "C2H6": 70, "C2H4": 120,
       "C2H2": 2, "CO": 400, "CO2": 3200, "TDCG": 1100}
OIL = {"water": 18, "acidity": 0.12, "dielectric_strength": 30,
       "interfacial_tension": 28, "tan_delta_oil": 0.6}


# -- mask ----------------------------------------------------------------------
def test_mask_covers_every_configured_parameter():
    mask = measurement_mask({"H2": 90})
    assert set(mask) == set(TransformerReading.parameter_names())
    assert mask["H2"] == 1
    assert sum(mask.values()) == 1


def test_mask_treats_none_and_nan_as_missing():
    mask = measurement_mask({"H2": 90, "CH4": None, "C2H6": float("nan"), "C2H4": 0})
    assert (mask["H2"], mask["CH4"], mask["C2H6"]) == (1, 0, 0)
    assert mask["C2H4"] == 1          # zero is a real measurement


def test_mask_accepts_validated_reading_and_custom_parameter_list():
    reading = TransformerReading(timestamp=TS, H2=90)
    assert measurement_mask(reading, parameters=["H2", "CH4"]) == {"H2": 1, "CH4": 0}


def test_mask_ignores_unknown_keys():
    assert "serial_no" not in measurement_mask({"serial_no": "T-01"})


# -- imputation: default is "do nothing" ----------------------------------------
def test_default_fills_nothing():
    result = impute({"H2": 90})
    assert result.imputed == {}
    assert result.values["H2"] == 90.0
    assert result.values["CH4"] is None
    assert result.measured_values() == {"H2": 90.0}


def test_default_leaves_engine_result_unchanged():
    engine = IHIEngine()
    reading = {**DGA, "water": 18}
    assert engine.compute(impute(reading).measured_values()).ihi == engine.compute(reading).ihi


# -- imputation: opt-in baseline -----------------------------------------------
def test_baseline_fills_only_gaps_and_is_recorded():
    result = impute({"H2": 90, "CH4": None}, {"H2": 999, "CH4": 250, "water": 20},
                    source="previous reading 2025-12-15", parameters=["H2", "CH4", "water", "acidity"])
    assert result.values == {"H2": 90.0, "CH4": 250.0, "water": 20.0, "acidity": None}
    assert result.imputed == {"CH4": "previous reading 2025-12-15",
                              "water": "previous reading 2025-12-15"}


def test_measured_mask_still_reports_original_input():
    result = impute({"H2": 90}, {"CH4": 250}, parameters=["H2", "CH4"])
    assert result.measured == {"H2": 1, "CH4": 0}         # CH4 was imputed, not measured
    assert result.imputed_mask() == {"H2": 0, "CH4": 1}


def test_baseline_none_and_nan_are_not_used():
    result = impute({}, {"H2": None, "CH4": float("nan")}, parameters=["H2", "CH4"])
    assert result.values == {"H2": None, "CH4": None}
    assert result.imputed == {}


def test_nan_in_reading_can_be_filled():
    result = impute({"H2": float("nan")}, {"H2": 80}, parameters=["H2"])
    assert result.values["H2"] == 80.0 and result.measured["H2"] == 0


def test_inputs_are_not_modified():
    reading, baseline = {"H2": 90}, {"CH4": 250}
    impute(reading, baseline)
    assert reading == {"H2": 90} and baseline == {"CH4": 250}


def test_validated_readings_work_as_reading_and_baseline():
    now = TransformerReading(timestamp=TS, H2=90)
    before = TransformerReading(timestamp=TS.replace(month=1, day=1), H2=80, CH4=250)
    result = impute(now, before, parameters=["H2", "CH4"])
    assert result.values == {"H2": 90.0, "CH4": 250.0}


def test_imputation_brings_a_dropped_family_back_into_the_ihi():
    engine = IHIEngine()
    dga_only = engine.compute(DGA)
    assert dga_only.families["oil"].index is None       # oil dropped, weight renormalized

    result = impute(DGA, OIL, source="last oil test")
    filled = engine.compute(result.measured_values())
    assert filled.families["oil"].index is not None
    assert set(result.imputed) == set(OIL)               # audit trail names every filled value
    assert all(result.measured[p] == 0 for p in OIL)
