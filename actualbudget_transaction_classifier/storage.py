from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import (
    ClassificationHistoryEntry,
    ClassificationResult,
    MerchantRegistryEntry,
    ModelVersion,
    ReviewQueueEntry,
    TransactionPayload,
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PluginRepository:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS classifications (
                    transaction_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    corrected_category TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS review_queue (
                    transaction_id TEXT PRIMARY KEY,
                    reason TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    predicted_category TEXT NOT NULL,
                    explanations_json TEXT NOT NULL,
                    suggested_alternatives_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    resolved_category TEXT,
                    resolution_note TEXT,
                    resolved_at TEXT
                );

                CREATE TABLE IF NOT EXISTS merchant_intelligence (
                    canonical_name TEXT PRIMARY KEY,
                    aliases_json TEXT NOT NULL,
                    default_category TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    updated_at TEXT NOT NULL,
                    transaction_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS merchant_category_counts (
                    canonical_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    count INTEGER NOT NULL,
                    PRIMARY KEY (canonical_name, category)
                );

                CREATE TABLE IF NOT EXISTS model_versions (
                    model_version TEXT PRIMARY KEY,
                    taxonomy_version TEXT NOT NULL,
                    training_date TEXT NOT NULL,
                    macro_f1 REAL NOT NULL,
                    calibration_error REAL NOT NULL,
                    training_rows INTEGER NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS retrain_jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    corrected_rows INTEGER,
                    output_model_version TEXT,
                    error_message TEXT
                );
                """
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _ensure_default_model(self, model: ModelVersion) -> None:
        row = self._conn.execute("SELECT model_version FROM model_versions WHERE is_active = 1").fetchone()
        if row:
            return
        now = utc_now_iso()
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO model_versions (
                    model_version, taxonomy_version, training_date, macro_f1,
                    calibration_error, training_rows, is_active, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    model.model_version,
                    model.taxonomy_version,
                    model.training_date,
                    model.macro_f1,
                    model.calibration_error,
                    model.training_rows,
                    json.dumps({"source": "bootstrap"}),
                    now,
                ),
            )

    def load_state(self, default_model: ModelVersion) -> Dict[str, Any]:
        with self._lock:
            self._ensure_default_model(default_model)

            merchants: Dict[str, MerchantRegistryEntry] = {}
            merchant_rows = self._conn.execute(
                "SELECT canonical_name, aliases_json, default_category, confidence, updated_at, transaction_count FROM merchant_intelligence"
            ).fetchall()
            for row in merchant_rows:
                merchants[row["canonical_name"]] = MerchantRegistryEntry(
                    canonical_name=row["canonical_name"],
                    aliases=json.loads(row["aliases_json"]),
                    default_category=row["default_category"],
                    confidence=float(row["confidence"]),
                    updated_at=row["updated_at"],
                    transaction_count=int(row["transaction_count"]),
                )

            history: Dict[str, ClassificationHistoryEntry] = {}
            classification_cache: Dict[str, ClassificationResult] = {}
            class_rows = self._conn.execute(
                "SELECT transaction_id, result_json, corrected_category FROM classifications"
            ).fetchall()
            for row in class_rows:
                result_dict = json.loads(row["result_json"])
                result = ClassificationResult(**result_dict)
                classification_cache[row["transaction_id"]] = result
                history[row["transaction_id"]] = ClassificationHistoryEntry(
                    transaction_id=row["transaction_id"],
                    predicted_category=result.category,
                    corrected_category=row["corrected_category"],
                    confidence=result.confidence,
                    explanation="; ".join(result.explanations),
                    corrected=row["corrected_category"] is not None,
                )

            review_queue: Dict[str, ReviewQueueEntry] = {}
            review_rows = self._conn.execute(
                """
                SELECT transaction_id, reason, confidence, predicted_category,
                       explanations_json, suggested_alternatives_json, created_at
                FROM review_queue
                WHERE status = 'open'
                """
            ).fetchall()
            for row in review_rows:
                review_queue[row["transaction_id"]] = ReviewQueueEntry(
                    transaction_id=row["transaction_id"],
                    reason=row["reason"],
                    confidence=float(row["confidence"]),
                    predicted_category=row["predicted_category"],
                    explanations=json.loads(row["explanations_json"]),
                    suggested_alternatives=json.loads(row["suggested_alternatives_json"]),
                    created_at=row["created_at"],
                )

            counts: Dict[str, Dict[str, int]] = {}
            count_rows = self._conn.execute(
                "SELECT canonical_name, category, count FROM merchant_category_counts"
            ).fetchall()
            for row in count_rows:
                counts.setdefault(row["canonical_name"], {})[row["category"]] = int(row["count"])

            active_row = self._conn.execute(
                """
                SELECT model_version, taxonomy_version, training_date, macro_f1, calibration_error, training_rows
                FROM model_versions
                WHERE is_active = 1
                LIMIT 1
                """
            ).fetchone()
            model = default_model
            if active_row:
                model = ModelVersion(
                    model_version=active_row["model_version"],
                    taxonomy_version=active_row["taxonomy_version"],
                    training_date=active_row["training_date"],
                    macro_f1=float(active_row["macro_f1"]),
                    calibration_error=float(active_row["calibration_error"]),
                    training_rows=int(active_row["training_rows"]),
                )

            return {
                "merchant_registry": merchants,
                "classification_history": history,
                "classification_cache": classification_cache,
                "review_queue": review_queue,
                "merchant_category_counts": counts,
                "active_model": model,
            }

    def save_classification(self, payload: TransactionPayload, result: ClassificationResult) -> None:
        now = utc_now_iso()
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO classifications (transaction_id, payload_json, result_json, corrected_category, created_at, updated_at)
                    VALUES (?, ?, ?, NULL, ?, ?)
                    ON CONFLICT(transaction_id) DO UPDATE SET
                        payload_json = excluded.payload_json,
                        result_json = excluded.result_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        payload.transaction_id,
                        json.dumps(asdict(payload)),
                        json.dumps(asdict(result)),
                        now,
                        now,
                    ),
                )

    def save_review_item(self, item: ReviewQueueEntry) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO review_queue (
                        transaction_id, reason, confidence, predicted_category,
                        explanations_json, suggested_alternatives_json, created_at, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open')
                    ON CONFLICT(transaction_id) DO UPDATE SET
                        reason = excluded.reason,
                        confidence = excluded.confidence,
                        predicted_category = excluded.predicted_category,
                        explanations_json = excluded.explanations_json,
                        suggested_alternatives_json = excluded.suggested_alternatives_json,
                        created_at = excluded.created_at,
                        status = 'open',
                        resolved_category = NULL,
                        resolution_note = NULL,
                        resolved_at = NULL
                    """,
                    (
                        item.transaction_id,
                        item.reason,
                        item.confidence,
                        item.predicted_category,
                        json.dumps(item.explanations),
                        json.dumps(item.suggested_alternatives),
                        item.created_at,
                    ),
                )

    def remove_review_item(self, transaction_id: str) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "UPDATE review_queue SET status = 'resolved', resolved_at = ? WHERE transaction_id = ?",
                    (utc_now_iso(), transaction_id),
                )

    def list_open_review_queue(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT transaction_id, reason, confidence, predicted_category,
                       explanations_json, suggested_alternatives_json, created_at
                FROM review_queue
                WHERE status = 'open'
                ORDER BY created_at ASC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [
            {
                "transaction_id": row["transaction_id"],
                "reason": row["reason"],
                "confidence": float(row["confidence"]),
                "predicted_category": row["predicted_category"],
                "explanations": json.loads(row["explanations_json"]),
                "suggested_alternatives": json.loads(row["suggested_alternatives_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def resolve_review_item(self, transaction_id: str, corrected_category: str, note: str = "") -> bool:
        now = utc_now_iso()
        with self._lock:
            with self._conn:
                result = self._conn.execute(
                    """
                    UPDATE review_queue
                    SET status = 'resolved', resolved_category = ?, resolution_note = ?, resolved_at = ?
                    WHERE transaction_id = ?
                    """,
                    (corrected_category, note, now, transaction_id),
                )
                self._conn.execute(
                    """
                    UPDATE classifications
                    SET corrected_category = ?, updated_at = ?
                    WHERE transaction_id = ?
                    """,
                    (corrected_category, now, transaction_id),
                )
        return result.rowcount > 0

    def upsert_merchant_intelligence(self, merchant: MerchantRegistryEntry) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO merchant_intelligence (
                        canonical_name, aliases_json, default_category, confidence, updated_at, transaction_count
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(canonical_name) DO UPDATE SET
                        aliases_json = excluded.aliases_json,
                        default_category = excluded.default_category,
                        confidence = excluded.confidence,
                        updated_at = excluded.updated_at,
                        transaction_count = excluded.transaction_count
                    """,
                    (
                        merchant.canonical_name,
                        json.dumps(merchant.aliases),
                        merchant.default_category,
                        merchant.confidence,
                        merchant.updated_at,
                        merchant.transaction_count,
                    ),
                )

    def upsert_merchant_category_count(self, canonical_name: str, category: str, count: int) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO merchant_category_counts (canonical_name, category, count)
                    VALUES (?, ?, ?)
                    ON CONFLICT(canonical_name, category) DO UPDATE SET count = excluded.count
                    """,
                    (canonical_name, category, count),
                )

    def enqueue_retrain_job(self, requested_by: str = "system") -> Dict[str, Any]:
        job_id = str(uuid.uuid4())
        now = utc_now_iso()
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO retrain_jobs (job_id, status, requested_by, requested_at)
                    VALUES (?, 'queued', ?, ?)
                    """,
                    (job_id, requested_by, now),
                )
        return {
            "job_id": job_id,
            "status": "queued",
            "requested_by": requested_by,
            "requested_at": now,
        }

    def list_retrain_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT job_id, status, requested_by, requested_at, started_at, completed_at,
                       corrected_rows, output_model_version, error_message
                FROM retrain_jobs
                ORDER BY requested_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_retrain_job_running(self, job_id: str) -> bool:
        with self._lock:
            with self._conn:
                result = self._conn.execute(
                    "UPDATE retrain_jobs SET status = 'running', started_at = ? WHERE job_id = ?",
                    (utc_now_iso(), job_id),
                )
        return result.rowcount > 0

    def mark_retrain_job_complete(self, job_id: str, corrected_rows: int, output_model_version: str) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    UPDATE retrain_jobs
                    SET status = 'completed', completed_at = ?, corrected_rows = ?, output_model_version = ?
                    WHERE job_id = ?
                    """,
                    (utc_now_iso(), corrected_rows, output_model_version, job_id),
                )

    def mark_retrain_job_failed(self, job_id: str, error_message: str) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    UPDATE retrain_jobs
                    SET status = 'failed', completed_at = ?, error_message = ?
                    WHERE job_id = ?
                    """,
                    (utc_now_iso(), error_message[:512], job_id),
                )

    def list_model_versions(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT model_version, taxonomy_version, training_date, macro_f1,
                       calibration_error, training_rows, is_active, metadata_json, created_at
                FROM model_versions
                ORDER BY created_at DESC
                """
            ).fetchall()
        versions: List[Dict[str, Any]] = []
        for row in rows:
            body = dict(row)
            body["is_active"] = bool(body["is_active"])
            body["metadata"] = json.loads(body.pop("metadata_json"))
            versions.append(body)
        return versions

    def create_model_version(self, model: ModelVersion, metadata: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO model_versions (
                        model_version, taxonomy_version, training_date, macro_f1,
                        calibration_error, training_rows, is_active, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        model.model_version,
                        model.taxonomy_version,
                        model.training_date,
                        model.macro_f1,
                        model.calibration_error,
                        model.training_rows,
                        json.dumps(metadata or {}),
                        utc_now_iso(),
                    ),
                )

    def activate_model_version(self, model_version: str) -> bool:
        with self._lock:
            with self._conn:
                found = self._conn.execute(
                    "SELECT model_version FROM model_versions WHERE model_version = ?",
                    (model_version,),
                ).fetchone()
                if not found:
                    return False
                self._conn.execute("UPDATE model_versions SET is_active = 0")
                self._conn.execute(
                    "UPDATE model_versions SET is_active = 1 WHERE model_version = ?",
                    (model_version,),
                )
        return True
