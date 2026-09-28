import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ihi.decision.classify import classify, health_bands


@pytest.mark.parametrize(
    "ihi, label, level",
    [
        (100, "Excellent", 0),
        (80, "Excellent", 0),          # lower bound is inclusive
        (79.9, "Bon", 1),
        (40, "Dégradé", 2),
        (20, "Critique", 3),
        (19.9, "Très critique", 4),
        (0, "Très critique", 4),
    ],
)
def test_band_boundaries(ihi, label, level):
    c = classify(ihi)
    assert (c.label, c.level) == (label, level)


def test_bands_come_from_config_with_derived_upper_bounds():
    bands = health_bands()
    assert [b.label for b in bands] == ["Excellent", "Bon", "Dégradé", "Critique", "Très critique"]
    assert bands[0].upper == 100 and bands[1].upper == 80
    assert bands[2].band == "40–60%"
    assert classify(50).action == "Surveillance renforcée"


def test_misordered_bands_are_rejected(tmp_path):
    (tmp_path / "classification.yaml").write_text(
        "bands:\n"
        "  - {lower: 20, label: A, action: a}\n"
        "  - {lower: 50, label: B, action: b}\n"
        "  - {lower: 0,  label: C, action: c}\n"
    )
    with pytest.raises(ValueError, match="ordered"):
        health_bands(tmp_path)
