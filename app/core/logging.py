"""Logging configuration for Geo-Measure API."""

import logging
import sys

from app.core.config import get_settings


def setup_logging() -> None:
    """Initialize structured application logging."""
    settings = get_settings()
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    log_format = "%(asctime)s | %(levelname)-7s | %(name)s:%(funcName)s:%(lineno)d - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    logging.basicConfig(
        level=log_level,
        format=log_format,
        datefmt=date_format,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )

    # Silence overly verbose third-party loggers if needed
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("pyogrio").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a logger configured for the specified module name."""
    return logging.getLogger(name)
