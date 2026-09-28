import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from ihi.dashboard.app import create_app  # noqa: E402
from ihi.dashboard.service import compute_trend  # noqa: E402
from ihi.subindex.engine import IHIEngine  # noqa: E402

SEED = ROOT / "data" / "demo" / "fleet.json"

# Same snapshot as run_example.py -> 83.4 %
SAMPLE = {
    "H2": 90, "CH4": 300, "C2H6": 70, "C2H4": 120,
    "C2H2": 2, "CO": 400, "CO2": 3200, "TDCG": 1100,
    "top_oil": 82, "winding": 98, "hot_spot": 118, "load": 75,
    "water": 18, "acidity": 0.12, "dielectric_strength": 30,
    "interfacial_tension": 28, "tan_delta_oil": 0.6,
    "polarization_index": 1.8, "pf_tan_delta": 0.7, "insulation_resistance": 120,
    "age_years": 22,
}


@pytest.fixture
def client(tmp_path):
    # Each test gets its own copy of the demo fleet, so saves don't leak between tests.
    return TestClient(create_app(tmp_path / "fleet.json", seed_path=SEED))


@pytest.fixture
def empty_client(tmp_path):
    return TestClient(create_app(tmp_path / "fleet.json"))


# -- trend -------------------------------------------------------------------
def test_trend_needs_two_points():
    assert compute_trend([(datetime(2026, 1, 1), 80.0)], 8.0) is None


def test_trend_rate_is_per_year_and_flags_acceleration():
    t0 = datetime(2026, 1, 1)
    fast = compute_trend([(t0, 60.0), (t0 + timedelta(days=91), 55.0)], 8.0)   # ~ -20 pt/yr
    slow = compute_trend([(t0, 60.0), (t0 + timedelta(days=365), 55.0)], 8.0)  # ~ -5 pt/yr
    assert fast["delta_pt"] == -5.0 and fast["accelerated"]
    assert slow["rate_pt_per_year"] == pytest.approx(-5.0, abs=0.1)
    assert not slow["accelerated"]


# -- pages & read endpoints -----------------------------------------------------
def test_index_serves_the_page(client):
    r = client.get("/")
    assert r.status_code == 200 and "IHI" in r.text
    assert client.get("/static/app.js").status_code == 200


def test_config_view_comes_from_yaml(client):
    cfg = client.get("/api/config").json()
    assert [b["label"] for b in cfg["bands"]][0] == "Excellent"
    dga = next(f for f in cfg["families"] if f["name"] == "dga")
    assert dga["weight"] == 0.30
    h2 = dga["parameters"][0]
    assert (h2["name"], h2["normal"], h2["critical"]) == ("H2", 100, 1800)


def test_fleet_summary_is_consistent(client):
    fleet = client.get("/api/fleet").json()
    transformers = fleet["transformers"]
    assert len(transformers) == 8
    assert sum(fleet["distribution"].values()) == 8
    # sorted worst first, like the mockup
    scores = [t["ihi_percent"] for t in transformers]
    assert scores == sorted(scores)
    assert fleet["alert_count"] == sum(1 for t in transformers if t["alerts"])
    assert fleet["alert_count"] == len(client.get("/api/alerts").json())


def test_fleet_scores_match_the_engine(client):
    """The dashboard must not compute its own IHI: it has to agree with IHIEngine."""
    engine = IHIEngine()
    detail = client.get("/api/transformers/TR-01").json()
    fleet_entry = next(t for t in client.get("/api/fleet").json()["transformers"] if t["id"] == "TR-01")
    values = {p["name"]: p["value"] for f in detail["latest"]["families"]
              for p in f["parameters"] if p["value"] is not None}
    assert fleet_entry["ihi_percent"] == engine.compute(values).ihi_percent


def test_detail_has_history_and_rates(client):
    t = client.get("/api/transformers/TR-07").json()
    assert len(t["history"]) == t["evaluations"] == 5
    assert t["trend"]["accelerated"]
    assert t["latest"]["dga"]["rates"]["rate_H2_ppm_per_day"] is not None


def test_unknown_transformer_is_404(client):
    assert client.get("/api/transformers/NOPE").status_code == 404


# -- evaluate (try-out, nothing saved) ---------------------------------------
def test_evaluate_matches_run_example(client):
    r = client.post("/api/evaluate", json={"timestamp": "2026-01-15T08:30:00", "values": SAMPLE})
    body = r.json()
    assert r.status_code == 200
    assert body["ihi_percent"] == 83.4
    assert body["classification"]["label"] == "Excellent"
    assert body["dga"]["ratios"]["ratio_CH4_H2"] == pytest.approx(300 / 90)
    assert body["dga"]["rates"] is None          # no transformer -> no previous reading
    assert any("renormalized" in n for n in body["notes"])


def test_evaluate_does_not_save(client):
    before = client.get("/api/transformers/TR-01").json()["evaluations"]
    client.post("/api/evaluate", json={"values": SAMPLE, "transformer_id": "TR-01"})
    assert client.get("/api/transformers/TR-01").json()["evaluations"] == before


def test_evaluate_against_history_gives_rates(client):
    r = client.post("/api/evaluate", json={
        "timestamp": "2026-09-28T10:00", "values": SAMPLE, "transformer_id": "TR-01",
    })
    assert r.status_code == 200
    assert r.json()["dga"]["rates_since"].startswith("2026-09-14")


def test_evaluate_accepts_numbers_as_text_and_ignores_blanks(client):
    r = client.post("/api/evaluate", json={"values": {"H2": "90.5", "CH4": "", "water": None}})
    assert r.status_code == 200
    params = {p["name"]: p["value"] for f in r.json()["families"] for p in f["parameters"]}
    assert params["H2"] == 90.5 and params["CH4"] is None


def test_evaluate_reports_errors_per_field(client):
    r = client.post("/api/evaluate", json={"values": {"H2": -5, "water": "abc"}})
    assert r.status_code == 422
    fields = {e["field"] for e in r.json()["detail"]["errors"]}
    assert fields == {"H2", "water"}


def test_evaluate_with_nothing_measured_is_422(client):
    r = client.post("/api/evaluate", json={"values": {}})
    assert r.status_code == 422


def test_evaluate_warns_about_unknown_parameters(client):
    r = client.post("/api/evaluate", json={"values": {"H2": 90, "serial_no": "T1"}})
    assert r.status_code == 200
    assert "serial_no" in r.json()["warnings"][0]


# -- saving --------------------------------------------------------------------
def test_save_measurement_updates_history(client):
    r = client.post("/api/transformers/TR-02/measurements",
                    json={"timestamp": "2026-09-28T10:00:00", "values": SAMPLE})
    assert r.status_code == 201
    body = r.json()
    assert body["evaluations"] == 6
    assert body["latest"]["ihi_percent"] == 83.4
    assert body["history"][-1]["timestamp"] == "2026-09-28T10:00:00"


def test_save_requires_timestamp_and_valid_values(client):
    assert client.post("/api/transformers/TR-02/measurements", json={"values": SAMPLE}).status_code == 422
    r = client.post("/api/transformers/TR-02/measurements",
                    json={"timestamp": "2026-09-28T10:00", "values": {"H2": -1}})
    assert r.status_code == 422
    assert client.get("/api/transformers/TR-02").json()["evaluations"] == 5   # nothing stored


def test_duplicate_timestamp_is_409(client):
    body = {"timestamp": "2026-09-28T10:00:00", "values": {"H2": 90}}
    assert client.post("/api/transformers/TR-02/measurements", json=body).status_code == 201
    assert client.post("/api/transformers/TR-02/measurements", json=body).status_code == 409


def test_new_transformer_flow(empty_client):
    c = empty_client
    assert c.get("/api/fleet").json()["transformers"] == []

    r = c.post("/api/transformers", json={"id": "TR-09", "substation": "Poste 5"})
    assert r.status_code == 201 and r.json()["latest"] is None
    assert c.post("/api/transformers", json={"id": "TR-09"}).status_code == 409

    c.post("/api/transformers/TR-09/measurements", json={"timestamp": "2026-09-01T00:00", "values": SAMPLE})
    fleet = c.get("/api/fleet").json()
    assert fleet["transformers"][0]["ihi_percent"] == 83.4
    assert fleet["transformers"][0]["trend"] is None      # one evaluation only
