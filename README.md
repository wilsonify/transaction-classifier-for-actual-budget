# transaction-classifier-for-actual-budget

`actualbudget_transaction_classifier` is now a production-ready, local-only plugin service for ActualBudget with persistent intelligence, review queue APIs, model lifecycle controls, and Kubernetes/Helm deployment support.

## What is implemented

- Production HTTP service mode with FastAPI (`python -m actualbudget_transaction_classifier.main`)
- Persistent SQLite storage for:
  - merchant intelligence
  - classification history
  - user corrections
  - review queue state
  - model version registry
  - retraining jobs
- Automatic transaction classification entrypoint for import/sync events:
  - `POST /events/transactions/imported`
- Explainability and confidence retained on every prediction:
  - explanations
  - top features
  - probability distribution
  - review flags and reasons
- Review workflow APIs:
  - `GET /review-queue`
  - `POST /review-queue/resolve`
  - `POST /feedback`
- Model lifecycle APIs:
  - `GET /model/version`
  - `GET /model/versions`
  - `POST /model/versions`
  - `POST /model/activate`
- Retraining workflow APIs:
  - `POST /retrain` (queue)
  - `GET /retrain/jobs`
  - `POST /retrain/jobs/run`
- Cloud-native deployment assets:
  - container image (`Dockerfile`)
  - Helm chart (`deploy/helm/actualbudget-classifier`)
  - PVC-backed persistence
  - readiness/liveness probes
  - optional NetworkPolicy, HPA, PDB
  - retraining CronJob
  - optional ActualBudget sync-forwarder CronJob

## Local service run

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Run the API:

```bash
ACTUAL_CLASSIFIER_DB_PATH=./data/classifier.db python -m actualbudget_transaction_classifier.main
```

3. Health check:

```bash
curl http://localhost:8080/health
```

## API examples

Classify one transaction:

```bash
curl -X POST http://localhost:8080/classify \
  -H "Content-Type: application/json" \
  -d '{"transaction_id":"txn_123","merchant":"Wegmans #078","amount":-83.6,"date":"2026-05-17"}'
```

Classify imported/synced transaction batch:

```bash
curl -X POST http://localhost:8080/events/transactions/imported \
  -H "Content-Type: application/json" \
  -d '{
    "source":"sync",
    "batch_id":"sync-2026-05-17T03:00:00Z",
    "transactions":[
      {"transaction_id":"txn_1","merchant":"Sunoco 0099368300","amount":-41.20,"date":"2026-05-17"},
      {"transaction_id":"txn_2","merchant":"Random Vendor","amount":-11.40,"date":"2026-05-17"}
    ]
  }'
```

Queue and run retraining:

```bash
curl -X POST http://localhost:8080/retrain -H "Content-Type: application/json" -d '{"requested_by":"ops"}'
curl http://localhost:8080/retrain/jobs
curl -X POST http://localhost:8080/retrain/jobs/run -H "Content-Type: application/json" -d '{"job_id":"<job-id>"}'
```

## Helm deployment

Chart path:

- `deploy/helm/actualbudget-classifier`

Install example:

```bash
helm upgrade --install actualbudget-classifier ./deploy/helm/actualbudget-classifier \
  --namespace finance \
  --create-namespace \
  --set image.repository=ghcr.io/<your-org>/actualbudget-classifier \
  --set image.tag=1.0.0
```

## Integrating with an existing Helm-based ActualBudget deployment

Use one of these patterns:

1. Deploy classifier chart in same namespace and allow traffic from ActualBudget pods.
2. Enable `actualbudgetIntegration.enabled=true` and point `actualbudgetIntegration.eventFeedPath` to an endpoint in your ActualBudget stack that returns pending imported/synced transactions as JSON payload compatible with `POST /events/transactions/imported`.
3. Or call `POST /events/transactions/imported` directly from your existing ActualBudget sync/import workflow.

Recommended production values:

- `persistence.enabled=true`
- `networkPolicy.enabled=true`
- `podDisruptionBudget.enabled=true`
- `resources.requests/limits` tuned for your cluster
- `actualbudgetIntegration.enabled=true` only when your feed endpoint is in place

## Local-only Kubernetes posture

- Service type is `ClusterIP` by default.
- No ingress is created by default.
- NetworkPolicy can restrict access to in-cluster callers only.
- All data remains on PVC-backed local storage inside the cluster.

## Testing

```bash
python -m unittest discover -s tests -v
```

## Build training data from Monarch exports

```bash
python tests/build_training_dataset.py
```

This script:

- deduplicates transactions across snapshots,
- keeps the newest snapshot label for each transaction,
- maps Monarch categories into plugin categories,
- writes `tests/transactions/from-actual/All-Accounts-training.csv`.
