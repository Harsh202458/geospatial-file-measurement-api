"""KML file reader supporting multi-layer extraction and WGS84 standardization."""

from collections.abc import Iterator
from pathlib import Path

import pyogrio

from app.core.exceptions import UnreadableFileError
from app.geo.geometry import sanitize_properties
from app.geo.readers.base import DatasetInfo, NormalizedFeature


class KmlReader:
    """Reader for Keyhole Markup Language (.kml) files."""

    def __init__(self) -> None:
        pass

    def _get_layers(self, file_path: Path) -> list[str]:
        """Discover all layers/folders inside the KML file."""
        try:
            layers_info = pyogrio.list_layers(file_path)
            # list_layers returns array of shape (N, 2) where col 0 is layer name
            layer_names = [str(item[0]) for item in layers_info]
            return layer_names if layer_names else ["default"]
        except Exception as err:
            raise UnreadableFileError(f"Failed to inspect KML layers: {err}") from err

    def get_dataset_info(self, file_path: Path) -> DatasetInfo:
        """Inspect KML metadata across all layers."""
        layers = self._get_layers(file_path)
        total_features = 0

        for layer in layers:
            try:
                info = pyogrio.read_info(file_path, layer=layer)
                total_features += info.get("features", 0)
            except Exception:
                pass

        return DatasetInfo(
            feature_count=total_features,
            crs="EPSG:4326",  # Standard KML specification is always WGS84
            crs_assumed=False,
            layers=layers,
        )

    def read_chunks(
        self,
        file_path: Path,
        chunk_size: int = 1000,
    ) -> Iterator[list[NormalizedFeature]]:
        """Yield normalized features across all KML layers."""
        layers = self._get_layers(file_path)
        global_feature_index = 0

        for layer in layers:
            try:
                info = pyogrio.read_info(file_path, layer=layer)
                layer_total = info.get("features", 0)
            except Exception as err:
                raise UnreadableFileError(f"Cannot read layer '{layer}' from KML: {err}") from err

            skip = 0
            while skip < layer_total:
                try:
                    gdf = pyogrio.read_dataframe(
                        file_path,
                        layer=layer,
                        skip_features=skip,
                        max_features=chunk_size,
                    )
                except Exception as err:
                    raise UnreadableFileError(
                        f"Failed parsing features from KML layer '{layer}': {err}"
                    ) from err

                if len(gdf) == 0:
                    break

                chunk_features: list[NormalizedFeature] = []
                for _, row in gdf.iterrows():
                    geom = row.geometry
                    geom_type = (
                        geom.geom_type if geom is not None and not geom.is_empty else "Unknown"
                    )

                    prop_dict = {k: v for k, v in row.to_dict().items() if k != "geometry"}
                    clean_props = sanitize_properties(prop_dict)

                    feat = NormalizedFeature(
                        index=global_feature_index,
                        geometry_type=geom_type,
                        geometry=geom,
                        properties=clean_props,
                        source_crs="EPSG:4326",
                        layer=layer,
                    )
                    chunk_features.append(feat)
                    global_feature_index += 1

                yield chunk_features
                skip += chunk_size

    def cleanup(self) -> None:
        """No temporary disk cleanup needed for single-file KML."""
        pass
