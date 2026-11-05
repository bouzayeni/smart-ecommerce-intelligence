"""Typed access to config/ml.yaml, with checks that the snapshot splits cannot leak."""

from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

from data_engineering.config import PROJECT_ROOT

ML_CONFIG_PATH = PROJECT_ROOT / "config" / "ml.yaml"


class Snapshots(BaseModel):
    train: list[date] = Field(min_length=1)
    validation: date
    test: date
    scoring: date


class FeatureConfig(BaseModel):
    top_states: int = Field(ge=1)
    top_categories: int = Field(ge=1)


class Segment(BaseModel):
    name: str
    r_min: int = 1
    r_max: int = 5
    f_min: int = 1
    f_max: int = 5
    m_min: int = 1
    m_max: int = 5

    def matches(self, r: int, f: int, m: int) -> bool:
        return (
            self.r_min <= r <= self.r_max
            and self.f_min <= f <= self.f_max
            and self.m_min <= m <= self.m_max
        )


class RfmConfig(BaseModel):
    reference_date: date
    frequency_scores: dict[int, int]
    segments: list[Segment]


class RiskBands(BaseModel):
    """Inclusive propensity-decile ranges per churn-risk band."""

    high: tuple[int, int]
    medium: tuple[int, int]
    low: tuple[int, int]

    def band(self, decile: int) -> str:
        for name in ("high", "medium", "low"):
            lo, hi = getattr(self, name)
            if lo <= decile <= hi:
                return name
        raise ValueError(f"decile {decile} not covered by risk_bands")


class RepurchaseConfig(BaseModel):
    risk_bands: RiskBands
    models: dict[str, dict[str, list[Any]]]


class ClvConfig(BaseModel):
    models: dict[str, dict[str, list[Any]]]


class MLConfig(BaseModel):
    random_state: int
    horizon_days: int = Field(gt=0)
    snapshots: Snapshots
    features: FeatureConfig
    rfm: RfmConfig
    repurchase: RepurchaseConfig
    clv: ClvConfig

    @property
    def horizon(self) -> timedelta:
        return timedelta(days=self.horizon_days)

    @model_validator(mode="after")
    def splits_do_not_overlap(self) -> "MLConfig":
        s, h = self.snapshots, self.horizon
        if max(s.train) + h > s.validation:
            raise ValueError("latest train cutoff + horizon must be <= validation cutoff")
        if s.validation + h > s.test:
            raise ValueError("validation cutoff + horizon must be <= test cutoff")
        if s.test >= s.scoring:
            raise ValueError("scoring cutoff must be after the test cutoff")
        return self


def load_ml_config(path: Path = ML_CONFIG_PATH) -> MLConfig:
    return MLConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def get_ml_config() -> MLConfig:
    return load_ml_config()
