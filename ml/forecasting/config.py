"""Typed access to config/forecasting.yaml with chronological-split checks."""

from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

from data_engineering.config import PROJECT_ROOT

FORECAST_CONFIG_PATH = PROJECT_ROOT / "config" / "forecasting.yaml"


class Backtest(BaseModel):
    origins: list[date] = Field(min_length=1)


class Metrics(BaseModel):
    mape_min_actual_brl: float = Field(ge=0)
    interval_level: float = Field(gt=0, lt=1)


class AnomalyConfig(BaseModel):
    metrics: list[str]
    stl_period: int = Field(ge=2)
    stl_trend_days: int = Field(ge=3)
    min_orders_for_ratios: int = Field(ge=1)
    robust_z_threshold: float = Field(gt=0)
    isolation_forest: dict[str, Any]
    autoencoder: dict[str, Any]
    sustained_shift: dict[str, Any]

    @model_validator(mode="after")
    def trend_window_is_odd_and_longer_than_period(self) -> "AnomalyConfig":
        if self.stl_trend_days % 2 == 0 or self.stl_trend_days <= self.stl_period:
            raise ValueError("stl_trend_days must be odd and longer than stl_period")
        return self


class ForecastConfig(BaseModel):
    random_state: int
    target: str
    horizons: list[int]
    max_horizon: int
    backtest: Backtest
    test_origin: date
    metrics: Metrics
    models: dict[str, dict[str, Any]]
    anomalies: AnomalyConfig

    @model_validator(mode="after")
    def splits_are_chronological(self) -> "ForecastConfig":
        h = timedelta(days=self.max_horizon)
        if sorted(self.backtest.origins) != self.backtest.origins:
            raise ValueError("backtest origins must be increasing")
        if self.backtest.origins[-1] + h > self.test_origin:
            raise ValueError("last backtest window must end before the test origin")
        if max(self.horizons) != self.max_horizon:
            raise ValueError("max_horizon must equal the largest evaluation horizon")
        return self


def load_forecast_config(path: Path = FORECAST_CONFIG_PATH) -> ForecastConfig:
    return ForecastConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def get_forecast_config() -> ForecastConfig:
    return load_forecast_config()
