"""Pytest configuration and shared test fixtures."""

import shutil
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.main import create_app


@pytest.fixture(scope="session")
def test_temp_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory cleaned up after test session."""
    temp_dir = Path(tempfile.mkdtemp(prefix="geo_measure_test_"))
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def override_settings(test_temp_dir: Path) -> Generator[Settings, None, None]:
    """Override application settings with test settings."""
    app_settings = get_settings()
    app_settings.DATABASE_URL = "sqlite:///:memory:"
    app_settings.UPLOAD_DIR = test_temp_dir / "uploads"
    app_settings.PROCESSING_MODE = "sync"
    app_settings.MAX_UPLOAD_MB = 10
    app_settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    yield app_settings


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Provide an isolated in-memory SQLite database session for unit tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):  # type: ignore
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        expire_on_commit=False,
    )
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(override_settings: Settings) -> Generator[TestClient, None, None]:
    """Test client for FastAPI app."""
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
