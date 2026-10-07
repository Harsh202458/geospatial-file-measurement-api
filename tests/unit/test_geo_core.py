"""Unit tests for pure geospatial core logic (CRS, geometry, measurements)."""

import pytest
from shapely.geometry import (
    GeometryCollection,
    LineString,
    Point,
    Polygon,
)

from app.geo.crs import resolve_source_crs, utm_epsg_for
from app.geo.geometry import ensure_2d, sanitize_properties, validate_and_repair
from app.geo.measure import measure_geometry


def test_utm_epsg_calculation() -> None:
    """Verify UTM zone and hemisphere logic across boundaries."""
    # Equator and northern hemisphere
    assert utm_epsg_for(0.0, 0.0) == 32631
    assert utm_epsg_for(5.99, 10.0) == 32631
    assert utm_epsg_for(6.01, 10.0) == 32632

    # Southern hemisphere
    assert utm_epsg_for(0.0, -1.0) == 32731
    assert utm_epsg_for(77.5, -12.9) == 32743

    # Longitudinal extremes (-180 and 180)
    assert utm_epsg_for(-180.0, 20.0) == 32601
    assert utm_epsg_for(180.0, 20.0) == 32660


def test_resolve_source_crs() -> None:
    """Test CRS resolution and assumption logic."""
    # Declared standard CRS
    crs, assumed = resolve_source_crs("EPSG:4326", None)
    assert crs == "EPSG:4326"
    assert assumed is False

    # Missing CRS within geographic bounds -> assumes EPSG:4326
    crs, assumed = resolve_source_crs(
        None, (-120.0, 30.0, -119.0, 31.0), assume_wgs84_if_missing=True
    )
    assert crs == "EPSG:4326"
    assert assumed is True

    # Missing CRS when assumption is disabled -> ValueError
    with pytest.raises(ValueError, match="Unable to determine source CRS"):
        resolve_source_crs(
            None, (500000.0, 4000000.0, 501000.0, 4001000.0), assume_wgs84_if_missing=False
        )


def test_ensure_2d_and_validation() -> None:
    """Verify 3D coordinate stripping and self-intersection repair."""
    # 3D polygon
    poly_3d = Polygon([(0, 0, 10), (1, 0, 20), (1, 1, 30), (0, 1, 40), (0, 0, 10)])
    clean_2d, warnings = ensure_2d(poly_3d)
    assert not clean_2d.has_z
    assert any("Z dimension" in w for w in warnings)

    # Bowtie self-intersecting polygon (invalid)
    bowtie = Polygon([(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)])
    assert not bowtie.is_valid
    repaired, rep_warnings, is_valid = validate_and_repair(bowtie)
    assert is_valid is True
    assert repaired.is_valid
    assert any("repaired" in w for w in rep_warnings)


def test_polygon_measurement_and_hole_subtraction() -> None:
    """Verify polygon area calculation and inner hole subtraction."""
    # Solid 0.01 deg x 0.01 deg box near equator
    solid = Polygon([(0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01), (0, 0)])
    res_solid = measure_geometry(solid, "EPSG:4326")
    assert res_solid.status == "OK"
    assert res_solid.area_m2 is not None and res_solid.area_m2 > 1_000_000
    assert res_solid.perimeter_m is not None
    assert res_solid.method == "laea_equal_area"
    # Geodesic agreement within 0.5%
    assert res_solid.geodesic_diff_pct is not None
    assert res_solid.geodesic_diff_pct < 0.5

    # Same box with a central hole of 0.005 x 0.005
    hole = [
        (0.0025, 0.0025),
        (0.0075, 0.0025),
        (0.0075, 0.0075),
        (0.0025, 0.0075),
        (0.0025, 0.0025),
    ]
    with_hole = Polygon(
        shell=[(0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01), (0, 0)],
        holes=[hole],
    )
    res_hole = measure_geometry(with_hole, "EPSG:4326")
    assert res_hole.status == "OK"
    assert res_hole.area_m2 is not None
    # Area with hole must be ~75% of solid area
    ratio = res_hole.area_m2 / res_solid.area_m2
    assert 0.70 < ratio < 0.80


def test_linestring_measurement_and_utm_selection() -> None:
    """Verify LineString length and UTM vs LAEA selection."""
    # Short line in UTM zone 31
    line = LineString([(0.0, 50.0), (0.01, 50.01)])
    res = measure_geometry(line, "EPSG:4326")
    assert res.status == "OK"
    assert res.length_m is not None and res.length_m > 0
    assert res.area_m2 is None
    assert res.method == "auto_utm"
    assert "32631" in (res.measurement_crs or "")
    assert res.geodesic_diff_pct is not None
    assert res.geodesic_diff_pct < 0.5

    # Wide line spanning > 6 degrees longitude -> triggers LAEA fallback
    wide_line = LineString([(0.0, 50.0), (8.0, 50.0)])
    res_wide = measure_geometry(wide_line, "EPSG:4326")
    assert res_wide.status == "OK"
    assert res_wide.method == "laea_fallback"
    assert "laea" in (res_wide.measurement_crs or "")


def test_unsupported_point_and_empty_geometries() -> None:
    """Verify Point / MultiPoint and empty geometries are handled gracefully."""
    pt = Point(10.0, 20.0)
    res_pt = measure_geometry(pt, "EPSG:4326")
    assert res_pt.status == "UNSUPPORTED"
    assert res_pt.area_m2 is None
    assert res_pt.length_m is None

    empty_poly = Polygon()
    res_empty = measure_geometry(empty_poly, "EPSG:4326")
    assert res_empty.status == "EMPTY"

    res_none = measure_geometry(None, "EPSG:4326")
    assert res_none.status == "EMPTY"


def test_geometry_collection_handling() -> None:
    """Verify recursive measurement of GeometryCollection."""
    poly = Polygon([(0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01), (0, 0)])
    line = LineString([(0, 0), (0.01, 0.01)])
    gc = GeometryCollection([poly, line])

    res = measure_geometry(gc, "EPSG:4326")
    assert res.status == "OK"
    assert res.area_m2 is not None and res.area_m2 > 0
    assert res.length_m is not None and res.length_m > 0
    assert any("Mixed" in w for w in res.warnings)


def test_sanitize_properties() -> None:
    """Verify properties with numpy types, NaN, datetimes serialize cleanly."""
    import datetime

    import numpy as np

    raw = {
        "str_val": "hello",
        "int_val": np.int64(42),
        "float_val": np.float64(3.1415),
        "nan_val": float("nan"),
        "dt_val": datetime.datetime(2026, 1, 1, 12, 0, 0),
        "bytes_val": b"utf-8 bytes",
    }
    clean = sanitize_properties(raw)
    assert clean["int_val"] == 42
    assert isinstance(clean["int_val"], int)
    assert clean["nan_val"] is None
    assert clean["dt_val"] == "2026-01-01T12:00:00"
    assert clean["bytes_val"] == "utf-8 bytes"
