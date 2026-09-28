# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

IHI_ENGINE computes an **Intelligent Health Index (IHI)** for power transformers from condition-monitoring measurements (DGA, thermal, oil quality, insulation, age). The design follows an external spec, `ARCHITECTURE_IHI.docx`, which is not in the repo but is cited in code comments and config. The domain vocabulary is partly French: family labels, health classes and actions are French strings.

Only **Phase 1**, the deterministic Tier-1 engine, is implemented. `ingestion`, `features`, `ml`, `explain`, `fusion`, `temporal` and `api` under `src/ihi/` are placeholder packages with a one-line docstring describing their planned role. `requirements.txt` groups dependencies by phase, and later-phase ones are commented out until that phase starts.

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
5. **Classification** (`src/ihi/decision/classify.py`): fixed 20-point bands map `ihi_percent` to a label and a maintenance action.

`IHIResult` keeps provenance: each family's effective weight, per-parameter sub-indices and missing parameters, plus `top_drivers(n)`, which returns the lowest sub-indices as `family.param`.

## Configuration is the source of truth

All thresholds and weights live in `config/`. They must not be hardcoded in the engine. By default `IHIEngine()` loads the repo-root `config/` directory, found by walking up from `engine.py` (`parents[3]`). Pass `config_dir=` to override it.

- `config/thresholds.yaml`: `families -> <family> -> parameters -> <param>: {normal, critical, polarity, unit}`. A parameter name is the key expected in the reading dict.
- `config/weights.yaml`: `family_weights`, which sum to 1.0.
- `config/standards_map.yaml`: the IEC/IEEE standard behind each family's thresholds, kept for audit traceability.

The config comments say that the current thresholds and weights are unverified starting values copied from the proposal document. That document contains two weight tables that disagree. Keep these caveats when editing the config, and update `standards_map.yaml` when a threshold is validated. The config also stresses auditability: every historical IHI must be reproducible.
