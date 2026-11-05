"""Typed access to config/recommendations.yaml."""

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

from data_engineering.config import PROJECT_ROOT

REC_CONFIG_PATH = PROJECT_ROOT / "config" / "recommendations.yaml"


class Window(BaseModel):
    cutoff: date
    end: date


class Serving(BaseModel):
    item_neighbours: int = Field(ge=1)
    popular_list_size: int = Field(ge=1)


class RecConfig(BaseModel):
    random_state: int
    k: int = Field(ge=1)
    validation: Window
    test: Window
    exclude_purchased: bool
    bootstrap_resamples: int = Field(ge=10)
    models: dict[str, dict[str, Any]]
    serving: Serving

    @model_validator(mode="after")
    def windows_are_chronological(self) -> "RecConfig":
        if not (self.validation.cutoff < self.validation.end <= self.test.cutoff < self.test.end):
            raise ValueError("validation window must end before the test cutoff")
        return self


def load_rec_config(path: Path = REC_CONFIG_PATH) -> RecConfig:
    return RecConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def get_rec_config() -> RecConfig:
    return load_rec_config()
