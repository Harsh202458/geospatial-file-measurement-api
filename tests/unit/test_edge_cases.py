"""Hardening and edge cases verification tests."""

import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, MultiPoint, MultiPolygon, Polygon

from app.geo.measure import measure_geometry
from app.geo.readers.shapefile import ShapefileReader


def test_multipolygon_area_sum() -> None:
    """Verify MultiPolygon area matches sum of parts."""
    poly1 = Polygon([(0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01), (0, 0)])
    poly2 = Polygon([(0.02, 0.02), (0.03, 0.02), (0.03, 0.03), (0.02, 0.03), (0.02, 0.02)])
    multi_poly = MultiPolygon([poly1, poly2])

    res1 = measure_geometry(poly1, "EPSG:4326")
    res2 = measure_geometry(poly2, "EPSG:4326")
    res_multi = measure_geometry(multi_poly, "EPSG:4326")

    assert res_multi.status == "OK"
    assert res1.area_m2 is not None and res2.area_m2 is not None and res_multi.area_m2 is not None
    expected_sum = res1.area_m2 + res2.area_m2
    # Within 1% due to common centroid projection vs individual centroid
    assert abs(res_multi.area_m2 - expected_sum) / expected_sum < 0.01


def test_multilinestring_length_sum() -> None:
    """Verify MultiLineString length matches sum of parts."""
    line1 = LineString([(0, 0), (0.01, 0.01)])
    line2 = LineString([(0.02, 0.02), (0.03, 0.03)])
    multi_line = MultiLineString([line1, line2])

    res1 = measure_geometry(line1, "EPSG:4326")
    res2 = measure_geometry(line2, "EPSG:4326")
    res_multi = measure_geometry(multi_line, "EPSG:4326")

    assert res_multi.status == "OK"
    assert (
        res1.length_m is not None and res2.length_m is not None and res_multi.length_m is not None
    )
    expected_sum = res1.length_m + res2.length_m
    assert abs(res_multi.length_m - expected_sum) / expected_sum < 0.01


def test_multipoint_unsupported() -> None:
    """Verify MultiPoint returns UNSUPPORTED gracefully."""
    multi_pt = MultiPoint([(0, 0), (1, 1), (2, 2)])
    res = measure_geometry(multi_pt, "EPSG:4326")
    assert res.status == "UNSUPPORTED"
    assert res.area_m2 is None
    assert res.length_m is None


def test_missing_shx_auto_restore(test_temp_dir: Path) -> None:
    """Verify shapefile missing .shx index succeeds via SHAPE_RESTORE_SHX."""
    temp_dir = Path(tempfile.mkdtemp())
    shp_path = temp_dir / "test_no_shx.shp"
    gdf = gpd.GeoDataFrame(
        {"name": ["A"]},
        geometry=[Polygon([(0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01), (0, 0)])],
        crs="EPSG:4326",
    )
    gdf.to_file(shp_path, driver="ESRI Shapefile")

    dest_zip = test_temp_dir / "missing_shx.zip"
    with zipfile.ZipFile(dest_zip, "w") as zf:
        zf.write(shp_path, arcname="test_no_shx.shp")
        zf.write(temp_dir / "test_no_shx.dbf", arcname="test_no_shx.dbf")
        zf.write(temp_dir / "test_no_shx.prj", arcname="test_no_shx.prj")
        # Intentionally omit .shx

    reader = ShapefileReader()
    try:
        info = reader.get_dataset_info(dest_zip)
        assert info.feature_count == 1
        chunks = list(reader.read_chunks(dest_zip))
        assert len(chunks) == 1
        assert chunks[0][0].geometry_type == "Polygon"
    finally:
        reader.cleanup()


def test_performance_bulk_features_sanity() -> None:
    """Performance sanity check measuring 1,000 features in a single batch."""
    poly = Polygon([(0, 0), (0.005, 0), (0.005, 0.005), (0, 0.005), (0, 0)])
    results = [measure_geometry(poly, "EPSG:4326") for _ in range(1000)]
    assert len(results) == 1000
    assert all(r.status == "OK" for r in results)
