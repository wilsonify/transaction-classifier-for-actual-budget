def to_model_features(record: dict[str, Any]) -> dict[str, Any]:
    model_features = {
        "amount_abs": max(float(record.get("amount", 0.0)), 0.0),
        "amount_bucket": str(record.get("amount_bucket", "small")),
        "day_of_week": str(record.get("day_of_week", "unknown")),
        "is_weekend": int(record.get("is_weekend", 0)),
        "merchant_frequency": int(record.get("merchant_frequency", 0)),
        "amount_zscore": min(abs(float(record.get("amount_zscore", 0.0))), 4.0),
        "payday_pattern": int(record.get("payday_pattern", 0)),
        "is_positive_amount": 1 if float(record.get("amount", 0.0)) > 0 else 0,
    }
    return model_features