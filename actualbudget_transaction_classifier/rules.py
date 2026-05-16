DEFAULT_RULES.extend([
    {
        "name": "large_walmart_not_groceries",
        "priority": 100,
        "when": {"merchant_equals": "walmart", "amount_bucket": "large"},
        "then": {"category": "shopping", "note": "Walmart large spend likely not groceries"},
    },
    {
        "name": "small_dunkin_coffee",
        "priority": 95,
        "when": {"merchant_equals": "dunkin", "amount_lt": 10},
        "then": {"category": "coffee shops", "note": "Dunkin under $10 mapped to coffee"},
    },
    {
        "name": "paycheck_pattern",
        "priority": 98,
        "when": {"merchant_in_paycheck_sources": True, "payday_pattern": True},
        "then": {"category": "paychecks", "force_flow": "spending_income", "note": "Biweekly paycheck pattern detected"},
    },
])