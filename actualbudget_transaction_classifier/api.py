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

    def health(self) -> Dict[str, Any]:
        return self.plugin.health()

    def metrics(self) -> Dict[str, Any]:
        return self.plugin.metrics()

    def model_version(self) -> Dict[str, Any]:
        return self.plugin.model_info()

    def handle_request(self, method: str, path: str, body: str = "") -> Tuple[int, Dict[str, Any]]:
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            return 400, {"error": "invalid_json", "message": "Request body is not valid JSON."}

        if method == "POST" and path == "/classify":
            try:
                return 200, self.classify(payload)
            except TypeError as exc:
                return 400, {"error": "invalid_request", "message": str(exc)}
        if method == "POST" and path == "/feedback":
            try:
                return 200, self.feedback(payload)
            except KeyError as exc:
                return 400, {"error": "invalid_request", "message": f"Missing required field: {exc.args[0]}"}
            except TypeError as exc:
                return 400, {"error": "invalid_request", "message": str(exc)}
        if method == "POST" and path == "/retrain":
            return 200, self.retrain()
        if method == "GET" and path == "/health":
            return 200, self.health()
        if method == "GET" and path == "/metrics":
            return 200, self.metrics()
        if method == "GET" and path == "/model/version":
            return 200, self.model_version()

        return 404, {"error": "not_found"}
