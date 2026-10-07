"""Base reader protocol and dataset metadata definitions."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from shapely.geometry.base import BaseGeometry


@dataclass
class NormalizedFeature:
    """Normalized representation of a single geospatial feature."""

    index: int
    geometry_type: str
    geometry: BaseGeometry | None
    properties: dict[str, Any] = field(default_factory=dict)
    source_crs: str = "EPSG:4326"
    layer: str = "default"


@dataclass
class DatasetInfo:
    """Dataset-level metadata."""

    feature_count: int
    crs: str
    crs_assumed: bool
    layers: list[str] = field(default_factory=list)


class BaseReader(Protocol):
    """Protocol for geospatial file readers."""

    def get_dataset_info(self, file_path: Path) -> DatasetInfo:
        """Inspect file without full dataset loading."""
        ...

    def read_chunks(
        self,
        file_path: Path,
        chunk_size: int = 1000,
    ) -> Iterator[list[NormalizedFeature]]:
        """Yield batches of normalized features."""
        ...

    def cleanup(self) -> None:
        """Clean up temporary files/directories if any were created."""
        ...
