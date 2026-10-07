"""Unit tests for UploadService, IngestionService, and MeasurementService."""

import io
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Polygon
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import (
    InvalidArchiveError,
    PayloadTooLargeError,
    ProcessingNotReadyError,
    ResourceNotFoundError,
    UnsupportedFormatError,
)
from app.db.models import FileStatus
from app.repositories.file_repository import FileRepository
from app.services.ingestion_service import IngestionService
from app.services.measurement_service import MeasurementService
from app.services.upload_service import UploadService
from app.storage.local import LocalStorageService


def _create_sample_zip_bytes() -> bytes:
    """Generate in-memory zip bytes containing a valid shapefile."""
    temp_dir = Path(tempfile.mkdtemp())
    shp_path = temp_dir / "test.shp"
    gdf = gpd.GeoDataFrame(
        {
            "id": [1],
            "geometry": [Polygon([(0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01), (0, 0)])],
        },
        crs="EPSG:4326",
    )
    gdf.to_file(shp_path, driver="ESRI Shapefile")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for ext in (".shp", ".shx", ".dbf", ".prj"):
            f = temp_dir / f"test{ext}"
            if f.exists():
                zf.write(f, arcname=f"test{ext}")
    return buf.getvalue()


def test_upload_service_valid_and_invalid(db_session: Session, test_temp_dir: Path) -> None:
    """Test upload validation, streaming, and error handling."""
    storage = LocalStorageService(test_temp_dir / "storage")
    settings = Settings(UPLOAD_DIR=test_temp_dir / "storage", MAX_UPLOAD_MB=1)
    file_repo = FileRepository(db_session)
    svc = UploadService(file_repo, storage, settings)

    # 1. Valid zip upload
    zip_bytes = _create_sample_zip_bytes()
    stream = io.BytesIO(zip_bytes)
    record, dest_path = svc.process_upload(stream, "parcels.zip")
    assert record.id is not None
    assert record.filename == "parcels.zip"
    assert record.status == FileStatus.PENDING
    assert dest_path.exists()

    # 2. Unsupported extension
    with pytest.raises(UnsupportedFormatError):
        svc.process_upload(io.BytesIO(b"dummy"), "notes.txt")

    # 3. Bad magic bytes (named .zip, but is plain text)
    with pytest.raises(InvalidArchiveError):
        svc.process_upload(io.BytesIO(b"NOT_A_ZIP_HEADER"), "fake.zip")

    # 4. Payload too large
    tiny_settings = Settings(UPLOAD_DIR=test_temp_dir / "storage", MAX_UPLOAD_MB=0)
    tiny_svc = UploadService(file_repo, storage, tiny_settings)
    with pytest.raises(PayloadTooLargeError):
        tiny_svc.process_upload(io.BytesIO(zip_bytes), "toolarge.zip")


def test_ingestion_and_measurement_service_flow(db_session: Session, test_temp_dir: Path) -> None:
    """Test full ingestion pipeline and measurement retrieval."""
    storage = LocalStorageService(test_temp_dir / "storage")
    settings = Settings(UPLOAD_DIR=test_temp_dir / "storage")
    file_repo = FileRepository(db_session)
    upload_svc = UploadService(file_repo, storage, settings)
    ingest_svc = IngestionService(db_session)
    measure_svc = MeasurementService(db_session)

    # 1. Upload valid zip
    zip_bytes = _create_sample_zip_bytes()
    record, dest_path = upload_svc.process_upload(io.BytesIO(zip_bytes), "test.zip")

    # 2. Before ingestion: checking measurements raises ProcessingNotReadyError
    with pytest.raises(ProcessingNotReadyError):
        measure_svc.get_measurements(record.id)

    # 3. Run ingestion
    ingest_svc.process_file(record.id, dest_path)

    # Verify status is COMPLETED
    updated_rec = file_repo.get_by_id(record.id)
    assert updated_rec is not None
    assert updated_rec.status == FileStatus.COMPLETED
    assert updated_rec.feature_count == 1
    assert "4326" in str(updated_rec.crs)

    # 4. Fetch measurements
    file_info, features, total = measure_svc.get_measurements(record.id)
    assert total == 1
    assert len(features) == 1
    assert features[0]["measurement_status"] == "OK"
    assert features[0]["measurements"]["area_m2"] > 0
    assert features[0]["method"] == "laea_equal_area"

    # 5. Non-existent file raises ResourceNotFoundError
    with pytest.raises(ResourceNotFoundError):
        measure_svc.get_file("non-existent-id")
