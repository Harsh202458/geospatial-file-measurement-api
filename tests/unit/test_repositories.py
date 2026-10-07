"""Unit tests for FileRepository and FeatureRepository against SQLite in-memory."""

import uuid

from sqlalchemy.orm import Session

from app.db.models import FileStatus, MeasurementStatus, UploadedFile
from app.repositories.feature_repository import FeatureRepository
from app.repositories.file_repository import FileRepository


def test_file_repository_crud(db_session: Session) -> None:
    """Test creating, reading, updating, and completing an uploaded file."""
    repo = FileRepository(db_session)

    # 1. Create file record
    file_record = repo.create(
        filename="parcels.shp.zip",
        file_format="SHAPEFILE",
        size_bytes=10240,
        sha256="abc123def456",
    )
    assert file_record.id is not None
    assert file_record.status == FileStatus.PENDING
    assert file_record.filename == "parcels.shp.zip"
    assert file_record.feature_count == 0
    assert file_record.crs_assumed is False
    assert file_record.created_at is not None
    assert file_record.completed_at is None

    # 2. Retrieve by ID
    fetched = repo.get_by_id(file_record.id)
    assert fetched is not None
    assert fetched.id == file_record.id
    assert fetched.sha256 == "abc123def456"

    # Non-existent ID returns None
    assert repo.get_by_id(str(uuid.uuid4())) is None

    # 3. Update status to PROCESSING
    updated = repo.update_status(file_record.id, FileStatus.PROCESSING)
    assert updated is not None
    assert updated.status == FileStatus.PROCESSING
    assert updated.completed_at is None

    # 4. Complete file
    completed = repo.complete_file(
        file_id=file_record.id,
        feature_count=42,
        crs="EPSG:4326",
        crs_assumed=True,
    )
    assert completed is not None
    assert completed.status == FileStatus.COMPLETED
    assert completed.feature_count == 42
    assert completed.crs == "EPSG:4326"
    assert completed.crs_assumed is True
    assert completed.completed_at is not None


def test_file_repository_fail_and_stale_recovery(db_session: Session) -> None:
    """Test fail_file and mark_stale_processing_as_failed recovery."""
    repo = FileRepository(db_session)

    # Create file and mark failed
    f1 = repo.create("corrupt.zip", "SHAPEFILE", 500, "hash1")
    failed = repo.fail_file(f1.id, "Invalid archive format")
    assert failed is not None
    assert failed.status == FileStatus.FAILED
    assert failed.error_message == "Invalid archive format"
    assert failed.completed_at is not None

    # Create one stuck in PROCESSING, one in COMPLETED, one in PENDING
    f_stuck = repo.create("stuck.kml", "KML", 200, "hash2")
    repo.update_status(f_stuck.id, FileStatus.PROCESSING)

    f_completed = repo.create("done.kml", "KML", 300, "hash3")
    repo.update_status(f_completed.id, FileStatus.COMPLETED)

    f_pending = repo.create("wait.kml", "KML", 400, "hash4")

    # Recover stale processing jobs
    stale_count = repo.mark_stale_processing_as_failed()
    assert stale_count == 1

    recovered = repo.get_by_id(f_stuck.id)
    assert recovered is not None
    assert recovered.status == FileStatus.FAILED
    assert "interrupted" in (recovered.error_message or "")

    # Others untouched
    assert repo.get_by_id(f_completed.id).status == FileStatus.COMPLETED  # type: ignore
    assert repo.get_by_id(f_pending.id).status == FileStatus.PENDING  # type: ignore


def test_feature_repository_bulk_insert_and_pagination(db_session: Session) -> None:
    """Test bulk insertion in batches and paginated retrieval."""
    file_repo = FileRepository(db_session)
    feat_repo = FeatureRepository(db_session)

    file_record = file_repo.create("test_features.kml", "KML", 1024, "hash123")

    # Empty insert returns 0
    assert feat_repo.bulk_insert_features(file_record.id, []) == 0

    # Prepare 1,250 dummy features to verify batching (batch_size=500)
    features_data = []
    for i in range(1250):
        features_data.append(
            {
                "feature_index": i,
                "geometry_type": "Polygon",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                },
                "source_crs": "EPSG:4326",
                "properties": {"index_num": i, "name": f"Feature {i}"},
                "measurement_status": MeasurementStatus.OK,
                "area_m2": 12345.67 + i,
                "perimeter_m": 450.2,
                "measurement_crs": "+proj=laea +lat_0=0 +lon_0=0",
                "method": "laea_equal_area",
                "warnings": ["Warning test"] if i % 100 == 0 else [],
            }
        )

    inserted_count = feat_repo.bulk_insert_features(
        file_id=file_record.id,
        feature_dicts=features_data,
        batch_size=500,
    )
    assert inserted_count == 1250

    # Test pagination: First page
    page1, total = feat_repo.get_features_by_file_id(
        file_id=file_record.id,
        limit=10,
        offset=0,
        include_geometry=True,
    )
    assert total == 1250
    assert len(page1) == 10
    assert page1[0]["index"] == 0
    assert page1[0]["geometry"] is not None
    assert page1[0]["measurements"]["area_m2"] == 12345.67
    assert page1[0]["measurement_crs"] == "+proj=laea +lat_0=0 +lon_0=0"

    # Test pagination: Second page with include_geometry=False
    page2, total2 = feat_repo.get_features_by_file_id(
        file_id=file_record.id,
        limit=10,
        offset=10,
        include_geometry=False,
    )
    assert total2 == 1250
    assert len(page2) == 10
    assert page2[0]["index"] == 10
    assert page2[0]["geometry"] is None  # Excluded when false
    assert page2[0]["properties"]["name"] == "Feature 10"


def test_cascade_delete_features(db_session: Session) -> None:
    """Verify deleting UploadedFile cascades to delete associated Features."""
    file_repo = FileRepository(db_session)
    feat_repo = FeatureRepository(db_session)

    file_rec = file_repo.create("cascade_test.shp.zip", "SHAPEFILE", 2048, "hash_casc")
    feat_repo.bulk_insert_features(
        file_rec.id,
        [
            {
                "feature_index": 0,
                "geometry_type": "Point",
                "source_crs": "EPSG:4326",
                "properties": {},
                "measurement_status": MeasurementStatus.UNSUPPORTED,
            }
        ],
    )

    items, count = feat_repo.get_features_by_file_id(file_rec.id)
    assert count == 1

    # Delete the parent file record
    rec_to_delete = db_session.get(UploadedFile, file_rec.id)
    assert rec_to_delete is not None
    db_session.delete(rec_to_delete)
    db_session.commit()

    # Features should now be gone
    items_after, count_after = feat_repo.get_features_by_file_id(file_rec.id)
    assert count_after == 0
    assert len(items_after) == 0
