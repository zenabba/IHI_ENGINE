import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ihi.subindex.engine import IHIEngine


def test_perfect_health_scores_100():
    engine = IHIEngine()
    # values comfortably in the healthy zone for every parameter
    reading = {
        "H2": 10, "CH4": 10, "C2H6": 10, "C2H4": 10, "C2H2": 0, "CO": 50,
        "CO2": 500, "TDCG": 100,
        "top_oil": 40, "winding": 50, "hot_spot": 60, "load": 40,
        "water": 5, "acidity": 0.02, "dielectric_strength": 60,
        "interfacial_tension": 45, "tan_delta_oil": 0.1,
        "polarization_index": 4.0, "pf_tan_delta": 0.2, "insulation_resistance": 500,
        "age_years": 2,
    }
    result = engine.compute(reading)
    assert result.ihi_percent == 100.0


def test_critical_health_scores_0():
    engine = IHIEngine()
    reading = {
        "H2": 5000, "CH4": 5000, "C2H6": 5000, "C2H4": 5000, "C2H2": 500,
        "CO": 5000, "CO2": 50000, "TDCG": 50000,
        "top_oil": 200, "winding": 200, "hot_spot": 200, "load": 200,
        "water": 100, "acidity": 1.0, "dielectric_strength": 5,
        "interfacial_tension": 5, "tan_delta_oil": 5,
        "polarization_index": 0.2, "pf_tan_delta": 5, "insulation_resistance": 1,
        "age_years": 60,
    }
    result = engine.compute(reading)
    assert result.ihi_percent == 0.0


def test_weight_renormalization_when_family_missing():
    engine = IHIEngine()
    # only DGA provided; all other families dropped, so DGA weight -> 1.0
    reading = {"H2": 90, "CH4": 300, "C2H6": 70, "C2H4": 120,
               "C2H2": 2, "CO": 400, "CO2": 3200, "TDCG": 1100}
    result = engine.compute(reading)
    dga = result.families["dga"]
    assert abs(dga.weight_effective - 1.0) < 1e-9
    # IHI should equal the DGA family index alone (engine rounds IHI to 4 dp)
    assert abs(result.ihi - dga.index) < 1e-3
    assert any("renormalized" in n for n in result.notes)
