"""Repository for feature records and measurement results."""

import uuid
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.db.models import Feature, MeasurementStatus


class FeatureRepository:
    """Handles persistence operations for Feature entities."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def bulk_insert_features(
        self,
        file_id: str,
        feature_dicts: list[dict[str, Any]],
        batch_size: int = 1000,
    ) -> int:
        """Insert features in batches of batch_size for memory efficiency."""
        if not feature_dicts:
            return 0

        total_inserted = 0
        for i in range(0, len(feature_dicts), batch_size):
            chunk = feature_dicts[i : i + batch_size]
            prepared_records = []
            for item in chunk:
                status_val = item.get("measurement_status", MeasurementStatus.OK)
                if isinstance(status_val, MeasurementStatus):
                    status_val = status_val.value

                record = {
                    "id": item.get("id") or str(uuid.uuid4()),
                    "file_id": file_id,
                    "feature_index": item["feature_index"],
                    "geometry_type": item["geometry_type"],
                    "geometry": item.get("geometry"),
                    "source_crs": item["source_crs"],
                    "properties": item.get("properties", {}),
                    "measurement_status": status_val,
                    "area_m2": item.get("area_m2"),
                    "length_m": item.get("length_m"),
                    "perimeter_m": item.get("perimeter_m"),
                    "measurement_crs": item.get("measurement_crs"),
                    "method": item.get("method"),
                    "warnings": item.get("warnings", []),
                }
                prepared_records.append(record)

            self.db.execute(insert(Feature), prepared_records)
            self.db.commit()
            total_inserted += len(prepared_records)

        return total_inserted

    def get_features_by_file_id(
        self,
        file_id: str,
        limit: int = 100,
        offset: int = 0,
        include_geometry: bool = True,
    ) -> tuple[list[dict[str, Any]], int]:
        """Fetch paginated features for a given file and total count."""
        # Total count query
        count_stmt = select(func.count()).select_from(Feature).where(Feature.file_id == file_id)
        total_count = self.db.scalar(count_stmt) or 0

        # Data query
        stmt = (
            select(Feature)
            .where(Feature.file_id == file_id)
            .order_by(Feature.feature_index.asc())
            .offset(offset)
            .limit(limit)
        )
        records = self.db.scalars(stmt).all()

        results = []
        for feat in records:
            item = {
                "id": feat.id,
                "file_id": feat.file_id,
                "index": feat.feature_index,
                "geometry_type": feat.geometry_type,
                "source_crs": feat.source_crs,
                "measurement_status": (
                    feat.measurement_status.value
                    if hasattr(feat.measurement_status, "value")
                    else str(feat.measurement_status)
                ),
                "measurements": {
                    "area_m2": feat.area_m2,
                    "length_m": feat.length_m,
                    "perimeter_m": feat.perimeter_m,
                },
                "measurement_crs": feat.measurement_crs,
                "method": feat.method,
                "properties": feat.properties,
                "geometry": feat.geometry if include_geometry else None,
                "warnings": feat.warnings or [],
            }
            results.append(item)

        return results, total_count
