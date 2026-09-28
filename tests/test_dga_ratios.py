import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ihi.features.dga_ratios import (
    dga_features,
    dga_gas_names,
    dga_ratios,
    duval_triangle,
    gas_rates,
    gas_rates_between,
    safe_ratio,
)
from ihi.features.schema import TransformerReading

# DGA part of the run_example.py snapshot (ppm)
GASES = {"H2": 90, "CH4": 300, "C2H6": 70, "C2H4": 120,
         "C2H2": 2, "CO": 400, "CO2": 3200, "TDCG": 1100}

T0 = datetime(2026, 1, 1)


# -- safe_ratio --------------------------------------------------------------
def test_safe_ratio_guards():
    assert safe_ratio(6, 3) == 2.0
    assert safe_ratio(0, 3) == 0.0          # zero numerator is a real value
    assert safe_ratio(6, 0) is None         # divide by zero
    assert safe_ratio(None, 3) is None
    assert safe_ratio(6, None) is None


# -- ratios --------------------------------------------------------------------
def test_ratios_match_hand_computed_values():
    r = dga_ratios(GASES)
    assert r["ratio_C2H2_C2H4"] == pytest.approx(2 / 120)      # 0.0167
    assert r["ratio_CH4_H2"] == pytest.approx(300 / 90)        # 3.333
    assert r["ratio_C2H4_C2H6"] == pytest.approx(120 / 70)     # 1.714
    assert r["ratio_C2H6_CH4"] == pytest.approx(70 / 300)      # 0.233
    assert r["ratio_CO2_CO"] == pytest.approx(3200 / 400)      # 8.0


def test_zero_denominator_gives_none_but_other_ratios_survive():
    r = dga_ratios({**GASES, "C2H4": 0})
    assert r["ratio_C2H2_C2H4"] is None        # C2H4 is the denominator
    assert r["ratio_C2H4_C2H6"] == 0.0         # C2H4 is the numerator
    assert r["ratio_CH4_H2"] == pytest.approx(300 / 90)


def test_missing_gas_gives_none():
    gases = {k: v for k, v in GASES.items() if k != "H2"}
    r = dga_ratios(gases)
    assert r["ratio_CH4_H2"] is None
    assert r["ratio_CO2_CO"] == pytest.approx(8.0)


def test_nan_and_none_count_as_missing():
    assert dga_ratios({**GASES, "H2": None})["ratio_CH4_H2"] is None
    assert dga_ratios({**GASES, "H2": float("nan")})["ratio_CH4_H2"] is None


# -- Duval ---------------------------------------------------------------------
def test_duval_percentages():
    d = duval_triangle(GASES)
    total = 300 + 120 + 2
    assert d["duval_pct_CH4"] == pytest.approx(100 * 300 / total)    # 71.09 %
    assert d["duval_pct_C2H4"] == pytest.approx(100 * 120 / total)   # 28.44 %
    assert d["duval_pct_C2H2"] == pytest.approx(100 * 2 / total)     #  0.47 %
    assert sum(d.values()) == pytest.approx(100.0)


def test_duval_needs_all_three_gases():
    gases = {k: v for k, v in GASES.items() if k != "C2H2"}
    assert all(v is None for v in duval_triangle(gases).values())


def test_duval_all_zero_is_none():
    assert all(v is None for v in duval_triangle({"CH4": 0, "C2H4": 0, "C2H2": 0}).values())


def test_dga_features_merges_everything():
    f = dga_features(GASES)
    assert "ratio_CH4_H2" in f and "duval_pct_CH4" in f


# -- rates ---------------------------------------------------------------------
def test_gas_list_comes_from_config():
    assert set(dga_gas_names()) == set(GASES)


def test_rates_ppm_per_day():
    previous = dict(GASES)
    current = {**GASES, "H2": 120, "C2H2": 0}          # H2 +30, C2H2 -2
    r = gas_rates(current, T0 + timedelta(days=30), previous, T0)
    assert r["rate_H2_ppm_per_day"] == pytest.approx(1.0)
    assert r["rate_C2H2_ppm_per_day"] == pytest.approx(-2 / 30)     # drop kept negative
    assert r["rate_CH4_ppm_per_day"] == 0.0


def test_rates_use_fractional_days():
    r = gas_rates({"H2": 101}, T0 + timedelta(hours=12), {"H2": 100}, T0, gases=["H2"])
    assert r["rate_H2_ppm_per_day"] == pytest.approx(2.0)


def test_rate_is_none_when_either_side_missing():
    r = gas_rates({"H2": 120}, T0 + timedelta(days=1), {"CH4": 300}, T0, gases=["H2", "CH4"])
    assert r == {"rate_H2_ppm_per_day": None, "rate_CH4_ppm_per_day": None}


@pytest.mark.parametrize("delta", [timedelta(0), timedelta(days=-1)])
def test_rates_reject_non_increasing_time(delta):
    with pytest.raises(ValueError, match="must be after"):
        gas_rates(GASES, T0 + delta, GASES, T0)


def test_rates_between_validated_readings():
    before = TransformerReading(timestamp=T0, H2=90, CH4=300)
    after = TransformerReading(timestamp=T0 + timedelta(days=10), H2=100, CH4=300)
    r = gas_rates_between(before, after)
    assert r["rate_H2_ppm_per_day"] == pytest.approx(1.0)
    assert r["rate_CH4_ppm_per_day"] == 0.0
    assert r["rate_C2H2_ppm_per_day"] is None        # never measured
