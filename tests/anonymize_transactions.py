"""Anonymize all CSV fixtures under tests/transactions in place."""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).parent / "transactions"
DATE_SHIFT_DAYS = -731
COL_DATE = "Date"
COL_SNAPSHOT_TIMESTAMP = "Snapshot_Timestamp"
COL_ACCOUNT = "Account"
COL_OWNER = "Owner"
COL_MERCHANT = "Merchant"
COL_PAYEE = "Payee"
COL_ORIGINAL_STATEMENT = "Original Statement"
COL_NOTES = "Notes"
COL_SOURCE_FILE = "Source_File"
COL_TRANSACTION_KEY = "Transaction_Key"


def _token(value: str, prefix: str, width: int = 10) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest().upper()
    return f"{prefix}_{digest[:width]}"


def _shift_date(value: str) -> str:
    value = value.strip()
    if not value:
        return value
    try:
        dt = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return value
    return (dt + timedelta(days=DATE_SHIFT_DAYS)).strftime("%Y-%m-%d")


def _shift_iso_timestamp(value: str) -> str:
    value = value.strip()
    if not value:
        return value
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    return (dt + timedelta(days=DATE_SHIFT_DAYS)).isoformat(timespec="seconds")


def _apply_token(out: dict[str, str], column: str, prefix: str) -> None:
    value = out.get(column, "").strip()
    if value:
        out[column] = _token(value.lower(), prefix)


def _anonymize_row(row: dict[str, str]) -> dict[str, str]:
    out = dict(row)

    if COL_DATE in out:
        out[COL_DATE] = _shift_date(out[COL_DATE])

    if COL_SNAPSHOT_TIMESTAMP in out:
        out[COL_SNAPSHOT_TIMESTAMP] = _shift_iso_timestamp(out[COL_SNAPSHOT_TIMESTAMP])

    token_columns = [
        (COL_ACCOUNT, "ACCOUNT"),
        (COL_OWNER, "OWNER"),
        (COL_MERCHANT, "MERCHANT"),
        (COL_PAYEE, "MERCHANT"),
        (COL_ORIGINAL_STATEMENT, "DESC"),
        (COL_NOTES, "NOTE"),
        (COL_TRANSACTION_KEY, "TXN"),
    ]
    for column, prefix in token_columns:
        if column in out:
            _apply_token(out, column, prefix)

    source_file = out.get(COL_SOURCE_FILE, "").strip()
    if source_file:
        out[COL_SOURCE_FILE] = _token(source_file.lower(), "SNAPSHOT") + ".csv"

    return out


def anonymize_file(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        if not fields:
            return 0
        rows = [_anonymize_row(row) for row in reader]

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    return len(rows)


def main() -> None:
    csv_paths = sorted(ROOT.rglob("*.csv"))
    if not csv_paths:
        print(f"No CSV files found under {ROOT}")
        return

    total_files = 0
    total_rows = 0
    for path in csv_paths:
        rows = anonymize_file(path)
        total_files += 1
        total_rows += rows
        print(f"Anonymized {path}: {rows} rows")

    print(f"Done. Files: {total_files}, Rows: {total_rows}")


if __name__ == "__main__":
    main()