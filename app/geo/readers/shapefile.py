"""Shapefile reader with safe archive extraction and component validation."""

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pyogrio

from app.core.exceptions import MissingComponentError, UnreadableFileError
from app.geo.crs import resolve_source_crs
from app.geo.geometry import sanitize_properties
from app.geo.readers.base import DatasetInfo, NormalizedFeature
from app.geo.safe_zip import extract_safe_shapefile_zip


class ShapefileReader:
    """Reader for ESRI Shapefile archives (.zip)."""

    def __init__(self, assume_wgs84_if_missing: bool = True) -> None:
        self.assume_wgs84 = assume_wgs84_if_missing
        self._temp_dir: Path | None = None
        self._extracted_shp_list: list[Path] = []

    def _ensure_extracted(self, file_path: Path) -> list[Path]:
        """Extract shapefile archive if not already done."""
        if self._extracted_shp_list and self._temp_dir and self._temp_dir.exists():
            return self._extracted_shp_list

        self._temp_dir = Path(tempfile.mkdtemp(prefix="shp_extract_"))
        shp_paths = extract_safe_shapefile_zip(file_path, self._temp_dir)

        if not shp_paths:
            raise MissingComponentError("Archive does not contain any .shp file.")

        self._extracted_shp_list = shp_paths
        return self._extracted_shp_list

    def get_dataset_info(self, file_path: Path) -> DatasetInfo:
        """Inspect shapefile components and read header metadata."""
        shp_paths = self._ensure_extracted(file_path)

        total_features = 0
        detected_crs = "EPSG:4326"
        crs_assumed = False
        layers: list[Path] = []

        for shp in shp_paths:
            layers.append(shp)
            dbf = shp.with_suffix(".dbf")
            if not dbf.exists():
                raise MissingComponentError(
                    f"Required component '{dbf.name}' is missing for shapefile '{shp.name}'."
                )

            # Auto-rebuild .shx index if missing
            shx = shp.with_suffix(".shx")
            if not shx.exists():
                os.environ["SHAPE_RESTORE_SHX"] = "YES"

            try:
                info = pyogrio.read_info(shp)
            except Exception as err:
                raise UnreadableFileError(f"Failed to read shapefile '{shp.name}': {err}") from err

            total_features += info.get("features", 0)

            # Inspect CRS / .prj
            prj = shp.with_suffix(".prj")
            declared_crs = info.get("crs")
            bounds = info.get("total_bounds")

            if not prj.exists() or not declared_crs:
                resolved, assumed = resolve_source_crs(
                    None,
                    bounds,
                    assume_wgs84_if_missing=self.assume_wgs84,
                )
                detected_crs = resolved
                crs_assumed = assumed
            else:
                resolved, assumed = resolve_source_crs(
                    str(declared_crs),
                    bounds,
                    assume_wgs84_if_missing=self.assume_wgs84,
                )
                detected_crs = resolved
                crs_assumed = assumed

        return DatasetInfo(
            feature_count=total_features,
            crs=detected_crs,
            crs_assumed=crs_assumed,
            layers=[p.stem for p in layers],
        )

    def read_chunks(
        self,
        file_path: Path,
        chunk_size: int = 1000,
    ) -> Iterator[list[NormalizedFeature]]:
        """Read features chunk by chunk across all shapefile layers."""
        shp_paths = self._ensure_extracted(file_path)
        global_feature_index = 0

        for shp in shp_paths:
            # Check encoding in .cpg file if present
            cpg_path = shp.with_suffix(".cpg")
            encoding = "utf-8"
            if cpg_path.exists():
                try:
                    encoding = cpg_path.read_text(encoding="utf-8").strip().lower()
                except Exception:
                    encoding = "latin-1"

            info = pyogrio.read_info(shp)
            total = info.get("features", 0)

            # Resolve CRS for this layer
            prj = shp.with_suffix(".prj")
            declared_crs = info.get("crs")
            bounds = info.get("total_bounds")
            layer_crs, _ = resolve_source_crs(
                str(declared_crs) if prj.exists() and declared_crs else None,
                bounds,
                assume_wgs84_if_missing=self.assume_wgs84,
            )

            skip = 0
            while skip < total:
                try:
                    gdf = pyogrio.read_dataframe(
                        shp,
                        skip_features=skip,
                        max_features=chunk_size,
                        encoding=encoding,
                    )
                except Exception:
                    # Fallback to latin-1 on encoding failures
                    gdf = pyogrio.read_dataframe(
                        shp,
                        skip_features=skip,
                        max_features=chunk_size,
                        encoding="latin-1",
                    )

                if len(gdf) == 0:
                    break

                chunk_features: list[NormalizedFeature] = []
                for _, row in gdf.iterrows():
                    geom = row.geometry
                    geom_type = (
                        geom.geom_type if geom is not None and not geom.is_empty else "Unknown"
                    )

                    # Collect non-geometry attributes as properties
                    prop_dict = {k: v for k, v in row.to_dict().items() if k != "geometry"}
                    clean_props = sanitize_properties(prop_dict)

                    feat = NormalizedFeature(
                        index=global_feature_index,
                        geometry_type=geom_type,
                        geometry=geom,
                        properties=clean_props,
                        source_crs=layer_crs,
                        layer=shp.stem,
                    )
                    chunk_features.append(feat)
                    global_feature_index += 1

                yield chunk_features
                skip += chunk_size

    def cleanup(self) -> None:
        """Remove temporary directory containing extracted shapefile components."""
        if self._temp_dir and self._temp_dir.exists():
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None
            self._extracted_shp_list = []
