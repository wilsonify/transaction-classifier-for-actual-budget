"""
Classify all transactions in tests/transactions/from-actual/All-Accounts.csv
and write results to tests/transactions/from-actual/All-Accounts-classified.csv
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

# Allow running as: python tests/classify_all_accounts.py from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from actualbudget_transaction_classifier.api import ClassifierAPI

INPUT = Path(__file__).parent / "transactions" / "from-actual" / "All-Accounts.csv"
OUTPUT = Path(__file__).parent / "transactions" / "from-actual" / "All-Accounts-classified.csv"

OUTPUT_FIELDS = [
    "Account",
    "Date",
    "Payee",
    "Notes",
    "Category_Group",
    "Category",
    "Amount",
    "Split_Amount",
    "Cleared",
    # classifier outputs
    "classified_category",
    "coarse_category",
    "confidence",
    "source",
    "auto_apply",
    "review_required",
    "review_flag",
    "review_reason",
    "hierarchy_path",
]


def main() -> None:
    api = ClassifierAPI()

    rows_in = 0
    rows_out = 0
    errors = 0

    with INPUT.open(newline="", encoding="utf-8") as f_in, \
         OUTPUT.open("w", newline="", encoding="utf-8") as f_out:

        reader = csv.DictReader(f_in)
        writer = csv.DictWriter(f_out, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()

        for i, row in enumerate(reader):
            rows_in += 1
            transaction_id = f"row_{i:04d}"
            payee = row.get("Payee", "").strip()
            amount_str = row.get("Amount", "0").strip()
            date = row.get("Date", "").strip()
            account = row.get("Account", "default").strip()

            try:
                amount = float(amount_str) if amount_str else 0.0
            except ValueError:
                amount = 0.0

            payload = json.dumps({
                "transaction_id": transaction_id,
                "merchant": payee,
                "amount": amount,
                "date": date,
                "account": account,
                "notes": row.get("Notes", "").strip(),
            })

            status, body = api.handle_request("POST", "/classify", payload)

            out_row = dict(row)
            if status == 200:
                out_row["classified_category"] = body.get("category", "")
                out_row["coarse_category"] = body.get("coarse_category", "")
                out_row["confidence"] = body.get("confidence", "")
                out_row["source"] = body.get("source", "")
                out_row["auto_apply"] = body.get("auto_apply", "")
                out_row["review_required"] = body.get("review_required", "")
                out_row["review_flag"] = body.get("review_flag", "")
                out_row["review_reason"] = body.get("review_reason", "")
                out_row["hierarchy_path"] = " > ".join(body.get("hierarchy_path", []))
                rows_out += 1
            else:
                out_row["classified_category"] = f"ERROR:{status}"
                out_row["coarse_category"] = ""
                out_row["confidence"] = ""
                out_row["source"] = ""
                out_row["auto_apply"] = ""
                out_row["review_required"] = ""
                out_row["review_flag"] = ""
                out_row["review_reason"] = ""
                out_row["hierarchy_path"] = ""
                errors += 1

            writer.writerow(out_row)

    print(f"Input rows:  {rows_in}")
    print(f"Classified:  {rows_out}")
    print(f"Errors:      {errors}")
    print(f"Output:      {OUTPUT}")


if __name__ == "__main__":
    main()
