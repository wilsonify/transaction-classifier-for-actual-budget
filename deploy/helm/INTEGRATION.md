# ActualBudget Helm Integration Guide

This guide shows how to integrate the classifier service into an existing Helm-based ActualBudget deployment.

## 1) Deploy classifier service in-cluster

```bash
helm upgrade --install actualbudget-classifier ./deploy/helm/actualbudget-classifier \
  --namespace finance \
  --create-namespace \
  --set image.repository=ghcr.io/<your-org>/actualbudget-classifier \
  --set image.tag=1.0.0 \
  --set persistence.enabled=true \
  --set networkPolicy.enabled=true
```

## 2) Wire ActualBudget sync/import flow to classifier

The classifier expects this endpoint to be called after import/sync:

- `POST /events/transactions/imported`

Payload shape:

```json
{
  "source": "sync",
  "batch_id": "sync-2026-05-17T03:00:00Z",
  "transactions": [
    {
      "transaction_id": "txn_123",
      "merchant": "Wegmans #078",
      "amount": -83.60,
      "date": "2026-05-17",
      "account": "checking",
      "notes": "optional"
    }
  ]
}
```

## 3) Enable feed-forwarder CronJob (optional)

If your ActualBudget stack exposes an endpoint that returns pending imported transactions in the same payload format, enable:

- `actualbudgetIntegration.enabled=true`
- `actualbudgetIntegration.actualbudgetServiceUrl=http://<actualbudget-service>:<port>`
- `actualbudgetIntegration.eventFeedPath=/api/classifier/transactions/imported`

Example:

```bash
helm upgrade --install actualbudget-classifier ./deploy/helm/actualbudget-classifier \
  --namespace finance \
  --set actualbudgetIntegration.enabled=true \
  --set actualbudgetIntegration.actualbudgetServiceUrl=http://actualbudget:5006 \
  --set actualbudgetIntegration.eventFeedPath=/api/classifier/transactions/imported
```

## 4) Keep deployment local-only

- Keep service type as `ClusterIP`.
- Do not create ingress unless explicitly needed.
- Restrict access via NetworkPolicy to ActualBudget pods/namespaces.
- Persist state in PVC mounted at `/data`.

## 5) Model and review operations

- Review queue: `GET /review-queue`, `POST /review-queue/resolve`
- Retrain: `POST /retrain`, `GET /retrain/jobs`, `POST /retrain/jobs/run`
- Model lifecycle: `GET /model/versions`, `POST /model/versions`, `POST /model/activate`
