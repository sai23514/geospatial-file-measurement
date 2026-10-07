from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class FileInfo(BaseModel):
    id: str
    filename: str
    file_type: str
    feature_count: int
    crs: str | None = Field(None, description='File CRS, or "MIXED" if layers differ')
    status: str
    error: str | None = None
    created_at: datetime
    geometry_type_counts: dict[str, int] = Field(default_factory=dict)


class FeatureOut(BaseModel):
    index: int
    layer: str
    geometry_type: str
    crs: str
    geometry: dict[str, Any] | None
    properties: dict[str, Any]


class FeaturePage(BaseModel):
    file_id: str
    total: int
    limit: int
    offset: int
    items: list[FeatureOut]


class MeasurementOut(BaseModel):
    feature_index: int
    layer: str
    geometry_type: str
    status: str
    area_m2: float | None = None
    length_m: float | None = None
    projected_crs: str | None = Field(None, description="CRS the measurement was computed in")
    message: str | None = None


class MeasurementSummary(BaseModel):
    total_area_m2: float
    total_length_m: float
    status_counts: dict[str, int]


class MeasurementPage(BaseModel):
    file_id: str
    total: int
    limit: int
    offset: int
    summary: MeasurementSummary
    items: list[MeasurementOut]
