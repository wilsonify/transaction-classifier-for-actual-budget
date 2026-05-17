import unittest
from tempfile import TemporaryDirectory

from actualbudget_transaction_classifier.api import ClassifierAPI
from actualbudget_transaction_classifier.classifier import MerchantNormalizer, TransactionClassifierPlugin
from actualbudget_transaction_classifier.storage import PluginRepository
from actualbudget_transaction_classifier.models import TransactionPayload


class MerchantNormalizerTests(unittest.TestCase):
    def test_recommended_regex_normalization(self) -> None:
        normalizer = MerchantNormalizer()
        alias_map = {}
        canonical, trace = normalizer.normalize("Google *Fi Jjm8Mh", alias_map)

        self.assertEqual("google_fi", canonical)
        self.assertTrue(any("regex_match=google\\s*\\*?fi->google_fi" in item for item in trace))


class ClassifierPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin = TransactionClassifierPlugin()

    def test_rule_engine_priority_path(self) -> None:
        result = self.plugin.classify(
            TransactionPayload(
                transaction_id="txn_123",
                merchant="Wegmans #078",
                amount=-83.60,
                date="2024-05-10",
            )
        )

        self.assertEqual("groceries", result.category)
        self.assertEqual("rule_engine", result.source)
        self.assertGreaterEqual(result.confidence, 0.95)
        self.assertIn("wegmans_grocery_rule", result.rule_matches)
        self.assertIn("merchant=wegmans", result.top_features)

    def test_phone_rule_maps_to_utilities_coarse_category(self) -> None:
        result = self.plugin.classify(
            TransactionPayload(
                transaction_id="txn_phone",
                merchant="Google *Fi Jjm8Mh",
                amount=-65.0,
                date="2024-05-10",
            )
        )
        self.assertEqual("phone", result.category)
        self.assertEqual("Utilities", result.coarse_category)

    def test_low_confidence_goes_to_review(self) -> None:
        result = self.plugin.classify(
            TransactionPayload(
                transaction_id="txn_low",
                merchant="Random Unknown Vendor",
                amount=-10.0,
                date="2024-05-10",
            )
        )

        self.assertTrue(result.review_required)
        self.assertIn("txn_low", self.plugin.review_queue)
        self.assertIn(result.review_reason, {"suggested_only", "low_confidence", "unseen_merchant"})

    def test_duplicate_processing_is_prevented(self) -> None:
        payload = TransactionPayload(
            transaction_id="txn_dupe",
            merchant="Sunoco 0099368300",
            amount=-40.0,
            date="2024-05-10",
        )
        first = self.plugin.classify(payload)
        second = self.plugin.classify(payload)

        self.assertNotEqual("history_cache", first.source)
        self.assertEqual("history_cache", second.source)
        self.assertEqual(first.category, second.category)

    def test_feedback_preserves_original_prediction(self) -> None:
        payload = TransactionPayload(
            transaction_id="txn_corrected",
            merchant="Wegmans #078",
            amount=-55.0,
            date="2024-05-10",
        )
        first = self.plugin.classify(payload)
        feedback = self.plugin.feedback(transaction_id="txn_corrected", corrected_category="fitness")
        second = self.plugin.classify(payload)

        history = self.plugin.classification_history["txn_corrected"]
        self.assertEqual(first.category, history.predicted_category)
        self.assertEqual("fitness", history.corrected_category)
        self.assertEqual("fitness", second.category)
        self.assertEqual(first.category, feedback["original_predicted_category"])

    def test_repeat_merchant_uses_history_consistency_features(self) -> None:
        first = self.plugin.classify(
            TransactionPayload(
                transaction_id="txn_history_1",
                merchant="Sunoco 0099368300",
                amount=-40.0,
                date="2024-05-10",
            )
        )
        second = self.plugin.classify(
            TransactionPayload(
                transaction_id="txn_history_2",
                merchant="Sunoco 0099368300",
                amount=-41.0,
                date="2024-05-11",
            )
        )

        self.assertEqual(first.category, second.category)
        self.assertIn("historical_user_category_consistency=95%", second.explanations)
        self.assertIn("merchant_purity=0.95", second.top_features)


class ApiEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = ClassifierAPI()

    def test_required_endpoints(self) -> None:
        status, classify_body = self.api.handle_request(
            "POST",
            "/classify",
            '{"transaction_id":"txn_api","merchant":"Wegmans #098","amount":-45.0,"date":"2024-05-10"}',
        )
        self.assertEqual(200, status)
        self.assertEqual("groceries", classify_body["category"])
        self.assertIn("hierarchy_path", classify_body)
        self.assertIn("merchant_normalization_trace", classify_body)
        self.assertIn("model_probabilities", classify_body)

        status, _ = self.api.handle_request(
            "POST",
            "/feedback",
            '{"transaction_id":"txn_api","corrected_category":"groceries"}',
        )
        self.assertEqual(200, status)

        status, retrain_body = self.api.handle_request("POST", "/retrain")
        self.assertEqual(200, status)
        self.assertEqual("queued", retrain_body["status"])

        self.assertEqual(200, self.api.handle_request("GET", "/health")[0])
        self.assertEqual(200, self.api.handle_request("GET", "/metrics")[0])
        self.assertEqual(200, self.api.handle_request("GET", "/model/version")[0])

    def test_malformed_json_returns_structured_error(self) -> None:
        status, body = self.api.handle_request("POST", "/classify", "{bad")
        self.assertEqual(400, status)
        self.assertEqual("invalid_json", body["error"])

    def test_missing_classify_required_fields_returns_structured_error(self) -> None:
        status, body = self.api.handle_request("POST", "/classify", '{"transaction_id":"txn_missing"}')
        self.assertEqual(400, status)
        self.assertEqual("invalid_request", body["error"])

    def test_import_batch_requires_list_transactions(self) -> None:
        status, body = self.api.handle_request(
            "POST",
            "/events/transactions/imported",
            '{"transactions":{"transaction_id":"txn_bad"}}',
        )
        self.assertEqual(400, status)
        self.assertEqual("invalid_request", body["error"])

    def test_unknown_endpoint_returns_not_found(self) -> None:
        status, body = self.api.handle_request("GET", "/missing")
        self.assertEqual(404, status)
        self.assertEqual("not_found", body["error"])


class PersistentPluginApiTests(unittest.TestCase):
    def test_persistent_review_queue_and_lifecycle_endpoints(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = PluginRepository(db_path=f"{tmp}/classifier.db")
            try:
                plugin = TransactionClassifierPlugin(repository=repo)
                api = ClassifierAPI(plugin=plugin)

                status, batch_body = api.handle_request(
                    "POST",
                    "/events/transactions/imported",
                    """
                    {
                      "source": "sync",
                      "transactions": [
                        {"transaction_id":"txn_batch_1","merchant":"Unknown Merchant","amount":-12.0,"date":"2026-05-17"}
                      ]
                    }
                    """,
                )
                self.assertEqual(200, status)
                self.assertEqual(1, batch_body["processed"])

                status, review_body = api.handle_request("GET", "/review-queue")
                self.assertEqual(200, status)
                self.assertGreaterEqual(review_body["total"], 1)

                status, resolve_body = api.handle_request(
                    "POST",
                    "/review-queue/resolve",
                    '{"transaction_id":"txn_batch_1","corrected_category":"groceries"}',
                )
                self.assertEqual(200, status)
                self.assertTrue(resolve_body["updated"])

                status, create_model_body = api.handle_request(
                    "POST",
                    "/model/versions",
                    '{"model_version":"2026.05.17.1","taxonomy_version":"v3","training_date":"2026-05-17","macro_f1":0.94,"calibration_error":0.03,"training_rows":90000}',
                )
                self.assertEqual(200, status)
                self.assertTrue(create_model_body["created"])

                status, activate_body = api.handle_request(
                    "POST",
                    "/model/activate",
                    '{"model_version":"2026.05.17.1"}',
                )
                self.assertEqual(200, status)
                self.assertTrue(activate_body["updated"])

                status, retrain_body = api.handle_request("POST", "/retrain", '{"requested_by":"test"}')
                self.assertEqual(200, status)
                self.assertEqual("queued", retrain_body["status"])
                self.assertIn("job_id", retrain_body)

                status, run_body = api.handle_request(
                    "POST",
                    "/retrain/jobs/run",
                    '{"job_id":"' + retrain_body["job_id"] + '"}',
                )
                self.assertEqual(200, status)
                self.assertTrue(run_body["updated"])
            finally:
                repo.close()


if __name__ == "__main__":
    unittest.main()
