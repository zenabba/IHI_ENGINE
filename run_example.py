"""Runnable demo of the Phase-1 deterministic IHI engine.

    python run_example.py

Uses a sample transformer reading. Note there is no `electrical` data in the
sample, so you'll see the engine renormalize the family weights.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from ihi.subindex.engine import IHIEngine
from ihi.decision.classify import classify

# A single transformer snapshot: {parameter: measured value}.
# Any parameter you omit is treated as "not measured".
sample_reading = {
    # DGA (ppm)
    "H2": 90, "CH4": 300, "C2H6": 70, "C2H4": 120,
    "C2H2": 2, "CO": 400, "CO2": 3200, "TDCG": 1100,
    # Thermal
    "top_oil": 82, "winding": 98, "hot_spot": 118, "load": 75,
    # Oil
    "water": 18, "acidity": 0.12, "dielectric_strength": 30,
    "interfacial_tension": 28, "tan_delta_oil": 0.6,
    # Insulation
    "polarization_index": 1.8, "pf_tan_delta": 0.7, "insulation_resistance": 120,
    # Age
    "age_years": 22,
    # (no electrical parameters supplied -> family dropped & weights renormalized)
}


def main():
    engine = IHIEngine()
    result = engine.compute(sample_reading)
    verdict = classify(result.ihi_percent)

    print("=" * 60)
    print(f"  INTELLIGENT HEALTH INDEX = {result.ihi_percent} %   ({result.ihi})")
    print(f"  State : {verdict.label}   (band {verdict.band})")
    print(f"  Action: {verdict.action}")
    print("=" * 60)

    print("\nPer-family breakdown:")
    for fam in result.families.values():
        if fam.index is None:
            print(f"  - {fam.name:<11} : no data")
            continue
        print(f"  - {fam.name:<11} : index={fam.index:.3f}  "
              f"weight={fam.weight_effective:.3f}  "
              f"contribution={fam.index * fam.weight_effective:.3f}")

    print("\nTop 3 drivers pulling the score down:")
    for param, si in result.top_drivers(3):
        print(f"  - {param:<28} sub-index={si:.3f}")

    if result.notes:
        print("\nNotes:")
        for note in result.notes:
            print(f"  * {note}")


if __name__ == "__main__":
    main()
