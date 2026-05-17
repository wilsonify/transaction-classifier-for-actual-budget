from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api import ClassifierAPI
from .classifier import TransactionClassifierPlugin
from .storage import PluginRepository


def build_api() -> ClassifierAPI:
    db_path = os.getenv("ACTUAL_CLASSIFIER_DB_PATH", "/data/classifier.db")
    repository = PluginRepository(db_path=db_path)
    plugin = TransactionClassifierPlugin(repository=repository)
    return ClassifierAPI(plugin=plugin)


def build_error_response(status: int, payload: Dict[str, Any]) -> JSONResponse:
    body: Dict[str, Any] = {"error": str(payload.get("error", "internal_error"))}
    if "message" in payload:
        body["message"] = str(payload["message"])
    return JSONResponse(status_code=status, content=body)


def create_fastapi_app() -> Any:
    api = build_api()
    app = FastAPI(
        title="ActualBudget Transaction Classifier",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return api.health()

    @app.get("/metrics")
    async def metrics() -> Dict[str, Any]:
        return api.metrics()

    @app.get("/model/version")
    async def model_version() -> Dict[str, Any]:
        return api.model_version()

    @app.get("/model/versions")
    async def list_model_versions() -> Dict[str, Any]:
        return api.list_model_versions()

    @app.post("/model/versions")
    async def create_model_version(body: Dict[str, Any]) -> Dict[str, Any]:
        return api.create_model_version(body)

    @app.post("/model/activate")
    async def activate_model(body: Dict[str, Any]) -> Dict[str, Any]:
        return api.activate_model_version(body)

    @app.post("/classify")
    async def classify(body: Dict[str, Any]) -> Dict[str, Any]:
        return api.classify(body)

    @app.post("/events/transactions/imported")
    async def classify_imported(body: Dict[str, Any]) -> Dict[str, Any]:
        return api.classify_imported_transactions(body)

    @app.get("/review-queue")
    async def review_queue(limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        return api.list_review_queue({"limit": limit, "offset": offset})

    @app.post("/review-queue/resolve")
    async def resolve_review(body: Dict[str, Any]) -> Dict[str, Any]:
        return api.resolve_review_queue_item(body)

    @app.post("/feedback")
    async def feedback(body: Dict[str, Any]) -> Dict[str, Any]:
        return api.feedback(body)

    @app.post("/retrain")
    async def retrain(body: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return api.retrain_with_payload(body or {})

    @app.get("/retrain/jobs")
    async def retrain_jobs(limit: int = 50) -> Dict[str, Any]:
        return api.list_retrain_jobs({"limit": limit})

    @app.post("/retrain/jobs/run")
    async def run_retrain_job(body: Dict[str, Any]) -> Dict[str, Any]:
        return api.run_retrain_job(body)

    @app.post("/{full_path:path}")
    async def fallback_post(full_path: str, request: Request) -> Dict[str, Any]:
        raw_body = await request.body()
        status, payload = api.handle_request("POST", "/" + full_path, raw_body.decode("utf-8"))
        if status >= 400:
            return build_error_response(status, payload)
        return payload

    @app.get("/{full_path:path}")
    async def fallback_get(full_path: str) -> Dict[str, Any]:
        status, payload = api.handle_request("GET", "/" + full_path)
        if status >= 400:
            return build_error_response(status, payload)
        return payload

    return app
