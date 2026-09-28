"""Turn stored measurements into what the dashboard displays.

Everything numeric here comes from the real engine modules: IHIEngine (Tier 1),
classify(), and the DGA features. This layer only arranges their outputs into
JSON-friendly dicts and adds the fleet-level views (trend, alerts, summary).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional

from ..config import load_family_weights, load_thresholds, load_yaml
from ..decision.classify import classify, health_bands
from ..features.dga_ratios import GAS_RATIOS, duval_triangle, dga_ratios, gas_rates
from ..subindex.engine import IHIEngine, IHIResult
from .store import FleetStore

DAYS_PER_YEAR = 365.25


def _fr_signed(value: float) -> str:
    """-11.2 -> '−11,2' (French decimal comma and a real minus sign, like the UI)."""
    return f"{value:+.1f}".replace("-", "−").replace(".", ",")


# ---------------------------------------------------------------------------
# Trend (ARCHITECTURE_IHI §H: dIHI/dt)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AlertRules:
    accelerated_decline_pt_per_year: float
    alert_classes: tuple[str, ...]


def load_alert_rules(config_dir: str | Path | None = None) -> AlertRules:
    raw = load_yaml("alerts.yaml", config_dir)
    return AlertRules(
        accelerated_decline_pt_per_year=float(raw["trend"]["accelerated_decline_pt_per_year"]),
        alert_classes=tuple(raw.get("alert_classes", [])),
    )


def compute_trend(
    history: list[tuple[datetime, float]], accelerated_decline_pt_per_year: float
) -> Optional[dict[str, Any]]:
    """Change between the last two evaluations of a (time-sorted) IHI history.

    Returns None with fewer than two points. `delta_pt` is the raw change in
    IHI points; `rate_pt_per_year` normalizes it by the time between the two
    evaluations, which is what decides "accelerated". Otherwise a -3 pt drop
    would mean the same thing whether it took a month or three years.
    """
    if len(history) < 2:
        return None
    (t_prev, ihi_prev), (t_last, ihi_last) = history[-2], history[-1]
    days = (t_last - t_prev).total_seconds() / 86_400
    delta = ihi_last - ihi_prev
    rate = delta / days * DAYS_PER_YEAR if days > 0 else None
    return {
        "delta_pt": round(delta, 1),
        "days": round(days, 1),
        "rate_pt_per_year": None if rate is None else round(rate, 1),
        "accelerated": rate is not None and rate <= -accelerated_decline_pt_per_year,
    }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
class FleetService:
    def __init__(self, store: FleetStore, config_dir: str | Path | None = None):
        self.store = store
        self.config_dir = config_dir
        self.engine = IHIEngine(config_dir)
        self.thresholds = load_thresholds(config_dir)
        self.weights = load_family_weights(config_dir)
        self.rules = load_alert_rules(config_dir)

    # -- one reading ----------------------------------------------------------
    def evaluate(
        self,
        values: Mapping[str, float],
        timestamp: Optional[datetime] = None,
        previous: Optional[tuple[datetime, Mapping[str, float]]] = None,
    ) -> dict[str, Any]:
        """Full evaluation of one reading: IHI, class, breakdown, drivers, DGA features.

        `previous` (timestamp, values) enables gas rates of change. Raises
        ValueError if nothing in `values` is measured (from IHIEngine).
        """
        result = self.engine.compute(dict(values))
        verdict = classify(result.ihi_percent, self.config_dir)

        rates = None
        if previous is not None and timestamp is not None and timestamp > previous[0]:
            rates = gas_rates(values, timestamp, previous[1], previous[0], config_dir=self.config_dir)

        return {
            "timestamp": timestamp.isoformat() if timestamp else None,
            "ihi": result.ihi,
            "ihi_percent": result.ihi_percent,
            "classification": {
                "label": verdict.label, "action": verdict.action,
                "band": verdict.band, "level": verdict.level,
            },
            "families": self._families(result, values),
            "drivers": [{"parameter": p, "sub_index": si} for p, si in result.top_drivers(3)],
            "notes": result.notes,
            "dga": {
                "ratios": dga_ratios(values),
                "duval": duval_triangle(values),
                "rates": rates,
                "rates_since": previous[0].isoformat() if rates is not None else None,
            },
        }

    def _families(self, result: IHIResult, values: Mapping[str, float]) -> list[dict[str, Any]]:
        families = []
        for name, fam in result.families.items():
            params = self.thresholds.get(name, {}).get("parameters") or {}
            families.append({
                "name": name,
                "label": fam.label,
                "index": fam.index,
                "weight_nominal": self.weights[name],
                "weight_effective": fam.weight_effective,
                "contribution": None if fam.index is None else fam.index * fam.weight_effective,
                "parameters": [
                    {
                        "name": p, "value": values.get(p), "unit": spec.get("unit"),
                        "normal": spec["normal"], "critical": spec["critical"],
                        "polarity": spec["polarity"], "sub_index": fam.sub_indices.get(p),
                    }
                    for p, spec in params.items()
                ],
                "missing": fam.missing,
            })
        return families

    # -- one transformer ------------------------------------------------------
    def _history(self, transformer: dict[str, Any]) -> list[dict[str, Any]]:
        """Evaluate every stored measurement, oldest first, each with rates vs the one before."""
        evaluations, previous = [], None
        for m in transformer["measurements"]:
            ts = datetime.fromisoformat(m["timestamp"])
            evaluations.append(self.evaluate(m["values"], ts, previous))
            previous = (ts, m["values"])
        return evaluations

    def _summary(self, transformer: dict[str, Any], evaluations: list[dict[str, Any]]) -> dict[str, Any]:
        latest = evaluations[-1] if evaluations else None
        last_values = transformer["measurements"][-1]["values"] if evaluations else {}
        trend = compute_trend(
            [(datetime.fromisoformat(e["timestamp"]), e["ihi_percent"]) for e in evaluations],
            self.rules.accelerated_decline_pt_per_year,
        )
        return {
            "id": transformer["id"],
            "substation": transformer.get("substation", ""),
            "age_years": last_values.get("age_years"),
            "evaluations": len(evaluations),
            "last_evaluation": latest["timestamp"] if latest else None,
            "ihi_percent": latest["ihi_percent"] if latest else None,
            "classification": latest["classification"] if latest else None,
            "trend": trend,
            "alerts": self._alert_reasons(latest, trend),
        }

    def _alert_reasons(self, latest: Optional[dict], trend: Optional[dict]) -> list[str]:
        if latest is None:
            return []
        reasons = []
        label = latest["classification"]["label"]
        if label in self.rules.alert_classes:
            reasons.append(f"Classe {label} : {latest['classification']['action'].lower()}")
        if trend and trend["accelerated"]:
            reasons.append(
                f"Dégradation accélérée : {_fr_signed(trend['delta_pt'])} pt en {trend['days']:.0f} j "
                f"({_fr_signed(trend['rate_pt_per_year'])} pt/an)"
            )
        return reasons

    def detail(self, transformer_id: str) -> dict[str, Any]:
        transformer = self.store.get(transformer_id)
        evaluations = self._history(transformer)
        return {
            **self._summary(transformer, evaluations),
            "latest": evaluations[-1] if evaluations else None,
            "history": [
                {"timestamp": e["timestamp"], "ihi_percent": e["ihi_percent"],
                 "level": e["classification"]["level"]}
                for e in evaluations
            ],
        }

    # -- fleet ----------------------------------------------------------------
    def fleet(self) -> dict[str, Any]:
        summaries = [self._summary(t, self._history(t)) for t in self.store.transformers()]
        scored = [s for s in summaries if s["ihi_percent"] is not None]

        counts = {b.label: 0 for b in health_bands(self.config_dir)}
        for s in scored:
            counts[s["classification"]["label"]] += 1

        return {
            "transformers": sorted(
                summaries, key=lambda s: (s["ihi_percent"] is None, s["ihi_percent"] or 0)
            ),
            "distribution": counts,
            "mean_ihi_percent": (
                round(sum(s["ihi_percent"] for s in scored) / len(scored), 1) if scored else None
            ),
            "alert_count": sum(1 for s in summaries if s["alerts"]),
        }

    def alerts(self) -> list[dict[str, Any]]:
        return [s for s in self.fleet()["transformers"] if s["alerts"]]

    # -- configuration (read-only view for the UI) -----------------------------
    def config_view(self) -> dict[str, Any]:
        """Everything the UI needs to build forms and legends, straight from config/."""
        return {
            "families": [
                {
                    "name": name,
                    "label": self.thresholds.get(name, {}).get("label", name),
                    "weight": self.weights[name],
                    "parameters": [
                        {"name": p, **spec}
                        for p, spec in (self.thresholds.get(name, {}).get("parameters") or {}).items()
                    ],
                }
                for name in self.weights
            ],
            "bands": [
                {"level": b.level, "lower": b.lower, "upper": b.upper,
                 "label": b.label, "action": b.action, "band": b.band}
                for b in health_bands(self.config_dir)
            ],
            "alerts": {
                "accelerated_decline_pt_per_year": self.rules.accelerated_decline_pt_per_year,
                "alert_classes": list(self.rules.alert_classes),
            },
            "standards": load_yaml("standards_map.yaml", self.config_dir),
            "dga_ratios": [
                {"key": f"ratio_{r.name}", "label": f"{r.numerator}/{r.denominator}", "source": r.source}
                for r in GAS_RATIOS
            ],
        }
