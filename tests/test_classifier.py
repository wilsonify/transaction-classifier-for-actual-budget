import unittest

from actualbudget_transaction_classifier.api import ClassifierAPI
from actualbudget_transaction_classifier.classifier import MerchantNormalizer, TransactionClassifierPlugin
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


if __name__ == "__main__":
    unittest.main()
