"""Application settings and configuration management."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for Geo-Measure API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    PROJECT_NAME: str = "Geospatial File Measurement API"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    # Database settings
    DATABASE_URL: str = "sqlite:///./geo_measure.db"

    # Ingestion & Upload limits
    MAX_UPLOAD_MB: int = Field(default=50, description="Max uploaded file size in MB")
    MAX_ZIP_UNCOMPRESSED_MB: int = Field(
        default=250, description="Max uncompressed archive size in MB (zip-bomb defense)"
    )
    MAX_ZIP_MEMBERS: int = Field(
        default=1000, description="Max archive member count (zip-bomb defense)"
    )

    # Processing mode: 'sync' for synchronous processing (tests/cli), 'background' for async task
    PROCESSING_MODE: Literal["sync", "background"] = "background"

    # CRS Handling policy
    ASSUME_WGS84_IF_MISSING: bool = Field(
        default=True,
        description=(
            "Assume EPSG:4326 if .prj is missing and coordinates fit [-180, 180] x [-90, 90]"
        ),
    )

    # Storage settings
    UPLOAD_DIR: Path = Field(
        default=Path("./uploads"), description="Local directory for file storage"
    )

    @property
    def max_upload_bytes(self) -> int:
        """Max upload size in bytes."""
        return self.MAX_UPLOAD_MB * 1024 * 1024

    @property
    def max_zip_uncompressed_bytes(self) -> int:
        """Max uncompressed zip size in bytes."""
        return self.MAX_ZIP_UNCOMPRESSED_MB * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
