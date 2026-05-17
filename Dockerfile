FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system classifier && adduser --system --ingroup classifier classifier

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY actualbudget_transaction_classifier ./actualbudget_transaction_classifier

ENV ACTUAL_CLASSIFIER_DB_PATH=/data/classifier.db \
    ACTUAL_CLASSIFIER_HOST=0.0.0.0 \
    ACTUAL_CLASSIFIER_PORT=8080 \
    ACTUAL_CLASSIFIER_WORKERS=1

RUN mkdir -p /data && chown -R classifier:classifier /data /app

USER classifier

EXPOSE 8080

CMD ["python", "-m", "actualbudget_transaction_classifier.main"]
