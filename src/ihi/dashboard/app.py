"""FastAPI app behind the fleet dashboard.

    GET  /                                   the dashboard page
    GET  /api/config                         thresholds, weights, bands, alert rules (read-only)
    GET  /api/fleet                          every transformer's latest state + fleet summary
    GET  /api/alerts                         transformers with at least one alert
    GET  /api/transformers/{id}              one transformer: latest evaluation + IHI history
    POST /api/transformers                   register a transformer
    POST /api/evaluate                       score a reading WITHOUT saving it (try-out)
    POST /api/transformers/{id}/measurements validate, save, and return the updated transformer

Every reading goes through the same Pydantic schema as the rest of the engine,
so the dashboard can't store anything the engine would reject.
"""
from __future__ import annotations

import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from ..features.schema import ReadingBase, UnknownParameterWarning, reading_from_dict
from .service import FleetService
from .store import (
    DuplicateMeasurement,
    DuplicateTransformer,
    FleetStore,
    UnknownTransformer,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------
class MeasurementIn(BaseModel):
    timestamp: Optional[datetime] = None
    # Values stay loosely typed here on purpose: the reading schema does the real
    # validation, and its errors name the offending parameter.
    values: dict[str, Any] = Field(default_factory=dict)
    # Only for /api/evaluate: compare against this transformer's history (gas rates).
    transformer_id: Optional[str] = None


class TransformerIn(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    substation: str = ""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def _unprocessable(errors: list[dict[str, Any]]) -> HTTPException:
    return HTTPException(status_code=422, detail={"errors": errors})


def _validate(body: MeasurementIn, timestamp: datetime) -> tuple[ReadingBase, list[str]]:
    """Run a request through the reading schema. Returns (reading, warnings)."""
    # Blank form fields mean "not measured", same as leaving the key out.
    values = {k: v for k, v in body.values.items() if v is not None and v != ""}

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", UnknownParameterWarning)
        try:
            reading = reading_from_dict({**values, "timestamp": timestamp})
        except ValidationError as exc:
            raise _unprocessable([
                {"field": str(e["loc"][0]) if e["loc"] else None, "message": e["msg"]}
                for e in exc.errors()
            ]) from exc

    if not reading.measured():
        raise _unprocessable([{"field": None, "message": "Aucune valeur mesurée : saisissez au moins un paramètre."}])

    notes = [str(w.message) for w in caught if issubclass(w.category, UnknownParameterWarning)]
    return reading, notes


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
def create_app(
    store_path: str | Path,
    seed_path: str | Path | None = None,
    config_dir: str | Path | None = None,
) -> FastAPI:
    store = FleetStore(store_path, seed_path)
    service = FleetService(store, config_dir)
    app = FastAPI(title="IHI — tableau de bord", docs_url="/api/docs", redoc_url=None)

    def _detail_or_404(transformer_id: str) -> dict[str, Any]:
        try:
            return service.detail(transformer_id)
        except UnknownTransformer:
            raise HTTPException(status_code=404, detail=f"Transformateur inconnu : {transformer_id}")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/config")
    def config() -> dict[str, Any]:
        return service.config_view()

    @app.get("/api/fleet")
    def fleet() -> dict[str, Any]:
        return service.fleet()

    @app.get("/api/alerts")
    def alerts() -> list[dict[str, Any]]:
        return service.alerts()

    @app.get("/api/transformers/{transformer_id}")
    def transformer(transformer_id: str) -> dict[str, Any]:
        return _detail_or_404(transformer_id)

    @app.post("/api/transformers", status_code=201)
    def add_transformer(body: TransformerIn) -> dict[str, Any]:
        try:
            store.add_transformer(body.id.strip(), body.substation.strip())
        except DuplicateTransformer:
            raise HTTPException(status_code=409, detail=f"{body.id} existe déjà")
        return _detail_or_404(body.id.strip())

    @app.post("/api/evaluate")
    def evaluate(body: MeasurementIn) -> dict[str, Any]:
        timestamp = body.timestamp or datetime.now().replace(microsecond=0)
        reading, notes = _validate(body, timestamp)

        # For gas rates, compare with the newest stored measurement before this one.
        previous = None
        if body.transformer_id:
            try:
                history = store.get(body.transformer_id)["measurements"]
            except UnknownTransformer:
                raise HTTPException(status_code=404, detail=f"Transformateur inconnu : {body.transformer_id}")
            earlier = [m for m in history if datetime.fromisoformat(m["timestamp"]) < timestamp]
            if earlier:
                previous = (datetime.fromisoformat(earlier[-1]["timestamp"]), earlier[-1]["values"])

        result = service.evaluate(reading.measured(), timestamp, previous)
        return {**result, "warnings": notes}

    @app.post("/api/transformers/{transformer_id}/measurements", status_code=201)
    def add_measurement(transformer_id: str, body: MeasurementIn) -> dict[str, Any]:
        if body.timestamp is None:
            raise _unprocessable([{"field": "timestamp", "message": "La date de mesure est obligatoire pour enregistrer."}])
        reading, notes = _validate(body, body.timestamp)
        try:
            store.add_measurement(transformer_id, reading.timestamp, reading.measured())
        except UnknownTransformer:
            raise HTTPException(status_code=404, detail=f"Transformateur inconnu : {transformer_id}")
        except DuplicateMeasurement as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {**_detail_or_404(transformer_id), "warnings": notes}

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
