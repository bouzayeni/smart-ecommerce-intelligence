"""Typed access to config/business_rules.yaml."""

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from data_engineering.config import PROJECT_ROOT

RULES_PATH = PROJECT_ROOT / "config" / "business_rules.yaml"

ORDER_STATUSES = frozenset(
    {"delivered", "shipped", "canceled", "unavailable", "invoiced", "processing", "created",
     "approved"}
)  # fmt: skip


class TruncationDetection(BaseModel):
    min_ratio: float = Field(gt=0, le=1)
    baseline_days: int = Field(ge=7)
    min_baseline_orders: int = Field(ge=1)


class AnalysisWindow(BaseModel):
    start: date
    end_override: date | None = None
    truncation_detection: TruncationDetection


class Revenue(BaseModel):
    include_statuses: list[str]
    exclude_statuses: list[str]

    @model_validator(mode="after")
    def statuses_partition_all_known(self) -> "Revenue":
        inc, exc = set(self.include_statuses), set(self.exclude_statuses)
        if inc & exc:
            raise ValueError(f"statuses both included and excluded: {sorted(inc & exc)}")
        if inc | exc != ORDER_STATUSES:
            missing, unknown = ORDER_STATUSES - inc - exc, (inc | exc) - ORDER_STATUSES
            raise ValueError(
                f"include + exclude must cover exactly {sorted(ORDER_STATUSES)}; "
                f"missing {sorted(missing)}, unknown {sorted(unknown)}"
            )
        return self


class Payments(BaseModel):
    reconciliation_tolerance_brl: float = Field(ge=0)
    payment_type_map: dict[str, str]


class Reviews(BaseModel):
    per_order_score: Literal["latest_answer", "mean"]
    available_at: Literal["review_answer_timestamp", "review_creation_date"]


class Delivery(BaseModel):
    late_comparison: Literal["calendar_date", "timestamp"]
    cohort_maturity_days: int = Field(ge=0)


class BrazilBBox(BaseModel):
    lat_min: float
    lat_max: float
    lng_min: float
    lng_max: float


class Quality(BaseModel):
    shipping_limit_max_days_after_purchase: int = Field(gt=0)
    brazil_bbox: BrazilBBox


class Products(BaseModel):
    unknown_category: str
    extra_translations: dict[str, str]


class BusinessRules(BaseModel):
    customer_key: Literal["customer_unique_id"]
    analysis_window: AnalysisWindow
    revenue: Revenue
    payments: Payments
    reviews: Reviews
    delivery: Delivery
    quality: Quality
    products: Products


def load_rules(path: Path = RULES_PATH) -> BusinessRules:
    return BusinessRules.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def get_rules() -> BusinessRules:
    return load_rules()
