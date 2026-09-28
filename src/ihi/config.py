"""Shared helpers for locating and reading the YAML files in config/.

Every module that needs thresholds or weights goes through here, so there is
exactly one notion of "where the config lives".
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def default_config_dir() -> Path:
    """Return repo_root/config (this file is src/ihi/config.py)."""
    return Path(__file__).resolve().parents[2] / "config"


def resolve_config_dir(config_dir: str | Path | None = None) -> Path:
    """Use the caller's directory if given, otherwise the repo default."""
    return Path(config_dir) if config_dir else default_config_dir()


def load_yaml(filename: str, config_dir: str | Path | None = None) -> Any:
    """Parse one YAML file from the config directory."""
    path = resolve_config_dir(config_dir) / filename
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_thresholds(config_dir: str | Path | None = None) -> dict:
    """Return the `families` mapping from thresholds.yaml."""
    return load_yaml("thresholds.yaml", config_dir)["families"]


def load_family_weights(config_dir: str | Path | None = None) -> dict:
    """Return the `family_weights` mapping from weights.yaml."""
    return load_yaml("weights.yaml", config_dir)["family_weights"]
