"""Measurement and file query service."""

from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import ProcessingNotReadyError, ResourceNotFoundError
from app.db.models import FileStatus, UploadedFile
from app.repositories.feature_repository import FeatureRepository
from app.repositories.file_repository import FileRepository


class MeasurementService:
    """Service handling retrieval of file details and feature measurements."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.file_repo = FileRepository(db)
        self.feature_repo = FeatureRepository(db)

    def get_file(self, file_id: str) -> UploadedFile:
        """Fetch file record or raise ResourceNotFoundError."""
        file_rec = self.file_repo.get_by_id(file_id)
        if not file_rec:
            raise ResourceNotFoundError(f"File with ID '{file_id}' does not exist.")
        return file_rec

    def get_measurements(
        self,
        file_id: str,
        limit: int = 100,
        offset: int = 0,
        include_geometry: bool = True,
    ) -> tuple[UploadedFile, list[dict[str, Any]], int]:
        """Fetch measurements for file, validating that processing is completed."""
        file_rec = self.get_file(file_id)

        if file_rec.status in (FileStatus.PENDING, FileStatus.PROCESSING):
            raise ProcessingNotReadyError(
                f"File '{file_id}' is in status {file_rec.status}. Measurements not ready yet.",
                details={"status": file_rec.status.value, "file_id": file_id},
            )

        features, total_count = self.feature_repo.get_features_by_file_id(
            file_id=file_id,
            limit=limit,
            offset=offset,
            include_geometry=include_geometry,
        )

        return file_rec, features, total_count
