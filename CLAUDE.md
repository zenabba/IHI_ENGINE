# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

IHI_ENGINE computes an **Intelligent Health Index (IHI)** for power transformers from condition-monitoring measurements (DGA, thermal, oil quality, insulation, age). The design follows an external spec, `ARCHITECTURE_IHI.docx`, which is not in the repo but is cited in code comments and config. The domain vocabulary is partly French: family labels, health classes and actions are French strings.

Only **Phase 1**, the deterministic Tier-1 engine, is implemented, plus input validation and DGA features in `features/` and a local dashboard. `ingestion`, `ml`, `explain`, `fusion`, `temporal` and `api` under `src/ihi/` are placeholder packages with a one-line docstring describing their planned role. `requirements.txt` groups dependencies by phase, and later-phase ones are commented out until that phase starts.

## Project rules

- This is a **two-tier** engine. Tier 1 is the deterministic rubric anchored to standards (`src/ihi/subindex`). Tier 2 is ML that augments Tier 1 and is always bounded by it. ML may nudge the score within a configured clamp, but it must never override a safety rule, and the Tier-1 score must stay recoverable for audit.
- `config/` is the **single source of truth**. Never hardcode thresholds, weights, classification bands or override limits in Python. Read them from YAML.
- Every new module ships with pytest tests, and `pytest` must stay green.
- Prefer pandas, numpy, scikit-learn and xgboost. Ask before adding heavy dependencies. Add each new dependency to the matching phase section of `requirements.txt`.
- Keep functions small and typed. Docstrings should cite the concept or standard they implement.
- Missing measurements are normal. Handle them explicitly (`None`) and never crash. Imputation must be opt-in and recorded.
- Work in small steps (one step = one commit) and explain the plan before making large edits. The step-by-step roadmap is Parts A–D: features/ingestion, ML core, prognostics/API/MLOps, finalize.

## Commands

A local venv lives in `.venv/` (Windows: `.venv\Scripts\python`).

```bash
pip install -r requirements.txt       # Phase 1 needs only pyyaml + pytest
python run_example.py                 # demo on a sample transformer reading
python run_dashboard.py               # local dashboard at http://127.0.0.1:8000 (--reset to restore demo fleet)
python scripts/make_demo_fleet.py --check   # regenerate the synthetic demo fleet and print its IHIs
pytest                                # all tests
pytest tests/test_normalize.py::test_low_good_midpoint   # single test
```

There is no packaging (no `pyproject.toml`). Scripts and tests make `ihi` importable by adding `src/` to `sys.path` themselves, so new entry points and test files must do the same.

## Architecture (Phase 1 pipeline)

`reading dict -> sub-indices -> family indices -> weighted IHI -> classification`

1. **Input**: a flat `{parameter_name: value}` dict. A key that is absent means "not measured". It is not treated as healthy or as zero.
2. **Normalization** (`src/ihi/subindex/normalize.py`): `sub_index()` maps each value to [0, 1] (1 = healthy) with piecewise-linear functions between `normal` and `critical` thresholds. `polarity` decides the direction: `low_good` requires `normal < critical`, `high_good` requires `normal > critical`. A missing value returns `None`.
3. **Family index** (`IHIEngine._family_index` in `src/ihi/subindex/engine.py`): the plain mean of the measured sub-indices in the family. Parameters inside a family are not weighted yet.
4. **Aggregation** (`IHIEngine.compute`): families are iterated from `weights.yaml`, not from `thresholds.yaml`. Families with no measured data are dropped, and the remaining weights are **renormalized** to sum to 1. A note is added to `IHIResult.notes` when this happens. If no family has data, it raises `ValueError`. `electrical` currently has no parameters defined, so it is always dropped.
5. **Classification** (`src/ihi/decision/classify.py`): the bands in `config/classification.yaml` map `ihi_percent` to a label, a maintenance action and a `level` (0 = best). The UI colours classes by `level`, not by label.

`IHIResult` keeps provenance: each family's effective weight, per-parameter sub-indices and missing parameters, plus `top_drivers(n)`, which returns the lowest sub-indices as `family.param`.

## Dashboard (`src/ihi/dashboard/`)

This is a local test harness for the engine, not production serving (API serving is step C.3).

- `store.py` keeps the fleet in one JSON file at `data/processed/fleet.json` (gitignored). It's seeded on first run from `data/demo/fleet.json`, which is **synthetic** data produced by `scripts/make_demo_fleet.py`.
- `service.py` runs every stored measurement through `IHIEngine`, `classify` and `dga_ratios`, then adds the trend (IHI points/year between the last two evaluations) and the alerts from `config/alerts.yaml`. It must never compute a score itself.
- `app.py` holds the FastAPI routes. Readings go through `reading_from_dict`, and field errors come back as 422 `{"detail": {"errors": [{field, message}]}}`. `POST /api/evaluate` scores a reading without saving it.
- `static/` is vanilla JS with no build step. Forms, legends and the settings page are built from `GET /api/config`, so parameters, thresholds and bands must never be written into the JS.
- Config is cached at start-up, so restart the server after editing `config/*.yaml`.

## Configuration is the source of truth

All thresholds and weights live in `config/`. They must not be hardcoded in the engine. Always load them through `src/ihi/config.py`, which resolves the repo-root `config/` by default. Components take `config_dir=` to override it.

- `config/thresholds.yaml`: `families -> <family> -> parameters -> <param>: {normal, critical, polarity, unit, allow_negative?}`. A parameter name is the key expected in the reading dict. It must be unique across families. The input schema (`src/ihi/features/schema.py`) is **generated** from this file, so a new parameter is validated automatically.
- `config/weights.yaml`: `family_weights`, which sum to 1.0.
- `config/classification.yaml`: health bands (lower bound, label, action), ordered best first and ending at 0.
- `config/alerts.yaml`: the accelerated-decline threshold (placeholder, pt/year) and which classes raise alerts.
- `config/standards_map.yaml`: the IEC/IEEE standard behind each family's thresholds, kept for audit traceability.

The config comments say that the current thresholds and weights are unverified starting values copied from the proposal document. That document contains two weight tables that disagree. Keep these caveats when editing the config, and update `standards_map.yaml` when a threshold is validated. The config also stresses auditability: every historical IHI must be reproducible.
