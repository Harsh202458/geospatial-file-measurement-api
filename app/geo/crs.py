"""Coordinate Reference System (CRS) resolution and projection strategy.

Pure Python module: No FastAPI or database imports.
Rule: Never measure in degrees. Always use always_xy=True with pyproj.
"""

import math
from typing import Literal

from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry


def resolve_source_crs(
    declared_crs: str | None,
    bounds: tuple[float, float, float, float] | None,
    assume_wgs84_if_missing: bool = True,
) -> tuple[str, bool]:
    """Resolve the source CRS of a dataset.

    Returns:
        tuple[str, bool]: (resolved_crs_str, crs_assumed_flag)
    """
    if declared_crs:
        try:
            crs_obj = CRS.from_user_input(declared_crs)
            # Normalize to authority string if possible, or srs
            auth = crs_obj.to_authority()
            if auth:
                return f"{auth[0]}:{auth[1]}", False
            return crs_obj.to_string(), False
        except Exception:
            pass

    # If CRS is missing or unparseable, check geographic bounding box
    if bounds is not None:
        minx, miny, maxx, maxy = bounds
        if (
            -180.0 <= minx <= 180.0
            and -180.0 <= maxx <= 180.0
            and -90.0 <= miny <= 90.0
            and -90.0 <= maxy <= 90.0
        ):
            if assume_wgs84_if_missing:
                return "EPSG:4326", True

    if assume_wgs84_if_missing:
        return "EPSG:4326", True

    raise ValueError("Unable to determine source CRS and assumptions are disabled.")


def utm_epsg_for(lon: float, lat: float) -> int:
    """Calculate the UTM EPSG code for a given longitude and latitude.

    Auto-UTM math:
        zone = floor((lon + 180) / 6) + 1  # 1..60 (clamp lon=180 -> 60)
        EPSG = 32600 + zone if lat >= 0 else 32700 + zone
    """
    if lon >= 180.0:
        zone = 60
    elif lon <= -180.0:
        zone = 1
    else:
        zone = int(math.floor((lon + 180.0) / 6.0)) + 1
        zone = max(1, min(60, zone))

    if lat >= 0.0:
        return 32600 + zone
    return 32700 + zone


def laea_crs_for(lon: float, lat: float) -> str:
    """Generate Lambert Azimuthal Equal Area (LAEA) PROJ string centered on (lon, lat).

    Formula:
        +proj=laea +lat_0=<lat> +lon_0=<lon> +datum=WGS84 +units=m +no_defs
    """
    # Clamp polar centers slightly to avoid singularity at exact poles if needed
    lat_clamped = max(-89.999999, min(89.999999, lat))
    lon_clamped = max(-180.0, min(180.0, lon))
    return (
        f"+proj=laea +lat_0={lat_clamped:.6f} +lon_0={lon_clamped:.6f} "
        "+datum=WGS84 +units=m +no_defs"
    )


def select_measurement_crs(
    geom_4326: BaseGeometry,
    purpose: Literal["area", "length"],
) -> tuple[str, str]:
    """Select the optimal projected CRS for measurement.

    Strategy pattern:
    - Area: Per-feature Lambert Azimuthal Equal Area (LAEA). Preserves area exactly
      with no UTM zone-boundary issues.
    - Length: Auto-UTM for local accuracy (scale distortion < 0.1%). Falls back to
      per-feature LAEA if longitudinal span > 6° or polar (|lat| > 84°N or 80°S).

    Returns:
        tuple[str, str]: (measurement_crs_string, method_name)
    """
    centroid = geom_4326.centroid
    lon_c, lat_c = centroid.x, centroid.y
    minx, miny, maxx, maxy = geom_4326.bounds
    lon_span = abs(maxx - minx)

    if purpose == "area":
        proj_str = laea_crs_for(lon_c, lat_c)
        return proj_str, "laea_equal_area"

    # Length purpose
    # Fallback if polar or large longitudinal extent
    if lon_span > 6.0 or lat_c > 84.0 or lat_c < -80.0:
        proj_str = laea_crs_for(lon_c, lat_c)
        return proj_str, "laea_fallback"

    epsg = utm_epsg_for(lon_c, lat_c)
    return f"EPSG:{epsg}", "auto_utm"


def get_transformer(from_crs: str, to_crs: str) -> Transformer:
    """Create a PyProj Transformer with always_xy=True."""
    return Transformer.from_crs(from_crs, to_crs, always_xy=True)
