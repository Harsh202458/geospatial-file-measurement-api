"""Unit tests for safe_zip, ShapefileReader, and KmlReader."""

import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from app.core.exceptions import InvalidArchiveError, MissingComponentError, UnreadableFileError
from app.geo.readers.kml import KmlReader
from app.geo.readers.shapefile import ShapefileReader
from app.geo.safe_zip import extract_safe_shapefile_zip


def _create_sample_shp_zip(
    dest_zip: Path,
    include_shx: bool = True,
    include_prj: bool = True,
    include_dbf: bool = True,
) -> None:
    """Helper to programmatically generate a test shapefile zip archive."""
    temp_dir = Path(tempfile.mkdtemp(prefix="make_shp_"))
    shp_path = temp_dir / "test_parcels.shp"

    gdf = gpd.GeoDataFrame(
        {
            "id": [1, 2],
            "name": ["Parcel A", "Parcel B"],
            "geometry": [
                Polygon([(0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01), (0, 0)]),
                Polygon([(1, 1), (1.02, 1), (1.02, 1.02), (1, 1.02), (1, 1)]),
            ],
        },
        crs="EPSG:4326",
    )
    gdf.to_file(shp_path, driver="ESRI Shapefile")

    with zipfile.ZipFile(dest_zip, "w") as zf:
        zf.write(shp_path, arcname="test_parcels.shp")
        if include_dbf:
            zf.write(temp_dir / "test_parcels.dbf", arcname="test_parcels.dbf")
        if include_shx:
            zf.write(temp_dir / "test_parcels.shx", arcname="test_parcels.shx")
        if include_prj:
            zf.write(temp_dir / "test_parcels.prj", arcname="test_parcels.prj")


def test_safe_zip_valid_extraction(test_temp_dir: Path) -> None:
    """Verify safe extraction of valid shapefile zip."""
    zip_path = test_temp_dir / "valid.zip"
    _create_sample_shp_zip(zip_path)

    out_dir = test_temp_dir / "out_valid"
    shp_files = extract_safe_shapefile_zip(zip_path, out_dir)
    assert len(shp_files) == 1
    assert shp_files[0].name == "test_parcels.shp"


def test_safe_zip_corrupt_archive(test_temp_dir: Path) -> None:
    """Verify corrupted zip raises InvalidArchiveError."""
    bad_zip = test_temp_dir / "corrupted.zip"
    bad_zip.write_bytes(b"NOT A REAL ZIP FILE CONTENT")

    out_dir = test_temp_dir / "out_bad"
    with pytest.raises(InvalidArchiveError, match="not a valid ZIP"):
        extract_safe_shapefile_zip(bad_zip, out_dir)


def test_safe_zip_slip_traversal(test_temp_dir: Path) -> None:
    """Verify zip-slip path traversal is blocked."""
    evil_zip = test_temp_dir / "evil_slip.zip"
    with zipfile.ZipFile(evil_zip, "w") as zf:
        zf.writestr("../../etc/passwd.shp", b"dummy")

    out_dir = test_temp_dir / "out_slip"
    # Even if relative paths are inside member, basename sanitization prevents traversal,
    # or raises InvalidArchiveError if attempted.
    shp_files = extract_safe_shapefile_zip(evil_zip, out_dir)
    # The member was safely sanitized to out_dir / passwd.shp
    assert all(str(p).startswith(str(out_dir.resolve())) for p in shp_files)


def test_safe_zip_member_limit_bomb(test_temp_dir: Path) -> None:
    """Verify member count bomb protection."""
    bomb_zip = test_temp_dir / "bomb_members.zip"
    with zipfile.ZipFile(bomb_zip, "w") as zf:
        for i in range(15):
            zf.writestr(f"file_{i}.shp", b"test")

    out_dir = test_temp_dir / "out_bomb"
    with pytest.raises(InvalidArchiveError, match="exceeds maximum member limit"):
        extract_safe_shapefile_zip(bomb_zip, out_dir, max_members=10)


def test_shapefile_reader_flow(test_temp_dir: Path) -> None:
    """Verify reading valid shapefile chunks."""
    zip_path = test_temp_dir / "parcels.zip"
    _create_sample_shp_zip(zip_path)

    reader = ShapefileReader()
    try:
        info = reader.get_dataset_info(zip_path)
        assert info.feature_count == 2
        assert "4326" in info.crs
        assert info.crs_assumed is False

        chunks = list(reader.read_chunks(zip_path, chunk_size=1))
        assert len(chunks) == 2
        assert chunks[0][0].index == 0
        assert chunks[0][0].geometry_type == "Polygon"
        assert chunks[1][0].index == 1
        assert chunks[1][0].geometry_type == "Polygon"
    finally:
        reader.cleanup()


def test_shapefile_reader_missing_dbf(test_temp_dir: Path) -> None:
    """Verify missing .dbf component raises MissingComponentError."""
    zip_path = test_temp_dir / "no_dbf.zip"
    _create_sample_shp_zip(zip_path, include_dbf=False)

    reader = ShapefileReader()
    try:
        with pytest.raises(
            MissingComponentError, match="Required component 'test_parcels.dbf' is missing"
        ):
            reader.get_dataset_info(zip_path)
    finally:
        reader.cleanup()


def test_shapefile_reader_missing_prj_assumed(test_temp_dir: Path) -> None:
    """Verify missing .prj assumes EPSG:4326."""
    zip_path = test_temp_dir / "no_prj.zip"
    _create_sample_shp_zip(zip_path, include_prj=False)

    reader = ShapefileReader(assume_wgs84_if_missing=True)
    try:
        info = reader.get_dataset_info(zip_path)
        assert info.feature_count == 2
        assert info.crs == "EPSG:4326"
        assert info.crs_assumed is True
    finally:
        reader.cleanup()


def test_kml_reader_flow(test_temp_dir: Path) -> None:
    """Verify KmlReader parses simple KML documents."""
    kml_content = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Site A</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              0,0,0 1,0,0 1,1,0 0,1,0 0,0,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>Path B</name>
      <LineString>
        <coordinates>
          0,0,0 2,2,0
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>"""
    kml_file = test_temp_dir / "test_doc.kml"
    kml_file.write_text(kml_content, encoding="utf-8")

    reader = KmlReader()
    info = reader.get_dataset_info(kml_file)
    assert info.crs == "EPSG:4326"
    assert info.crs_assumed is False
    assert info.feature_count >= 1

    chunks = list(reader.read_chunks(kml_file, chunk_size=10))
    total_feats = sum(len(c) for c in chunks)
    assert total_feats >= 2
    reader.cleanup()


def test_kml_reader_corrupt(test_temp_dir: Path) -> None:
    """Verify corrupted KML raises UnreadableFileError."""
    bad_kml = test_temp_dir / "bad.kml"
    bad_kml.write_text("NOT VALID XML CONTENT AT ALL", encoding="utf-8")

    reader = KmlReader()
    with pytest.raises(UnreadableFileError):
        reader.get_dataset_info(bad_kml)
