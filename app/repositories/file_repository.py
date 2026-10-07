"""Repository for uploaded file records."""

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import FileStatus, UploadedFile


class FileRepository:
    """Handles persistence operations for UploadedFile entities."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        filename: str,
        file_format: str,
        size_bytes: int,
        sha256: str,
        file_id: str | None = None,
    ) -> UploadedFile:
        """Create and persist a new UploadedFile record in PENDING state."""
        file_record = UploadedFile(
            filename=filename,
            format=file_format,
            size_bytes=size_bytes,
            sha256=sha256,
            status=FileStatus.PENDING,
        )
        if file_id:
            file_record.id = file_id

        self.db.add(file_record)
        self.db.commit()
        self.db.refresh(file_record)
        return file_record

    def get_by_id(self, file_id: str) -> UploadedFile | None:
        """Retrieve an UploadedFile by its UUID."""
        stmt = select(UploadedFile).where(UploadedFile.id == file_id)
        return self.db.scalars(stmt).first()

    def update_status(
        self,
        file_id: str,
        status: FileStatus,
        error_message: str | None = None,
    ) -> UploadedFile | None:
        """Update the lifecycle status of an UploadedFile."""
        file_record = self.get_by_id(file_id)
        if not file_record:
            return None

        file_record.status = status
        if error_message is not None:
            file_record.error_message = error_message
        if status in (FileStatus.COMPLETED, FileStatus.FAILED):
            file_record.completed_at = datetime.now(UTC)

        self.db.commit()
        self.db.refresh(file_record)
        return file_record

    def complete_file(
        self,
        file_id: str,
        feature_count: int,
        crs: str,
        crs_assumed: bool,
    ) -> UploadedFile | None:
        """Mark a file as COMPLETED with metadata."""
        file_record = self.get_by_id(file_id)
        if not file_record:
            return None

        file_record.status = FileStatus.COMPLETED
        file_record.feature_count = feature_count
        file_record.crs = crs
        file_record.crs_assumed = crs_assumed
        file_record.completed_at = datetime.now(UTC)

        self.db.commit()
        self.db.refresh(file_record)
        return file_record

    def fail_file(self, file_id: str, error_message: str) -> UploadedFile | None:
        """Mark a file as FAILED with an error message."""
        return self.update_status(file_id, FileStatus.FAILED, error_message=error_message)

    def mark_stale_processing_as_failed(self) -> int:
        """Mark any files stuck in PROCESSING as FAILED upon service startup."""
        stmt = (
            update(UploadedFile)
            .where(UploadedFile.status == FileStatus.PROCESSING)
            .values(
                status=FileStatus.FAILED,
                error_message="Process interrupted mid-job (server shutdown or restart).",
                completed_at=datetime.now(UTC),
            )
        )
        result = self.db.execute(stmt)
        self.db.commit()
        return int(getattr(result, "rowcount", 0) or 0)
