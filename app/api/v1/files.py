"""API routes for geospatial file upload, inspection, and measurement."""

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_measurement_svc, get_upload_svc
from app.core.config import Settings, get_settings
from app.db.session import SessionLocal, get_db
from app.schemas.files import (
    ErrorResponse,
    FileInfoResponse,
    FileMeasurementsResponse,
    FileUploadResponse,
)
from app.services.ingestion_service import IngestionService
from app.services.measurement_service import MeasurementService
from app.services.upload_service import UploadService

router = APIRouter(prefix="/files", tags=["Files"])


def _run_background_ingestion(file_id: str, stored_path: Path, assume_wgs84: bool) -> None:
    """Dedicated background task worker creating an isolated database session."""
    with SessionLocal() as db_session:
        ingestion_svc = IngestionService(db_session, assume_wgs84_if_missing=assume_wgs84)
        ingestion_svc.process_file(file_id, stored_path)


@router.post(
    "/",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=FileUploadResponse,
    summary="Upload Geospatial File",
    description="Upload a Shapefile (.zip) or KML (.kml) archive for measurement processing.",
    responses={
        413: {"model": ErrorResponse, "description": "File exceeds size limit"},
        415: {"model": ErrorResponse, "description": "Unsupported media format"},
        422: {"model": ErrorResponse, "description": "Invalid archive or missing components"},
    },
)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Geospatial file (.zip containing Shapefile or .kml)"),
    upload_svc: UploadService = Depends(get_upload_svc),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> FileUploadResponse:
    """Accepts uploaded geospatial file and triggers ingestion."""
    filename = file.filename or "unknown.zip"
    record, dest_path = upload_svc.process_upload(
        stream=file.file,
        filename=filename,
    )

    if settings.PROCESSING_MODE == "sync":
        # Synchronous execution (useful for testing and deterministic CLI runs)
        ingestion_svc = IngestionService(
            db, assume_wgs84_if_missing=settings.ASSUME_WGS84_IF_MISSING
        )
        ingestion_svc.process_file(record.id, dest_path)
        # Refresh to capture updated status
        db.refresh(record)
    else:
        # Asynchronous execution via FastAPI BackgroundTasks
        background_tasks.add_task(
            _run_background_ingestion,
            record.id,
            dest_path,
            settings.ASSUME_WGS84_IF_MISSING,
        )

    return FileUploadResponse(
        id=record.id,
        filename=record.filename,
        status=record.status.value,
    )


@router.get(
    "/{id}/",
    response_model=FileInfoResponse,
    summary="Get File Information",
    description="Fetch processing status, feature count, and CRS metadata for an uploaded file.",
    responses={
        404: {"model": ErrorResponse, "description": "File not found"},
    },
)
def get_file_info(
    id: str,
    measure_svc: MeasurementService = Depends(get_measurement_svc),
) -> FileInfoResponse:
    """Retrieve metadata and lifecycle status for a file."""
    record = measure_svc.get_file(id)
    return FileInfoResponse(
        id=record.id,
        filename=record.filename,
        format=record.format,
        size_bytes=record.size_bytes,
        sha256=record.sha256,
        status=record.status.value,
        crs=record.crs,
        crs_assumed=record.crs_assumed,
        feature_count=record.feature_count,
        error_message=record.error_message,
        created_at=record.created_at,
        completed_at=record.completed_at,
    )


@router.get(
    "/{id}/measurements/",
    response_model=FileMeasurementsResponse,
    summary="Get Feature Measurements",
    description="Retrieve paginated feature measurements for a completed geospatial file.",
    responses={
        404: {"model": ErrorResponse, "description": "File not found"},
        409: {"model": ErrorResponse, "description": "File is still processing or pending"},
    },
)
def get_file_measurements(
    id: str,
    limit: int = Query(default=100, ge=1, le=1000, description="Page limit (max 1000)"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    include_geometry: bool = Query(
        default=True, description="Whether to include full GeoJSON geometry in output"
    ),
    measure_svc: MeasurementService = Depends(get_measurement_svc),
) -> FileMeasurementsResponse:
    """Retrieve calculated measurements for all features in the file."""
    file_rec, features, total_count = measure_svc.get_measurements(
        file_id=id,
        limit=limit,
        offset=offset,
        include_geometry=include_geometry,
    )

    return FileMeasurementsResponse(
        file_id=file_rec.id,
        total=total_count,
        limit=limit,
        offset=offset,
        features=features,  # type: ignore
    )
