from __future__ import annotations
import uvicorn
import os

from .service import create_fastapi_app

app = create_fastapi_app()

def main() -> None:
    host = os.getenv("ACTUAL_CLASSIFIER_HOST", "0.0.0.0")
    port = int(os.getenv("ACTUAL_CLASSIFIER_PORT", "8080"))
    workers = int(os.getenv("ACTUAL_CLASSIFIER_WORKERS", "1"))
    uvicorn.run("actualbudget_transaction_classifier.main:app", host=host, port=port, workers=workers)


if __name__ == "__main__":
    main()
