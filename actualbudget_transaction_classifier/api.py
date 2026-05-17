from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Dict, Tuple

from .classifier import TransactionClassifierPlugin
from .models import TransactionPayload


class ClassifierAPI:
    def __init__(self, plugin: TransactionClassifierPlugin | None = None) -> None:
        self.plugin = plugin or TransactionClassifierPlugin()

    def classify(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = self.plugin.classify(TransactionPayload(**payload))
        body = asdict(result)
        body["auto_apply"] = result.confidence >= 0.8 and not result.review_required
        return body

    def feedback(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.plugin.feedback(
            transaction_id=payload["transaction_id"],
            corrected_category=payload["corrected_category"],
        )

    def retrain(self) -> Dict[str, Any]:
        return self.plugin.retrain()

    def retrain_with_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        requested_by = str(payload.get("requested_by", "system"))
        return self.plugin.retrain(requested_by=requested_by)

    def health(self) -> Dict[str, Any]:
        return self.plugin.health()

    def metrics(self) -> Dict[str, Any]:
        return self.plugin.metrics()

    def model_version(self) -> Dict[str, Any]:
        return self.plugin.model_info()

    def list_model_versions(self) -> Dict[str, Any]:
        return self.plugin.list_model_versions()

    def create_model_version(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.plugin.create_model_version(
            model_version=str(payload["model_version"]),
            taxonomy_version=str(payload.get("taxonomy_version", self.plugin.model_version.taxonomy_version)),
            training_date=str(payload.get("training_date", self.plugin.model_version.training_date)),
            macro_f1=float(payload.get("macro_f1", self.plugin.model_version.macro_f1)),
            calibration_error=float(payload.get("calibration_error", self.plugin.model_version.calibration_error)),
            training_rows=int(payload.get("training_rows", self.plugin.model_version.training_rows)),
            metadata=payload.get("metadata"),
        )

    def activate_model_version(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.plugin.activate_model_version(model_version=str(payload["model_version"]))

    def classify_imported_transactions(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        transactions = payload.get("transactions", [])
        if not isinstance(transactions, list):
            raise TypeError("transactions must be a list")
        result = self.plugin.classify_batch(transactions)
        result["source"] = payload.get("source", "import")
        result["batch_id"] = payload.get("batch_id")
        return result

    def list_review_queue(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        limit = int(payload.get("limit", 100))
        offset = int(payload.get("offset", 0))
        return self.plugin.list_review_queue(limit=limit, offset=offset)

    def resolve_review_queue_item(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.plugin.resolve_review_item(
            transaction_id=str(payload["transaction_id"]),
            corrected_category=str(payload["corrected_category"]),
            note=str(payload.get("note", "")),
        )

    def list_retrain_jobs(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        limit = int(payload.get("limit", 50))
        return self.plugin.list_retrain_jobs(limit=limit)

    def run_retrain_job(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.plugin.run_retrain_job(job_id=str(payload["job_id"]))

    def _invalid_request_response(self, exc: Exception) -> Tuple[int, Dict[str, Any]]:
        if isinstance(exc, KeyError):
            return 400, {"error": "invalid_request", "message": f"Missing required field: {exc.args[0]}"}
        return 400, {"error": "invalid_request", "message": str(exc)}

    def _handle_post(self, path: str, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        if path == "/classify":
            try:
                return 200, self.classify(payload)
            except TypeError as exc:
                return self._invalid_request_response(exc)
        if path == "/feedback":
            try:
                return 200, self.feedback(payload)
            except (KeyError, TypeError) as exc:
                return self._invalid_request_response(exc)
        if path == "/retrain":
            return 200, self.retrain_with_payload(payload)
        if path == "/retrain/jobs/run":
            return 200, self.run_retrain_job(payload)
        if path == "/model/versions":
            return 200, self.create_model_version(payload)
        if path == "/model/activate":
            return 200, self.activate_model_version(payload)
        if path == "/events/transactions/imported":
            try:
                return 200, self.classify_imported_transactions(payload)
            except TypeError as exc:
                return self._invalid_request_response(exc)
        if path == "/review-queue/resolve":
            return 200, self.resolve_review_queue_item(payload)
        return 404, {"error": "not_found"}

    def _handle_get(self, path: str, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        if path == "/retrain/jobs":
            return 200, self.list_retrain_jobs(payload)
        if path == "/health":
            return 200, self.health()
        if path == "/metrics":
            return 200, self.metrics()
        if path == "/model/version":
            return 200, self.model_version()
        if path == "/model/versions":
            return 200, self.list_model_versions()
        if path == "/review-queue":
            return 200, self.list_review_queue(payload)
        return 404, {"error": "not_found"}

    def handle_request(self, method: str, path: str, body: str = "") -> Tuple[int, Dict[str, Any]]:
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            return 400, {"error": "invalid_json", "message": "Request body is not valid JSON."}

        if method == "POST":
            return self._handle_post(path, payload)
        if method == "GET":
            return self._handle_get(path, payload)
        return 404, {"error": "not_found"}
