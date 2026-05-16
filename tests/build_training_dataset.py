"""
Build a recency-aware training dataset from Monarch exports.

Why this exists:
- Older Monarch snapshots may contain stale/misclassified labels.
- Newer snapshots include corrected labels.
- Future inference input uses the ActualBudget transaction schema.

Output:
- tests/transactions/from-actual/All-Accounts-training.csv
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path


MONARCH_DIR = Path(__file__).parent / "transactions" / "from-monarch"
OUTPUT_FILE = Path(__file__).parent / "transactions" / "from-actual" / "All-Accounts-training.csv"

ACTUAL_OUTPUT_FIELDS = [
    "Account",
    "Date",
    "Payee",
    "Notes",
    "Category_Group",
    "Category",
    "Amount",
    "Split_Amount",
    "Cleared",
    # training metadata
    "Monarch_Category",
    "Training_Weight",
    "Snapshot_Timestamp",
    "Source_File",
    "Transaction_Key",
]


MONARCH_TO_PLUGIN_CATEGORY = {
    "auto maintenance": "auto_maintenance",
    "cash & atm": "transfers",
    "clothing": "shopping",
    "coffee shops": "coffee_shops",
    "credit card payment": "transfers",
    "electronics": "shopping",
    "entertainment & recreation": "entertainment_recreation",
    "financial & legal services": "office_supplies",
    "fitness": "fitness",
    "gas": "gas",
    "gas & electric": "cable_internet",
    "gifts": "shopping",
    "groceries": "groceries",
    "home improvement": "home_maintenance",
    "interest": "interest",
    "internet & cable": "cable_internet",
    "medical": "pharmacy",
    "mortgage": "transfers",
    "office supplies & expenses": "office_supplies",
    "other income": "paychecks",
    "parking & tolls": "parking_tolls",
    "paychecks": "paychecks",
    "personal": "misc",
    "phone": "phone",
    "public transit": "public_transit",
    "restaurants & bars": "dining_out",
    "shopping": "shopping",
    "transfer": "transfers",
    "travel & vacation": "entertainment_recreation",
    "water": "water",
    "garbage": "garbage",
}


PLUGIN_TO_COARSE = {
    "groceries": "Food",
    "coffee_shops": "Food",
    "dining_out": "Food",
    "gas": "Transport",
    "parking": "Transport",
    "parking_tolls": "Transport",
    "public_transit": "Transport",
    "rideshare": "Transport",
    "car_rental": "Transport",
    "auto_maintenance": "Transport",
    "phone": "Utilities",
    "garbage": "Utilities",
    "cable_internet": "Utilities",
    "water": "Utilities",
    "fitness": "Lifestyle",
    "entertainment_recreation": "Entertainment",
    "shopping": "Shopping",
    "pharmacy": "Health",
    "office_supplies": "Business",
    "paychecks": "Income",
    "investments": "Financial",
    "interest": "Financial",
    "transfers": "Financial",
    "taxes": "Financial",
    "home_maintenance": "Home",
    "misc": "Uncategorized",
}


SNAPSHOT_RE = re.compile(r"Transactions_(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})\.csv$")


def parse_snapshot_timestamp(path: Path) -> datetime:
    match = SNAPSHOT_RE.search(path.name)
    if not match:
        raise ValueError(f"Unexpected Monarch filename: {path.name}")
    return datetime.strptime(match.group(1), "%Y-%m-%dT%H-%M-%S")


def normalize_category(monarch_category: str) -> str:
    lowered = monarch_category.strip().lower()
    if lowered in MONARCH_TO_PLUGIN_CATEGORY:
        return MONARCH_TO_PLUGIN_CATEGORY[lowered]
    # Safe fallback for unseen category labels.
    return "misc"


def coarse_category(plugin_category: str) -> str:
    return PLUGIN_TO_COARSE.get(plugin_category, "Uncategorized")


def normalize_amount(amount: str) -> str:
    amount = amount.strip()
    if not amount:
        return "0"
    try:
        return f"{float(amount):.2f}"
    except ValueError:
        return amount


def transaction_key(row: dict[str, str]) -> str:
    date = row.get("Date", "").strip()
    account = row.get("Account", "").strip().lower()
    statement = row.get("Original Statement", "").strip().lower()
    if not statement:
        statement = row.get("Merchant", "").strip().lower()
    amount = normalize_amount(row.get("Amount", "0"))
    return f"{date}|{account}|{statement}|{amount}"


def combined_notes(row: dict[str, str]) -> str:
    statement = row.get("Original Statement", "").strip()
    notes = row.get("Notes", "").strip()
    if statement and notes:
        return f"{statement} | {notes}"
    return statement or notes


def build_dataset() -> None:
    files = sorted(MONARCH_DIR.glob("Transactions_*.csv"), key=parse_snapshot_timestamp)
    if not files:
        raise FileNotFoundError(f"No Monarch files found in {MONARCH_DIR}")

    first_ts = parse_snapshot_timestamp(files[0])
    last_ts = parse_snapshot_timestamp(files[-1])
    span_seconds = max((last_ts - first_ts).total_seconds(), 1.0)

    latest_by_key: dict[str, tuple[datetime, Path, dict[str, str]]] = {}
    category_history: dict[str, list[tuple[datetime, str]]] = defaultdict(list)

    read_rows = 0
    skipped_unlabeled = 0

    for file_path in files:
        snapshot_ts = parse_snapshot_timestamp(file_path)
        with file_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                read_rows += 1
                raw_category = row.get("Category", "").strip()
                if not raw_category:
                    skipped_unlabeled += 1
                    continue

                key = transaction_key(row)
                category_history[key].append((snapshot_ts, raw_category))

                prior = latest_by_key.get(key)
                if prior is None or snapshot_ts >= prior[0]:
                    latest_by_key[key] = (snapshot_ts, file_path, row)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    corrected_count = 0
    with OUTPUT_FILE.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ACTUAL_OUTPUT_FIELDS)
        writer.writeheader()

        for key, (snapshot_ts, file_path, row) in sorted(latest_by_key.items(), key=lambda item: item[1][2].get("Date", ""), reverse=True):
            history = sorted(category_history[key], key=lambda item: item[0])
            if len({category for _, category in history}) > 1 and history[-1][1] != history[0][1]:
                corrected_count += 1

            monarch_category = row.get("Category", "").strip()
            plugin_category = normalize_category(monarch_category)
            coarse = coarse_category(plugin_category)

            recency = (snapshot_ts - first_ts).total_seconds() / span_seconds
            training_weight = 1.0 + recency

            out_row = {
                "Account": row.get("Account", "").strip(),
                "Date": row.get("Date", "").strip(),
                "Payee": row.get("Merchant", "").strip(),
                "Notes": combined_notes(row),
                "Category_Group": coarse,
                "Category": plugin_category,
                "Amount": normalize_amount(row.get("Amount", "0")),
                "Split_Amount": "0",
                "Cleared": "Cleared",
                "Monarch_Category": monarch_category,
                "Training_Weight": f"{training_weight:.4f}",
                "Snapshot_Timestamp": snapshot_ts.isoformat(),
                "Source_File": file_path.name,
                "Transaction_Key": key,
            }
            writer.writerow(out_row)

    print(f"Monarch files read:         {len(files)}")
    print(f"Rows read:                  {read_rows}")
    print(f"Rows skipped (no category): {skipped_unlabeled}")
    print(f"Unique labeled txns:        {len(latest_by_key)}")
    print(f"Detected corrected labels:  {corrected_count}")
    print(f"Training dataset written:   {OUTPUT_FILE}")


if __name__ == "__main__":
    build_dataset()