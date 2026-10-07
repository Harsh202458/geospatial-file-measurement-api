"""Ingestion pipeline orchestrating file reading, measurement, and persistence."""

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.core.logging import get_logger
from app.db.models import FileStatus, MeasurementStatus
from app.geo.geometry import to_geojson_dict
from app.geo.measure import measure_geometry
from app.geo.readers.base import BaseReader
from app.geo.readers.kml import KmlReader
from app.geo.readers.shapefile import ShapefileReader
from app.repositories.feature_repository import FeatureRepository
from app.repositories.file_repository import FileRepository

logger = get_logger(__name__)


class IngestionService:
    """Orchestrates reading geospatial files, executing measurements, and persisting features."""

    def __init__(self, db: Session, assume_wgs84_if_missing: bool = True) -> None:
        self.db = db
        self.file_repo = FileRepository(db)
        self.feature_repo = FeatureRepository(db)
        self.assume_wgs84 = assume_wgs84_if_missing

    def process_file(self, file_id: str, stored_path: Path) -> None:
        """Execute full ingestion pipeline for an uploaded file."""
        file_record = self.file_repo.get_by_id(file_id)
        if not file_record:
            logger.error("File ID %s not found for ingestion processing", file_id)
            return

        # 1. Transition to PROCESSING state
        self.file_repo.update_status(file_id, FileStatus.PROCESSING)
        logger.info("Started processing file %s (%s)", file_id, file_record.filename)

        reader: BaseReader
        if file_record.format == "SHAPEFILE":
            reader = ShapefileReader(assume_wgs84_if_missing=self.assume_wgs84)
        elif file_record.format == "KML":
            reader = KmlReader()
        else:
            err_msg = f"Unknown file format: {file_record.format}"
            logger.error(err_msg)
            self.file_repo.fail_file(file_id, err_msg)
            return

        try:
            # 2. Extract dataset metadata
            dataset_info = reader.get_dataset_info(stored_path)

            total_features_processed = 0

            # 3. Stream and process features chunk by chunk
            for chunk in reader.read_chunks(stored_path, chunk_size=1000):
                prepared_features: list[dict[str, Any]] = []

                for item in chunk:
                    try:
                        meas = measure_geometry(item.geometry, item.source_crs)
                        status_str = meas.status
                        area_m2 = meas.area_m2
                        perimeter_m = meas.perimeter_m
                        length_m = meas.length_m
                        meas_crs = meas.measurement_crs
                        method = meas.method
                        warnings = meas.warnings
                    except Exception as feat_err:
                        # Graceful failure per feature: NEVER crash the file!
                        logger.warning(
                            "Feature %d measurement calculation failed: %s", item.index, feat_err
                        )
                        status_str = MeasurementStatus.ERROR.value
                        area_m2 = None
                        perimeter_m = None
                        length_m = None
                        meas_crs = None
                        method = None
                        warnings = [f"Feature calculation error: {feat_err}"]

                    prepared_features.append(
                        {
                            "feature_index": item.index,
                            "geometry_type": item.geometry_type,
                            "geometry": to_geojson_dict(item.geometry),
                            "source_crs": item.source_crs,
                            "properties": item.properties,
                            "measurement_status": status_str,
                            "area_m2": area_m2,
                            "length_m": length_m,
                            "perimeter_m": perimeter_m,
                            "measurement_crs": meas_crs,
                            "method": method,
                            "warnings": warnings,
                        }
                    )

                # Bulk insert features into database
                self.feature_repo.bulk_insert_features(
                    file_id=file_id,
                    feature_dicts=prepared_features,
                    batch_size=1000,
                )
                total_features_processed += len(prepared_features)

            # 4. Mark COMPLETED
            self.file_repo.complete_file(
                file_id=file_id,
                feature_count=total_features_processed,
                crs=dataset_info.crs,
                crs_assumed=dataset_info.crs_assumed,
            )
            logger.info(
                "Successfully completed ingestion for file %s with %d features",
                file_id,
                total_features_processed,
            )

        except AppException as app_err:
            logger.warning("Domain error during ingestion of %s: %s", file_id, app_err.message)
            self.file_repo.fail_file(file_id, app_err.message)
        except Exception as exc:
            logger.exception("Unexpected error processing file %s: %s", file_id, exc)
            self.file_repo.fail_file(file_id, str(exc))
        finally:
            # 5. Always clean up temporary resources
            reader.cleanup()

    def recover_stale_processing(self) -> int:
        """Mark any files left in PROCESSING on service startup as FAILED."""
        count = self.file_repo.mark_stale_processing_as_failed()
        if count > 0:
            logger.warning("Recovered %d stale PROCESSING files on startup", count)
        return count
