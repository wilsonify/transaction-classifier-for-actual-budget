from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional


@dataclass(frozen=True)
class TransactionPayload:
    transaction_id: str
    merchant: str
    amount: float
    date: str
    account: str = "default"
    notes: str = ""


@dataclass
class ClassificationResult:
    transaction_id: str
    category: str
    confidence: float
    coarse_category: str
    flow: str
    source: str
    explanations: List[str]
    top_features: List[str]
    merchant_normalization_trace: List[str]
    rule_matches: List[str]
    model_probabilities: Dict[str, float]
    hierarchy_path: List[str]
    review_reason: Optional[str] = None
    review_required: bool = False
    review_flag: bool = False
    suggested_alternatives: List[str] = field(default_factory=list)


@dataclass
class MerchantRegistryEntry:
    canonical_name: str
    aliases: List[str]
    default_category: str
    confidence: float
    updated_at: str
    transaction_count: int = 0


@dataclass
class ClassificationHistoryEntry:
    transaction_id: str
    predicted_category: str
    corrected_category: Optional[str]
    confidence: float
    explanation: str
    corrected: bool


@dataclass
class ReviewQueueEntry:
    transaction_id: str
    reason: str
    confidence: float
    predicted_category: str
    explanations: List[str]
    suggested_alternatives: List[str]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ModelVersion:
    model_version: str = "2026.05.01"
    taxonomy_version: str = "v3"
    training_date: str = "2026-05-01"
    macro_f1: float = 0.93
    calibration_error: float = 0.04
    training_rows: int = 84231
