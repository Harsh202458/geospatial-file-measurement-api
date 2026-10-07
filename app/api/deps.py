"""Dependency injection providers for API endpoints."""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.repositories.file_repository import FileRepository
from app.services.measurement_service import MeasurementService
from app.services.upload_service import UploadService
from app.storage.local import LocalStorageService


def get_storage(settings: Settings = Depends(get_settings)) -> LocalStorageService:
    """Provide local storage service instance."""
    return LocalStorageService(settings.UPLOAD_DIR)


def get_upload_svc(
    db: Session = Depends(get_db),
    storage: LocalStorageService = Depends(get_storage),
    settings: Settings = Depends(get_settings),
) -> UploadService:
    """Provide upload service instance."""
    return UploadService(FileRepository(db), storage, settings)


def get_measurement_svc(db: Session = Depends(get_db)) -> MeasurementService:
    """Provide measurement query service instance."""
    return MeasurementService(db)
