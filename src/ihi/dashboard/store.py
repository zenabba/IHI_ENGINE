"""JSON file store for the dashboard's fleet: transformers and their measurements.

This is deliberately simple (one JSON file, rewritten on each change). It's a
test harness for the engine, not the production data layer: real ingestion
arrives in ingestion/ (step A.4).

File layout:
    {"transformers": [
        {"id": "TR-01", "substation": "Poste 1",
         "measurements": [{"timestamp": "2026-06-30T00:00:00", "values": {"H2": 90, ...}}]}
    ]}

Only validated values are ever written: callers pass readings that already went
through the Pydantic schema.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


class StoreError(Exception):
    """Base class for store problems the API turns into HTTP errors."""


class UnknownTransformer(StoreError):
    pass


class DuplicateTransformer(StoreError):
    pass


class DuplicateMeasurement(StoreError):
    pass


class FleetStore:
    def __init__(self, path: str | Path, seed_path: str | Path | None = None):
        """Open the store at `path`, creating it from `seed_path` if it doesn't exist yet."""
        self.path = Path(path)
        self._lock = threading.Lock()   # FastAPI runs sync endpoints in a thread pool

        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if seed_path is not None:
                shutil.copyfile(seed_path, self.path)
            else:
                self._write({"transformers": []})

    # -- reading --------------------------------------------------------------
    def _read(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def transformers(self) -> list[dict[str, Any]]:
        """All transformers, each with its measurements sorted oldest first."""
        with self._lock:
            data = self._read()
        for t in data["transformers"]:
            t["measurements"].sort(key=lambda m: m["timestamp"])
        return data["transformers"]

    def get(self, transformer_id: str) -> dict[str, Any]:
        for t in self.transformers():
            if t["id"] == transformer_id:
                return t
        raise UnknownTransformer(transformer_id)

    # -- writing --------------------------------------------------------------
    def _write(self, data: dict[str, Any]) -> None:
        # Write to a temp file then swap it in, so a crash mid-write can't
        # leave a half-written (unreadable) store behind.
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def add_transformer(self, transformer_id: str, substation: str = "") -> dict[str, Any]:
        with self._lock:
            data = self._read()
            if any(t["id"] == transformer_id for t in data["transformers"]):
                raise DuplicateTransformer(transformer_id)
            entry = {"id": transformer_id, "substation": substation, "measurements": []}
            data["transformers"].append(entry)
            self._write(data)
        return entry

    def add_measurement(
        self, transformer_id: str, timestamp: datetime, values: dict[str, float]
    ) -> None:
        """Append one validated measurement. Two measurements of the same
        transformer can't share a timestamp (rates of change would divide by 0)."""
        stamp = timestamp.isoformat()
        with self._lock:
            data = self._read()
            target = next((t for t in data["transformers"] if t["id"] == transformer_id), None)
            if target is None:
                raise UnknownTransformer(transformer_id)
            if any(m["timestamp"] == stamp for m in target["measurements"]):
                raise DuplicateMeasurement(f"{transformer_id} already has a measurement at {stamp}")
            target["measurements"].append({"timestamp": stamp, "values": values})
            self._write(data)
