"""Geospatial measurement calculations.

Pure Python module: No FastAPI or database imports.
Rule: Never measure in degrees. Always use always_xy=True with pyproj.
"""

from dataclasses import dataclass, field

import shapely
from pyproj import Geod
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPolygon,
    Polygon,
)
from shapely.geometry.base import BaseGeometry

from app.geo.crs import get_transformer, select_measurement_crs
from app.geo.geometry import ensure_2d, validate_and_repair

# WGS84 Geoid for geodesic validation cross-checks
WGS84_GEOD = Geod(ellps="WGS84")


@dataclass
class MeasurementResult:
    """Standard measurement calculation output."""

    status: str  # OK | UNSUPPORTED | EMPTY | INVALID | ERROR
    area_m2: float | None = None
    perimeter_m: float | None = None
    length_m: float | None = None
    measurement_crs: str | None = None
    method: str | None = None
    warnings: list[str] = field(default_factory=list)
    geodesic_diff_pct: float | None = None


def measure_geometry(
    geom: BaseGeometry | None,
    source_crs: str,
    enable_geodesic_crosscheck: bool = True,
) -> MeasurementResult:
    """Calculate measurements for supported geometries in metric projected CRS.

    Supported:
    - Polygon / MultiPolygon -> area_m2, perimeter_m
    - LineString / MultiLineString -> length_m
    - Point / MultiPoint -> UNSUPPORTED (no crash)
    - GeometryCollection -> recursive sum of supported parts
    """
    if geom is None or geom.is_empty:
        return MeasurementResult(status="EMPTY", warnings=["Feature has empty or null geometry."])

    all_warnings: list[str] = []

    # 1. Force 2D
    geom_2d, dim_warnings = ensure_2d(geom)
    all_warnings.extend(dim_warnings)

    # 2. Validate and repair
    repaired_geom, val_warnings, is_valid = validate_and_repair(geom_2d)
    all_warnings.extend(val_warnings)

    if not is_valid:
        return MeasurementResult(
            status="INVALID",
            warnings=all_warnings,
        )

    # 3. Transform to EPSG:4326 lon/lat if not already
    try:
        if source_crs != "EPSG:4326":
            to_4326 = get_transformer(source_crs, "EPSG:4326")
            geom_4326 = shapely.transform(repaired_geom, to_4326.transform, interleaved=False)
        else:
            geom_4326 = repaired_geom
    except Exception as exc:
        all_warnings.append(f"CRS transformation to EPSG:4326 failed: {exc}")
        return MeasurementResult(
            status="ERROR",
            warnings=all_warnings,
        )

    geom_type = geom_4326.geom_type

    # Points are not measured per requirements
    if geom_type in ("Point", "MultiPoint"):
        return MeasurementResult(
            status="UNSUPPORTED",
            warnings=all_warnings + [f"{geom_type} measurement is not required."],
        )

    # 4. Process Polygons (Area & Perimeter)
    if isinstance(geom_4326, (Polygon, MultiPolygon)):
        meas_crs, method = select_measurement_crs(geom_4326, purpose="area")
        to_meas = get_transformer("EPSG:4326", meas_crs)
        projected = shapely.transform(geom_4326, to_meas.transform, interleaved=False)

        area_val = round(float(projected.area), 4)
        perimeter_val = round(float(projected.length), 4)

        geod_diff = None
        if enable_geodesic_crosscheck:
            try:
                # Geod returns (area, perimeter)
                g_area, _ = WGS84_GEOD.geometry_area_perimeter(geom_4326)
                g_area_abs = abs(g_area)
                if g_area_abs > 0:
                    geod_diff = round(abs(area_val - g_area_abs) / g_area_abs * 100.0, 4)
            except Exception:
                pass

        return MeasurementResult(
            status="OK",
            area_m2=area_val,
            perimeter_m=perimeter_val,
            length_m=None,
            measurement_crs=meas_crs,
            method=method,
            warnings=all_warnings,
            geodesic_diff_pct=geod_diff,
        )

    # 5. Process LineStrings (Length)
    if isinstance(geom_4326, (LineString, MultiLineString)):
        meas_crs, method = select_measurement_crs(geom_4326, purpose="length")
        to_meas = get_transformer("EPSG:4326", meas_crs)
        projected = shapely.transform(geom_4326, to_meas.transform, interleaved=False)

        length_val = round(float(projected.length), 4)

        geod_diff = None
        if enable_geodesic_crosscheck:
            try:
                g_length = float(WGS84_GEOD.geometry_length(geom_4326))
                if g_length > 0:
                    geod_diff = round(abs(length_val - g_length) / g_length * 100.0, 4)
            except Exception:
                pass

        return MeasurementResult(
            status="OK",
            area_m2=None,
            perimeter_m=None,
            length_m=length_val,
            measurement_crs=meas_crs,
            method=method,
            warnings=all_warnings,
            geodesic_diff_pct=geod_diff,
        )

    # 6. Process GeometryCollection
    if isinstance(geom_4326, GeometryCollection):
        polygons = [g for g in geom_4326.geoms if isinstance(g, (Polygon, MultiPolygon))]
        lines = [g for g in geom_4326.geoms if isinstance(g, (LineString, MultiLineString))]

        if not polygons and not lines:
            return MeasurementResult(
                status="UNSUPPORTED",
                warnings=all_warnings
                + ["GeometryCollection contains no measurable sub-geometries."],
            )

        total_area = 0.0
        total_perim = 0.0
        total_len = 0.0
        meas_crs, method = select_measurement_crs(geom_4326, purpose="area")
        to_meas = get_transformer("EPSG:4326", meas_crs)

        for poly in polygons:
            proj_poly = shapely.transform(poly, to_meas.transform, interleaved=False)
            total_area += proj_poly.area
            total_perim += proj_poly.length

        for line in lines:
            proj_line = shapely.transform(line, to_meas.transform, interleaved=False)
            total_len += proj_line.length

        if polygons and lines:
            all_warnings.append(
                "Mixed GeometryCollection measured (both area and line length present)."
            )

        return MeasurementResult(
            status="OK",
            area_m2=round(total_area, 4) if polygons else None,
            perimeter_m=round(total_perim, 4) if polygons else None,
            length_m=round(total_len, 4) if lines else None,
            measurement_crs=meas_crs,
            method=method,
            warnings=all_warnings,
        )

    return MeasurementResult(
        status="UNSUPPORTED",
        warnings=all_warnings + [f"Unsupported geometry type: {geom_type}"],
    )
