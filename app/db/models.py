"""SQLAlchemy 2.0 ORM data models."""

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.sqlite import JSON as SQLITE_JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base


class FileStatus(enum.StrEnum):
    """Lifecycle status of an uploaded file."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MeasurementStatus(enum.StrEnum):
    """Per-feature measurement calculation status."""

    OK = "OK"
    UNSUPPORTED = "UNSUPPORTED"
    EMPTY = "EMPTY"
    INVALID = "INVALID"
    ERROR = "ERROR"


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(UTC)


class UploadedFile(Base):
    """Uploaded geospatial file record."""

    __tablename__ = "uploaded_files"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    format: Mapped[str] = mapped_column(String(50), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[FileStatus] = mapped_column(
        Enum(FileStatus, native_enum=False),
        default=FileStatus.PENDING,
        nullable=False,
        index=True,
    )
    crs: Mapped[str | None] = mapped_column(String(100), nullable=True)
    crs_assumed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    feature_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    features: Mapped[list["Feature"]] = relationship(
        "Feature",
        back_populates="file",
        cascade="all, delete-orphan",
    )


class Feature(Base):
    """Geospatial feature and associated measurements."""

    __tablename__ = "features"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    file_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("uploaded_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    feature_index: Mapped[int] = mapped_column(Integer, nullable=False)
    geometry_type: Mapped[str] = mapped_column(String(50), nullable=False)
    geometry: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(SQLITE_JSON, "sqlite"),
        nullable=True,
    )
    source_crs: Mapped[str] = mapped_column(String(100), nullable=False)
    properties: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(SQLITE_JSON, "sqlite"),
        default=dict,
        nullable=False,
    )
    measurement_status: Mapped[MeasurementStatus] = mapped_column(
        Enum(MeasurementStatus, native_enum=False),
        default=MeasurementStatus.OK,
        nullable=False,
        index=True,
    )
    area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    length_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    perimeter_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    measurement_crs: Mapped[str | None] = mapped_column(String(100), nullable=True)
    method: Mapped[str | None] = mapped_column(String(100), nullable=True)
    warnings: Mapped[list[str]] = mapped_column(
        JSON().with_variant(SQLITE_JSON, "sqlite"),
        default=list,
        nullable=False,
    )

    # Relationships
    file: Mapped["UploadedFile"] = relationship("UploadedFile", back_populates="features")

    __table_args__ = (Index("ix_features_file_id_feature_index", "file_id", "feature_index"),)
