"""Application entry point and FastAPI factory."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.files import router as files_router
from app.core.config import Settings, get_settings
from app.core.exceptions import AppException, app_exception_handler, format_error_response
from app.core.logging import get_logger, setup_logging
from app.db.session import SessionLocal, init_db
from app.services.ingestion_service import IngestionService

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup and shutdown hooks."""
    settings: Settings = get_settings()
    setup_logging()
    logger.info(
        "Starting %s v%s in %s mode", settings.PROJECT_NAME, settings.VERSION, settings.ENVIRONMENT
    )

    # Ensure upload directory exists
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Upload directory initialized at: %s", settings.UPLOAD_DIR.resolve())

    # Ensure database schema is initialized
    init_db()

    # Recover any jobs left in PROCESSING if previously interrupted
    with SessionLocal() as session:
        recovered = IngestionService(session).recover_stale_processing()
        if recovered:
            logger.info("Recovered %d stale processing jobs", recovered)

    yield

    logger.info("Shutting down %s", settings.PROJECT_NAME)


def create_app() -> FastAPI:
    """Create and configure FastAPI application instance."""
    settings = get_settings()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description=(
            "Production-grade API for geospatial file ingestion, validation, "
            "and measurement calculation."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register Exception Handlers
    app.add_exception_handler(AppException, app_exception_handler)  # type: ignore

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        logger.warning("Validation error on request: %s", exc.errors())
        return JSONResponse(
            status_code=422,
            content=format_error_response(
                code="VALIDATION_ERROR",
                message="Request payload validation failed.",
                details={"errors": exc.errors()},
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled server exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content=format_error_response(
                code="INTERNAL_SERVER_ERROR",
                message="An unexpected server error occurred.",
                details={"error": str(exc)},
            ),
        )

    # Register API Routers
    app.include_router(files_router, prefix="/api")

    # Health check endpoint
    @app.get("/health", tags=["Health"], summary="Health Check")
    async def health_check() -> dict[str, Any]:
        """Check application health status."""
        return {
            "status": "healthy",
            "project": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "processing_mode": settings.PROCESSING_MODE,
        }

    # Root route
    @app.get("/", tags=["Info"], summary="API Root")
    async def root() -> dict[str, Any]:
        """Root API metadata."""
        return {
            "message": f"Welcome to {settings.PROJECT_NAME}",
            "docs": "/docs",
            "health": "/health",
            "version": settings.VERSION,
        }

    return app


app = create_app()
