"""Pydantic v2 schemas for API requests and responses."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FileUploadResponse(BaseModel):
    """Response returned upon file upload."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Unique identifier for uploaded file")
    filename: str = Field(description="Original filename")
    status: str = Field(description="Current file processing status (PENDING | PROCESSING)")


class FileInfoResponse(BaseModel):
    """Response returned for file status and metadata query."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    format: str
    size_bytes: int
    sha256: str
    status: str
    crs: str | None = None
    crs_assumed: bool = False
    feature_count: int = 0
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class FeatureMeasurements(BaseModel):
    """Calculated metric measurements for a feature."""

    area_m2: float | None = Field(default=None, description="Area in square meters (polygons)")
    perimeter_m: float | None = Field(default=None, description="Perimeter in meters (polygons)")
    length_m: float | None = Field(default=None, description="Length in meters (linestrings)")


class FeatureMeasurementItem(BaseModel):
    """Measurement entry for an individual feature."""

    index: int = Field(description="Zero-based feature index in file")
    geometry_type: str = Field(description="Type of geometry (Polygon, LineString, Point, etc.)")
    source_crs: str = Field(description="Source Coordinate Reference System")
    measurement_status: str = Field(
        description="Measurement calculation status: OK | UNSUPPORTED | EMPTY | INVALID | ERROR"
    )
    measurements: FeatureMeasurements = Field(description="Calculated measurements")
    measurement_crs: str | None = Field(
        default=None, description="Projected metric CRS used for calculations"
    )
    method: str | None = Field(default=None, description="Measurement algorithm/strategy applied")
    properties: dict[str, Any] = Field(
        default_factory=dict, description="Feature attributes and metadata"
    )
    geometry: dict[str, Any] | None = Field(
        default=None, description="GeoJSON geometry dictionary (null if omitted)"
    )
    warnings: list[str] = Field(
        default_factory=list, description="Warnings generated during geometry repair or measurement"
    )


class FileMeasurementsResponse(BaseModel):
    """Paginated response containing feature measurements."""

    file_id: str
    total: int = Field(description="Total count of features in file")
    limit: int = Field(description="Page size limit")
    offset: int = Field(description="Page offset")
    features: list[FeatureMeasurementItem]


class ErrorDetail(BaseModel):
    """Structured error envelope."""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Standard error response format."""

    error: ErrorDetail
