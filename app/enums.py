from .models import Intent

ALLOWED_BILLING_ISSUE_TYPES = frozenset(
    {
        "charge_dispute",
        "payment_failure",
        "subscription_change",
        "refund_request",
        "invoice_question",
        "other",
    }
)

ALLOWED_TECHNICAL_ISSUE_TYPES = frozenset(
    {
        "login",
        "outage",
        "feature_not_working",
        "performance",
        "data_loss",
        "other",
    }
)

ALLOWED_ACCOUNT_CHANGE_TYPES = frozenset(
    {
        "email",
        "password",
        "plan",
        "payment_method",
        "personal_info",
        "other",
    }
)

ALLOWED_CANCELLATION_REASONS = frozenset(
    {
        "price",
        "not_using",
        "missing_feature",
        "switching_competitor",
        "temporary",
        "other",
    }
)

INTENT_REQUIRED_FIELD = {
    Intent.BILLING: "billing_issue_type",
    Intent.TECHNICAL: "technical_issue_type",
    Intent.ACCOUNT_CHANGE: "account_change_type",
    Intent.CANCELLATION: "cancellation_reason",
}

ALLOWED_INTENT_SPECIFIC_VALUES = {
    "billing_issue_type": ALLOWED_BILLING_ISSUE_TYPES,
    "technical_issue_type": ALLOWED_TECHNICAL_ISSUE_TYPES,
    "account_change_type": ALLOWED_ACCOUNT_CHANGE_TYPES,
    "cancellation_reason": ALLOWED_CANCELLATION_REASONS,
}

PUBLIC_INTENTS = (
    Intent.BILLING,
    Intent.TECHNICAL,
    Intent.ACCOUNT_CHANGE,
    Intent.CANCELLATION,
    Intent.OTHER,
)
