# transaction-classifier-for-actual-budget

`actualbudget_transaction_classifier` is an offline-first transaction classification plugin scaffold for ActualBudget.

## Implemented capabilities

- Merchant normalization with canonicalization traces
- Deterministic merchant rules with priority evaluation
- Historical user behavior fallback
- Hierarchical ML-style inference fallback
- Confidence calibration and review queue routing
- Feedback and retraining hooks
- Explainability metadata on every prediction
- Required API surface:
  - `POST /classify`
  - `POST /feedback`
  - `POST /retrain`
  - `GET /health`
  - `GET /metrics`
  - `GET /model/version`

## Quick usage

```python
from actualbudget_transaction_classifier import ClassifierAPI

api = ClassifierAPI()
status, body = api.handle_request(
    "POST",
    "/classify",
    '{"transaction_id":"txn_123","merchant":"Wegmans #078","amount":-83.60,"date":"2024-05-10"}'
)
```

## Testing

```bash
python -m unittest discover -s tests -v
```

## Build training data from Monarch exports

Use Monarch snapshots in `tests/transactions/from-monarch` to create a training dataset aligned to the Actual transaction schema.

```bash
python tests/build_training_dataset.py
```

This script:
- deduplicates transactions across snapshots,
- keeps the newest snapshot label for each transaction,
- maps Monarch categories into plugin categories,
- writes `tests/transactions/from-actual/All-Accounts-training.csv`.
