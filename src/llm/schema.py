"""
src/llm/schema.py
Pydantic output schema for the /enrich endpoint.
All categories and quality flags use closed enums — the model MUST match these exactly.
"""
from enum import Enum
from typing import List
from pydantic import BaseModel, field_validator


class Category(str, Enum):
    fiction = "fiction"
    non_fiction = "non-fiction"
    children = "children"
    poetry = "poetry"
    biography = "biography"
    other = "other"


class QualityFlag(str, Enum):
    missing_description = "missing_description"
    price_anomaly = "price_anomaly"
    suspicious_rating = "suspicious_rating"
    none = "none"


class EnrichOutput(BaseModel):
    category: Category
    summary: str
    quality_flags: List[QualityFlag]

    @field_validator("summary")
    @classmethod
    def summary_must_not_be_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("summary must not be empty")
        return v

    @field_validator("quality_flags")
    @classmethod
    def flags_must_be_consistent(cls, v: List[QualityFlag]) -> List[QualityFlag]:
        # If "none" is mixed with real flags, strip "none"
        if QualityFlag.none in v and len(v) > 1:
            v = [f for f in v if f != QualityFlag.none]
        return v
