"""Feature payload for on-demand customer predictions. Must match the training features in
ml/customer/features.py (tests/test_api_contract.py checks this)."""

from pydantic import BaseModel, ConfigDict, Field

NUMERIC_FEATURES = [
    "recency_days",
    "tenure_days",
    "frequency",
    "monetary",
    "avg_order_value",
    "max_order_value",
    "last_order_value",
    "avg_items_per_order",
    "freight_share",
    "mean_installments",
    "mean_days_between_orders",
    "orders_last_90d",
    "orders_last_180d",
    "n_delivered",
    "avg_delivery_days",
    "late_share",
    "last_order_delivered",
    "n_reviews",
    "mean_review_score",
    "min_review_score",
    "last_review_score",
    "n_categories",
]
CATEGORICAL_FEATURES = ["last_payment_type", "customer_state", "last_order_category"]


class CustomerFeatures(BaseModel):
    """What-if inputs. Optional fields mean "unknown" and are imputed like in training."""

    model_config = ConfigDict(extra="forbid")

    recency_days: float = Field(ge=0, le=5000)
    tenure_days: float = Field(ge=0, le=5000)
    frequency: float = Field(ge=1, le=1000)
    monetary: float = Field(ge=0, le=1_000_000)
    avg_order_value: float = Field(ge=0, le=1_000_000)
    max_order_value: float = Field(ge=0, le=1_000_000)
    last_order_value: float = Field(ge=0, le=1_000_000)
    avg_items_per_order: float = Field(1, ge=0, le=100)
    freight_share: float | None = Field(None, ge=0, le=1)
    mean_installments: float = Field(1, ge=0, le=24)
    mean_days_between_orders: float | None = Field(None, ge=0, le=5000)
    orders_last_90d: float = Field(0, ge=0, le=1000)
    orders_last_180d: float = Field(0, ge=0, le=1000)
    n_delivered: float = Field(1, ge=0, le=1000)
    avg_delivery_days: float | None = Field(None, ge=0, le=365)
    late_share: float | None = Field(None, ge=0, le=1)
    last_order_delivered: float = Field(1, ge=0, le=1)
    n_reviews: float = Field(1, ge=0, le=1000)
    mean_review_score: float | None = Field(None, ge=1, le=5)
    min_review_score: float | None = Field(None, ge=1, le=5)
    last_review_score: float | None = Field(None, ge=1, le=5)
    n_categories: float = Field(1, ge=0, le=100)
    last_payment_type: str = Field("credit_card", max_length=40)
    customer_state: str = Field("SP", pattern=r"^[A-Z]{2}$")
    last_order_category: str = Field("unknown", max_length=80)


class PredictionRequest(BaseModel):
    """Either a known customer (stored batch score) or a feature payload (on-demand)."""

    model_config = ConfigDict(extra="forbid")

    customer_unique_id: str | None = Field(None, pattern=r"^[0-9a-f]{32}$")
    features: CustomerFeatures | None = None
