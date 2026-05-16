from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .models import (
    ClassificationHistoryEntry,
    ClassificationResult,
    MerchantRegistryEntry,
    ModelVersion,
    ReviewQueueEntry,
    TransactionPayload,
)


class MerchantNormalizer:
    _punctuation = re.compile(r"[^a-z0-9\s]")
    _store_number = re.compile(r"\b\d{2,}\b")
    _space = re.compile(r"\s+")

    _canonical_rules: List[Tuple[re.Pattern[str], str]] = [
        (re.compile(r"wegmans.*"), "wegmans"),
        (re.compile(r"giant\s+\d+"), "giant"),
        (re.compile(r"sunoco.*"), "sunoco"),
        (re.compile(r"google\s*\*?fi"), "google_fi"),
        (re.compile(r"dunkin.*"), "dunkin"),
    ]

    def normalize(self, merchant: str, alias_map: Dict[str, str]) -> Tuple[str, List[str]]:
        trace = []
        text = merchant.strip().lower()
        trace.append(f"lowercase={text}")

        text = self._punctuation.sub(" ", text)
        trace.append(f"punctuation_stripped={text}")

        text = self._store_number.sub(" ", text)
        trace.append(f"store_numbers_removed={text}")

        text = self._space.sub(" ", text).strip()
        trace.append(f"ocr_cleanup={text}")

        if text in alias_map:
            resolved = alias_map[text]
            trace.append(f"alias_match={resolved}")
            return resolved, trace

        for pattern, canonical in self._canonical_rules:
            if pattern.fullmatch(text) or pattern.search(text):
                trace.append(f"regex_match={pattern.pattern}->{canonical}")
                return canonical, trace

        trace.append("canonical_resolution=fallback")
        return text.replace(" ", "_"), trace


class RuleEngine:
    def __init__(self) -> None:
        self._rules = [
            # ── Financial / transfers (check early so they don't mis-match food rules) ──
            {
                "id": "financial_transfer_keywords",
                "priority": 99,
                "original_contains_any": ["autopay", "e-payment", "crcardpmt", "credit card payment"],
                "category": "transfers",
                "confidence": 0.92,
            },
            {
                "id": "monthly_interest",
                "confidence": 0.95,
            },
            # ── Income ────────────────────────────────────────────────────────────────
            {
                "id": "paycheck_income",
                "priority": 97,
                "original_contains_any": ["baker hughes", "payroll", "direct dep"],
                "category": "paychecks",
                "confidence": 0.93,
            },
            # ── Groceries ─────────────────────────────────────────────────────────────
            {
                "id": "wegmans_grocery_rule",
                "priority": 96,
                "original_contains": "wegmans",
                "category": "groceries",
                "confidence": 0.99,
            },
            {
                "id": "giant_center_entertainment",
                "priority": 95,
                "original_contains": "giant center",
                "category": "entertainment_recreation",
                "confidence": 0.92,
            },
            {
                "id": "giant_food_groceries",
                "priority": 94,
                "original_contains": "giant",
                "category": "groceries",
                "confidence": 0.92,
            },
            {
                "id": "weis_markets_groceries",
                "priority": 93,
                "original_contains": "weis",
                "category": "groceries",
                "confidence": 0.92,
            },
            {
                "id": "walmart_large_shopping",
                "priority": 92,
                "original_contains_any": ["walmart", "wal-mart"],
                "amount_gte": 100.0,
                "category": "shopping",
                "confidence": 0.85,
            },
            {
                "id": "walmart_grocery",
                "priority": 91,
                "original_contains_any": ["walmart", "wal-mart"],
                "category": "groceries",
                "confidence": 0.80,
            },
            {
                "id": "wine_and_spirits_groceries",
                "priority": 90,
                "original_contains_any": ["wine and spirits", "wine & spirits", "pa wine"],
                "category": "groceries",
                "confidence": 0.90,
            },
            # ── Coffee shops ──────────────────────────────────────────────────────────
            {
                "id": "dunkin_coffee_rule",
                "priority": 89,
                "original_contains": "dunkin",
                "category": "coffee_shops",
                "confidence": 0.96,
            },
            {
                "id": "starbucks_coffee",
                "priority": 88,
                "original_contains": "starbucks",
                "category": "coffee_shops",
                "confidence": 0.97,
            },
            {
                "id": "panera_coffee",
                "priority": 87,
                "original_contains": "panera",
                "category": "coffee_shops",
                "confidence": 0.87,
            },
            {
                "id": "coffee_keyword",
                "priority": 86,
                "original_contains": "coffee",
                "category": "coffee_shops",
                "confidence": 0.88,
            },
            # ── Gas stations ──────────────────────────────────────────────────────────
            {
                "id": "sunoco_gas_rule",
                "priority": 85,
                "original_contains": "sunoco",
                "category": "gas",
                "confidence": 0.98,
            },
            {
                "id": "shell_gas",
                "priority": 84,
                "original_contains": "shell",
                "category": "gas",
                "confidence": 0.90,
            },
            {
                "id": "exxonmobil_gas",
                "priority": 83,
                "original_contains_any": ["exxonmobil", "exxon"],
                "category": "gas",
                "confidence": 0.95,
            },
            {
                "id": "bp_gas",
                "priority": 82,
                "original_contains": "bp gas",
                "category": "gas",
                "confidence": 0.90,
            },
            {
                "id": "wawa_gas",
                "priority": 81,
                "original_contains": "wawa",
                "category": "gas",
                "confidence": 0.82,
            },
            {
                "id": "sheetz_gas",
                "priority": 80,
                "original_contains": "sheetz",
                "category": "gas",
                "confidence": 0.92,
            },
            {
                "id": "bucees_gas",
                "priority": 79,
                "original_contains_any": ["buc-ee", "bucees", "buc ee"],
                "category": "gas",
                "confidence": 0.88,
            },
            # ── Phone ─────────────────────────────────────────────────────────────────
            {
                "id": "google_fi_phone_rule",
                "priority": 78,
                "original_contains_any": ["google *fi", "google fi", "google_fi"],
                "category": "phone",
                "confidence": 0.98,
            },
            # ── Utilities ─────────────────────────────────────────────────────────────
            {
                "id": "service_electric_cable",
                "priority": 77,
                "original_contains_any": ["service elec", "serviceelectric"],
                "category": "cable_internet",
                "confidence": 0.97,
            },
            {
                "id": "lewisburg_water",
                "priority": 76,
                "original_contains": "lewisburg area joint",
                "category": "water",
                "confidence": 0.99,
            },
            {
                "id": "fishers_disposal_garbage",
                "priority": 75,
                "original_contains": "fishers disposal",
                "category": "garbage",
                "confidence": 0.98,
            },
            # ── Transport ─────────────────────────────────────────────────────────────
            {
                "id": "ezpass_tolls",
                "priority": 74,
                "original_contains_any": ["e-zpass", "ezpass", "turnpike", "eractoll"],
                "category": "parking_tolls",
                "confidence": 0.92,
            },
            {
                "id": "parking_services",
                "priority": 73,
                "original_contains_any": ["spothero", "parkingmeter", "parkmobile", "nyc dot parking", "university parking"],
                "category": "parking_tolls",
                "confidence": 0.90,
            },
            {
                "id": "penndot_auto",
                "priority": 72,
                "original_contains_any": ["pa driver", "penndot", "pennsylvania driver"],
                "category": "auto_maintenance",
                "confidence": 0.92,
            },
            {
                "id": "uber_rideshare",
                "priority": 71,
                "original_contains": "uber",
                "category": "rideshare",
                "confidence": 0.92,
            },
            {
                "id": "public_transit",
                "priority": 70,
                "original_contains_any": ["nj transit", "njtransit", "omny", "septa", "mta nyc"],
                "category": "public_transit",
                "confidence": 0.93,
            },
            {
                "id": "enterprise_car_rental",
                "priority": 69,
                "original_contains": "enterprise",
                "category": "car_rental",
                "confidence": 0.88,
            },
            # ── Fitness ───────────────────────────────────────────────────────────────
            {
                "id": "ymca_fitness",
                "priority": 68,
                "original_contains": "ymca",
                "category": "fitness",
                "confidence": 0.95,
            },
            # ── Entertainment ─────────────────────────────────────────────────────────
            {
                "id": "spotify_entertainment",
                "priority": 67,
                "original_contains": "spotify",
                "category": "entertainment_recreation",
                "confidence": 0.96,
            },
            # ── Business / office ─────────────────────────────────────────────────────
            {
                "id": "github_office",
                "priority": 66,
                "original_contains": "github",
                "category": "office_supplies",
                "confidence": 0.95,
            },
            {
                "id": "cloudflare_office",
                "priority": 65,
                "original_contains": "cloudflare",
                "category": "office_supplies",
                "confidence": 0.93,
            },
            {
                "id": "aws_office",
                "priority": 64,
                "original_contains_any": ["amazon web services", "aws"],
                "category": "office_supplies",
                "confidence": 0.90,
            },
            {
                "id": "backblaze_office",
                "priority": 63,
                "original_contains": "backblaze",
                "category": "office_supplies",
                "confidence": 0.94,
            },
            # ── Shopping ──────────────────────────────────────────────────────────────
            {
                "id": "amazon_shopping",
                "priority": 62,
                "original_contains": "amazon",
                "category": "shopping",
                "confidence": 0.82,
            },
            {
                "id": "doordash_dining",
                "priority": 61,
                "original_contains": "doordash",
                "category": "dining_out",
                "confidence": 0.88,
            },
            # ── Health ────────────────────────────────────────────────────────────────
            {
                "id": "cvs_pharmacy",
                "priority": 60,
                "original_contains": "cvs",
                "category": "pharmacy",
                "confidence": 0.90,
            },
            # ── Taxes / financial services ────────────────────────────────────────────
            {
                "id": "turbotax_tax",
                "priority": 59,
                "original_contains": "turbotax",
                "category": "taxes",
                "confidence": 0.97,
            },
            {
                "id": "irs_taxes",
                "priority": 58,
                "original_contains": "irs",
                "category": "taxes",
                "confidence": 0.97,
            },
            {
                "id": "fidelity_investments",
                "priority": 57,
                "original_contains": "fidelity",
                "category": "investments",
                "confidence": 0.92,
            },
            # ── Home ──────────────────────────────────────────────────────────────────
            {
                "id": "landscaping_home",
                "priority": 56,
                "original_contains_any": ["landscapes", "landscaping", "landscape"],
                "category": "home_maintenance",
                "confidence": 0.85,
            },
        ]

    @staticmethod
    def _rule_matches(rule: Dict[str, object], search_text: str, amount: float) -> bool:
        text_contains = rule.get("text_contains")
        amount_lt = rule.get("amount_lt")
        amount_gte = rule.get("amount_gte")

        conditions = [
            isinstance(text_contains, str) and text_contains in search_text,
            isinstance(amount_lt, (int, float)) and amount < amount_lt,
            isinstance(amount_gte, (int, float)) and amount >= amount_gte,
        ]
        return all(conditions)

    def apply(self, merchant_canonical: str, notes_text: str = "", amount: float = 0.0) -> Tuple[Optional[Dict[str, object]], List[str]]:
        search_text = f"{merchant_canonical} {notes_text.strip().lower()}"
        matches: List[Tuple[int, Dict[str, object]]] = []
        trace: List[str] = []
        for rule in self._rules:
            if self._rule_matches(rule, search_text, amount):
                matches.append((int(rule["priority"]), rule))  # type: ignore[arg-type]
        if not matches:
            return None, trace

        _, selected = max(matches, key=lambda item: item[0])
        trace.append(str(selected["id"]))
        return selected, trace


class ConfidenceCalibrator:
    def __init__(self, method: str = "temperature_scaling", temperature: float = 1.25) -> None:
        self.method = method
        self.temperature = temperature

    def calibrate(self, probability: float) -> float:
        bounded = min(max(probability, 1e-6), 1 - 1e-6)
        if self.method == "platt_scaling":
            logit = math.log(bounded / (1 - bounded))
            return 1 / (1 + math.exp(-(0.9 * logit - 0.02)))
        if self.method == "isotonic_regression":
            return max(0.0, min(1.0, 0.1 + 0.85 * bounded))
        # temperature scaling default
        logit = math.log(bounded / (1 - bounded))
        scaled = logit / self.temperature
        return 1 / (1 + math.exp(-scaled))


class HierarchicalMLPipeline:
    _keyword_map = {
        # Food
        "groceries": ("spending_income", "Food", 0.92),
        "coffee": ("spending_income", "Food", 0.86),
        "dining": ("spending_income", "Food", 0.78),
        "restaurant": ("spending_income", "Food", 0.78),
        "brewing": ("spending_income", "Food", 0.76),
        "pizza": ("spending_income", "Food", 0.82),
        "bakery": ("spending_income", "Food", 0.80),
        "sushi": ("spending_income", "Food", 0.82),
        "kitchen": ("spending_income", "Food", 0.72),
        # Transport
        "gas": ("spending_income", "Transport", 0.88),
        "parking": ("spending_income", "Transport", 0.78),
        "tolls": ("spending_income", "Transport", 0.78),
        "transit": ("spending_income", "Transport", 0.82),
        "uber": ("spending_income", "Transport", 0.80),
        # Utilities
        "garbage": ("spending_income", "Utilities", 0.83),
        "phone": ("spending_income", "Utilities", 0.87),
        # Lifestyle / health
        "fitness": ("spending_income", "Lifestyle", 0.84),
        "pharmacy": ("spending_income", "Health", 0.82),
        # Entertainment
        "entertainment": ("spending_income", "Entertainment", 0.76),
        "streaming": ("spending_income", "Entertainment", 0.82),
        "museum": ("spending_income", "Entertainment", 0.80),
        "theater": ("spending_income", "Entertainment", 0.80),
        # Shopping
        "shopping": ("spending_income", "Shopping", 0.72),
        "amazon": ("spending_income", "Shopping", 0.72),
        "walmart": ("spending_income", "Shopping", 0.72),
        # Income
        "payroll": ("financial", "Income", 0.93),
        "paycheck": ("financial", "Income", 0.93),
        # Financial
        "interest": ("financial", "Financial", 0.88),
        "transfer": ("financial", "Financial", 0.88),
        "tax": ("financial", "Financial", 0.82),
    }

    def infer(self, merchant_canonical: str, amount: float) -> Tuple[str, str, str, Dict[str, float], float]:
        merchant_text = merchant_canonical.replace("_", " ")
        category = "misc"
        flow = "financial" if amount > 0 else "spending_income"
        coarse = "Uncategorized"
        confidence = 0.52

        for keyword, (mapped_flow, mapped_coarse, mapped_confidence) in self._keyword_map.items():
            if keyword in merchant_text:
                category = keyword if keyword != "coffee" else "coffee_shops"
                flow, coarse, confidence = mapped_flow, mapped_coarse, mapped_confidence
                break

        probabilities = {
            "groceries": 0.05,
            "coffee_shops": 0.05,
            "gas": 0.05,
            "phone": 0.05,
            "misc": 0.8,
        }
        probabilities[category] = max(probabilities.get(category, 0.05), confidence)

        total = sum(probabilities.values())
        normalized_probs = {k: round(v / total, 4) for k, v in probabilities.items()}
        return flow, coarse, category, normalized_probs, confidence


class TransactionClassifierPlugin:
    def __init__(self) -> None:
        self.normalizer = MerchantNormalizer()
        self.rule_engine = RuleEngine()
        self.ml = HierarchicalMLPipeline()
        self.calibrator = ConfidenceCalibrator()
        self.model_version = ModelVersion()

        self.merchant_registry: Dict[str, MerchantRegistryEntry] = {
            "wegmans": MerchantRegistryEntry(
                canonical_name="wegmans",
                aliases=["wegmans #078", "wegmans #098"],
                default_category="groceries",
                confidence=0.99,
                updated_at=datetime.now(timezone.utc).isoformat(),
                transaction_count=284,
            )
        }
        self.classification_history: Dict[str, ClassificationHistoryEntry] = {}
        self.review_queue: Dict[str, ReviewQueueEntry] = {}
        self.merchant_category_counts: Dict[str, Counter[str]] = defaultdict(Counter)

    def _alias_map(self) -> Dict[str, str]:
        aliases: Dict[str, str] = {}
        for canonical, entry in self.merchant_registry.items():
            aliases[canonical] = canonical
            for alias in entry.aliases:
                aliases[alias.lower()] = canonical
        return aliases

    def _user_history_match(self, merchant_canonical: str) -> Optional[Tuple[str, float]]:
        merchant_counts = self.merchant_category_counts.get(merchant_canonical)
        if not merchant_counts:
            return None
        category, count = merchant_counts.most_common(1)[0]
        total = sum(merchant_counts.values())
        consistency = count / max(total, 1)
        return category, min(0.95, 0.65 + consistency * 0.3)

    def _build_explanations(
        self,
        merchant_canonical: str,
        confidence: float,
        source: str,
        normalization_trace: List[str],
        rule_matches: List[str],
        history_consistency: Optional[float],
    ) -> Tuple[List[str], List[str]]:
        explanations = [
            f"prediction_source={source}",
            f"merchant={merchant_canonical}",
            f"confidence={confidence:.2f}",
        ]
        if rule_matches:
            explanations.append("deterministic_rule_matched")
        if history_consistency is not None:
            explanations.append(f"historical_user_category_consistency={history_consistency:.0%}")

        top_features = [
            f"merchant={merchant_canonical}",
            f"merchant_purity={history_consistency:.2f}" if history_consistency is not None else "merchant_purity=unknown",
            "recurring_pattern=true" if history_consistency and history_consistency > 0.8 else "recurring_pattern=false",
        ]
        if normalization_trace:
            top_features.append("merchant_normalized=true")
        return explanations, top_features

    def _review_decision(self, confidence: float, merchant_canonical: str) -> Tuple[bool, bool, Optional[str]]:
        unseen_merchant = merchant_canonical not in self.merchant_registry
        if confidence >= 0.95:
            return False, False, None
        if 0.80 <= confidence < 0.95:
            return False, True, "medium_confidence"
        if 0.50 <= confidence < 0.80:
            return True, True, "suggested_only"
        reason = "low_confidence" if not unseen_merchant else "unseen_merchant"
        return True, True, reason

    @staticmethod
    def _coarse_from_category(category: str) -> str:
        _map: Dict[str, str] = {
            # Food
            "groceries": "Food",
            "coffee_shops": "Food",
            "dining_out": "Food",
            # Transport
            "gas": "Transport",
            "parking": "Transport",
            "parking_tolls": "Transport",
            "parking & tolls": "Transport",
            "public_transit": "Transport",
            "rideshare": "Transport",
            "car_rental": "Transport",
            "auto_maintenance": "Transport",
            # Utilities
            "phone": "Utilities",
            "garbage": "Utilities",
            "cable_internet": "Utilities",
            "water": "Utilities",
            # Lifestyle
            "fitness": "Lifestyle",
            # Entertainment
            "entertainment_recreation": "Entertainment",
            # Shopping
            "shopping": "Shopping",
            # Health
            "pharmacy": "Health",
            # Business
            "office_supplies": "Business",
            # Income
            "paychecks": "Income",
            # Financial
            "investments": "Financial",
            "interest": "Financial",
            "transfers": "Financial",
            "taxes": "Financial",
            # Home
            "home_maintenance": "Home",
        }
        return _map.get(category, "Uncategorized")

    def classify(self, payload: TransactionPayload) -> ClassificationResult:
        merchant_canonical, _ = self.normalizer.normalize(payload.merchant, self._alias_map())
        rule, _ = self.rule_engine.apply(merchant_canonical, payload.notes, payload.amount)
        model_scores = {}
        if hasattr(self, 'model'):
            predict_proba = getattr(self.model, 'predict_proba', None)
            if callable(predict_proba):
                scores = predict_proba(payload)
                if isinstance(scores, dict) and all(isinstance(k, str) and isinstance(v, (int, float)) for k, v in scores.items()):
                    model_scores = scores

        category_scores = {str(rule): 1.0} if rule else model_scores
        final_category, confidence, *_ = defuzzify(
            category_scores, model_scores=model_scores, rule_override=rule
        )

def defuzzify(category_scores, strategy="hybrid", config=None, model_scores=None, fuzzy_scores=None, rule_override=None):
    if config is None:
        config = {"threshold": 0.6, "margin": 0.15, "fallback": "model"}
    normalized = {k: max(v, 0.0) for k, v in category_scores.items()}
    total = sum(normalized.values())
    if total > 0:
        normalized = {k: v / total for k, v in normalized.items()}
    top_category, top_score = max(normalized.items(), key=lambda x: x[1])
    second_score = max((v for k, v in normalized.items() if k != top_category), default=0.0)
    margin = top_score - second_score
    if top_score >= config["threshold"] and margin >= config["margin"]:
        return top_category, top_score, margin, normalized, False, "defuzzified by threshold"
    return "uncertain", top_score, margin, normalized, True, "marked uncertain"
        # Initialize variables
        explanations = []
        review_required = False
        review_reason = None

        # Return classification result with corrected argument types
        return ClassificationResult(
            transaction_id=payload.transaction_id,
            category=final_category,
            confidence=confidence,
            coarse_category="unknown",
            flow="unknown",
            source="classifier",
            explanations=explanations,
            top_features=[],
            merchant_normalization_trace=[],
            rule_matches=[],
            model_probabilities=model_scores,
            hierarchy_path=[],
        )

        if merchant_canonical in self.merchant_registry:
            self.merchant_registry[merchant_canonical].transaction_count += 1

        self.merchant_category_counts[merchant_canonical][final_category] += 1

        if review_required:
            self.review_queue[payload.transaction_id] = ReviewQueueEntry(
                transaction_id=payload.transaction_id,
                reason=review_reason or "manual_review",
                confidence=confidence,
                predicted_category=final_category,
                explanations=explanations,
                suggested_alternatives=alternatives,
            )

        return result

    def feedback(self, transaction_id: str, corrected_category: str) -> Dict[str, object]:
        history = self.classification_history.get(transaction_id)
        if not history:
            return {"updated": False, "reason": "transaction_not_found"}

        history.corrected = True
        history.corrected_category = corrected_category

        if transaction_id in self.review_queue:
            del self.review_queue[transaction_id]

        return {
            "updated": True,
            "transaction_id": transaction_id,
            "original_predicted_category": history.predicted_category,
            "corrected_category": corrected_category,
        }

    def retrain(self) -> Dict[str, object]:
        corrected_rows = sum(1 for row in self.classification_history.values() if row.corrected)
        self.model_version.training_date = datetime.now(timezone.utc).date().isoformat()
        return {
            "status": "queued",
            "corrected_rows": corrected_rows,
            "model_version": self.model_version.model_version,
            "taxonomy_version": self.model_version.taxonomy_version,
        }

    def health(self) -> Dict[str, str]:
        return {"status": "ok", "mode": "local_only", "telemetry": "disabled"}

    def metrics(self) -> Dict[str, object]:
        total = len(self.classification_history)
        in_review = len(self.review_queue)
        corrected = sum(1 for row in self.classification_history.values() if row.corrected)
        return {
            "total_classified": total,
            "review_queue_size": in_review,
            "correction_count": corrected,
            "manual_review_rate": round(in_review / total, 4) if total else 0.0,
        }

    def model_info(self) -> Dict[str, object]:
        return {
            "model_version": self.model_version.model_version,
            "taxonomy_version": self.model_version.taxonomy_version,
            "training_date": self.model_version.training_date,
            "macro_f1": self.model_version.macro_f1,
            "calibration_error": self.model_version.calibration_error,
            "training_rows": self.model_version.training_rows,
        }
