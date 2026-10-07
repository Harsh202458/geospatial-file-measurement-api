"""Domain exceptions and uniform error handling schemas."""

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class AppException(Exception):
    """Base exception for all application domain errors."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class InvalidArchiveError(AppException):
    """Raised when an uploaded archive is corrupted, contains zip-slip,
    or violates zip-bomb limits.
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="INVALID_ARCHIVE",
            status_code=422,
            details=details,
        )


class MissingComponentError(AppException):
    """Raised when a shapefile zip is missing required files (e.g. .shp or .dbf)."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="MISSING_COMPONENT",
            status_code=422,
            details=details,
        )


class UnsupportedFormatError(AppException):
    """Raised when an uploaded file format is not supported."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="UNSUPPORTED_FORMAT",
            status_code=415,
            details=details,
        )


class UnreadableFileError(AppException):
    """Raised when geospatial file cannot be parsed or read by GDAL/pyogrio."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="UNREADABLE_FILE",
            status_code=422,
            details=details,
        )


class PayloadTooLargeError(AppException):
    """Raised when upload size exceeds the configured limit."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="PAYLOAD_TOO_LARGE",
            status_code=413,
            details=details,
        )


class ResourceNotFoundError(AppException):
    """Raised when an entity (e.g., file ID) cannot be found."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="NOT_FOUND",
            status_code=404,
            details=details,
        )


class ProcessingNotReadyError(AppException):
    """Raised when querying measurements for a file that is still PENDING or PROCESSING."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="NOT_READY",
            status_code=409,
            details=details,
        )


class CRSResolutionError(AppException):
    """Raised when CRS cannot be resolved or is invalid."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="INVALID_CRS",
            status_code=422,
            details=details,
        )


def format_error_response(
    code: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Uniform error response envelope."""
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        }
    }


async def app_exception_handler(_: Request, exc: AppException) -> JSONResponse:
    """Handle custom application exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content=format_error_response(exc.code, exc.message, exc.details),
    )
