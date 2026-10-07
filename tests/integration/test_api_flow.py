"""Integration tests for the complete API lifecycle."""

import io
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
from fastapi.testclient import TestClient
from shapely.geometry import Polygon


def _make_zip_payload() -> bytes:
    """Create in-memory bytes for a shapefile zip with a polygon."""
    temp_dir = Path(tempfile.mkdtemp())
    shp_path = temp_dir / "sample.shp"
    gdf = gpd.GeoDataFrame(
        {
            "name": ["Site 1"],
            "geometry": [Polygon([(0, 0), (0.02, 0), (0.02, 0.02), (0, 0.02), (0, 0)])],
        },
        crs="EPSG:4326",
    )
    gdf.to_file(shp_path, driver="ESRI Shapefile")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for ext in (".shp", ".shx", ".dbf", ".prj"):
            f = temp_dir / f"sample{ext}"
            if f.exists():
                zf.write(f, arcname=f"sample{ext}")
    return buf.getvalue()


def _make_kml_payload() -> bytes:
    """Create in-memory bytes for a simple KML document."""
    kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Survey Line</name>
      <LineString>
        <coordinates>
          0.0,0.0,0 0.01,0.01,0
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>"""
    return kml.encode("utf-8")


def test_shapefile_full_lifecycle(client: TestClient) -> None:
    """Test full upload, status check, and measurement retrieval for Shapefile."""
    zip_bytes = _make_zip_payload()
    files = {"file": ("parcels.zip", zip_bytes, "application/zip")}

    # 1. Upload file
    upload_res = client.post("/api/files/", files=files)
    assert upload_res.status_code == 202
    upload_data = upload_res.json()
    assert "id" in upload_data
    file_id = upload_data["id"]
    assert upload_data["filename"] == "parcels.zip"

    # 2. Get file info
    info_res = client.get(f"/api/files/{file_id}/")
    assert info_res.status_code == 200
    info_data = info_res.json()
    assert info_data["id"] == file_id
    assert info_data["status"] == "COMPLETED"
    assert info_data["feature_count"] == 1
    assert "4326" in str(info_data["crs"])

    # 3. Get measurements
    meas_res = client.get(f"/api/files/{file_id}/measurements/")
    assert meas_res.status_code == 200
    meas_data = meas_res.json()
    assert meas_data["file_id"] == file_id
    assert meas_data["total"] == 1
    feature = meas_data["features"][0]
    assert feature["index"] == 0
    assert feature["geometry_type"] == "Polygon"
    assert feature["measurement_status"] == "OK"
    assert feature["measurements"]["area_m2"] > 0
    assert feature["measurements"]["perimeter_m"] > 0
    assert feature["method"] == "laea_equal_area"
    assert feature["geometry"] is not None


def test_kml_full_lifecycle(client: TestClient) -> None:
    """Test full upload, status check, and measurement retrieval for KML."""
    kml_bytes = _make_kml_payload()
    files = {"file": ("pipeline.kml", kml_bytes, "application/vnd.google-earth.kml+xml")}

    upload_res = client.post("/api/files/", files=files)
    assert upload_res.status_code == 202
    file_id = upload_res.json()["id"]

    info_res = client.get(f"/api/files/{file_id}/")
    assert info_res.status_code == 200
    assert info_res.json()["status"] == "COMPLETED"
    assert info_res.json()["crs"] == "EPSG:4326"

    meas_res = client.get(f"/api/files/{file_id}/measurements/")
    assert meas_res.status_code == 200
    meas_data = meas_res.json()
    assert meas_data["total"] >= 1
    feat = meas_data["features"][0]
    assert feat["geometry_type"] == "LineString"
    assert feat["measurements"]["length_m"] > 0
    assert feat["method"] == "auto_utm"


def test_pagination_and_geometry_exclusion(client: TestClient) -> None:
    """Verify limit, offset, and include_geometry query params."""
    zip_bytes = _make_zip_payload()
    upload_res = client.post(
        "/api/files/", files={"file": ("test.zip", zip_bytes, "application/zip")}
    )
    file_id = upload_res.json()["id"]

    # Test include_geometry=false
    no_geom_res = client.get(f"/api/files/{file_id}/measurements/?include_geometry=false")
    assert no_geom_res.status_code == 200
    assert no_geom_res.json()["features"][0]["geometry"] is None

    # Test offset beyond total
    offset_res = client.get(f"/api/files/{file_id}/measurements/?offset=10")
    assert offset_res.status_code == 200
    assert len(offset_res.json()["features"]) == 0


def test_api_error_responses(client: TestClient) -> None:
    """Verify structured error responses for missing file and invalid format."""
    # 404 for unknown file
    fake_id = "00000000-0000-0000-0000-000000000000"
    res_404 = client.get(f"/api/files/{fake_id}/")
    assert res_404.status_code == 404
    assert res_404.json()["error"]["code"] == "NOT_FOUND"

    meas_404 = client.get(f"/api/files/{fake_id}/measurements/")
    assert meas_404.status_code == 404
    assert meas_404.json()["error"]["code"] == "NOT_FOUND"

    # 415 for unsupported format
    unsupported_res = client.post(
        "/api/files/", files={"file": ("document.pdf", b"fake pdf content", "application/pdf")}
    )
    assert unsupported_res.status_code == 415
    assert unsupported_res.json()["error"]["code"] == "UNSUPPORTED_FORMAT"

    # 422 for corrupt zip
    corrupt_res = client.post(
        "/api/files/", files={"file": ("corrupt.zip", b"NOT A ZIP", "application/zip")}
    )
    assert corrupt_res.status_code == 422
    assert corrupt_res.json()["error"]["code"] == "INVALID_ARCHIVE"
