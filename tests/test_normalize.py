import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ihi.subindex.normalize import sub_index


def test_low_good_bounds():
    # normal=100, critical=500 (matches the worked DGA example in the doc)
    assert sub_index(80, 100, 500, "low_good") == 1.0     # healthy
    assert sub_index(500, 100, 500, "low_good") == 0.0    # critical
    assert sub_index(600, 100, 500, "low_good") == 0.0    # beyond critical -> clipped


def test_low_good_midpoint():
    # doc example: X=300 -> (500-300)/(500-100) = 0.5
    assert sub_index(300, 100, 500, "low_good") == 0.5


def test_high_good_bounds():
    # dielectric strength: normal=28, critical=23 (high is good)
    assert sub_index(30, 28, 23, "high_good") == 1.0
    assert sub_index(23, 28, 23, "high_good") == 0.0
    assert sub_index(20, 28, 23, "high_good") == 0.0


def test_high_good_midpoint():
    # X=25.5 -> (25.5-23)/(28-23) = 0.5
    assert sub_index(25.5, 28, 23, "high_good") == 0.5


def test_missing_returns_none():
    assert sub_index(None, 100, 500, "low_good") is None
