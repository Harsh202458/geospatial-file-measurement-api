"""Geometry processing, validation, and JSON sanitization.

Pure Python module: No FastAPI or database imports.
"""

import datetime
import math
from typing import Any

import numpy as np
import shapely
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry


def ensure_2d(geom: BaseGeometry) -> tuple[BaseGeometry, list[str]]:
    """Force geometry to 2D coordinates (X, Y), dropping Z/M dimensions.

    Adds a warning if geometry had 3D coordinates.
    """
    warnings: list[str] = []
    if geom.has_z:
        warnings.append("Coordinates contain Z dimension; 3D values projected to 2D planar.")
        geom = shapely.force_2d(geom)
    return geom, warnings


def validate_and_repair(geom: BaseGeometry) -> tuple[BaseGeometry, list[str], bool]:
    """Validate geometry and repair invalid geometries via make_valid.

    Returns:
        tuple[BaseGeometry, list[str], bool]: (repaired_geom, warnings, is_valid)
    """
    warnings: list[str] = []
    if geom.is_empty:
        return geom, ["Geometry is empty."], True

    if not geom.is_valid:
        reason = shapely.is_valid_reason(geom)
        warnings.append(f"Invalid geometry repaired ({reason}).")
        repaired = shapely.make_valid(geom)
        if not repaired.is_valid or repaired.is_empty:
            return repaired, [f"Unrepairable geometry: {reason}"], False
        return repaired, warnings, True

    return geom, warnings, True


def to_geojson_dict(geom: BaseGeometry | None) -> dict[str, Any] | None:
    """Serialize Shapely geometry to standard GeoJSON dictionary."""
    if geom is None or geom.is_empty:
        return None
    return mapping(geom)  # type: ignore


def sanitize_properties(props: dict[str, Any] | Any) -> dict[str, Any]:
    """Ensure dictionary values are strictly JSON-serializable.

    Handles datetimes, numpy types, NaNs, infinities, and byte strings.
    """
    if not isinstance(props, dict):
        return {}

    clean_props: dict[str, Any] = {}
    for key, value in props.items():
        clean_key = str(key)
        clean_props[clean_key] = _sanitize_val(value)

    return clean_props


def _sanitize_val(val: Any) -> Any:
    """Recursively sanitize individual value."""
    if val is None:
        return None
    if isinstance(val, (datetime.datetime, datetime.date)):
        return val.isoformat()
    if isinstance(val, (bytes, bytearray)):
        return val.decode("utf-8", errors="replace")
    if isinstance(val, (np.integer, int)):
        return int(val)
    if isinstance(val, (np.floating, float)):
        if math.isnan(val) or math.isinf(val):
            return None
        return float(val)
    if isinstance(val, (np.bool_, bool)):
        return bool(val)
    if isinstance(val, (list, tuple)):
        return [_sanitize_val(v) for v in val]
    if isinstance(val, dict):
        return {str(k): _sanitize_val(v) for k, v in val.items()}
    return str(val)
