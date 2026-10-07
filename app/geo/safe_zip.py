"""Safe zip archive extraction preventing zip-slip and zip-bombs.

Pure Python module: No FastAPI or database imports.
"""

import os
import zipfile
from pathlib import Path

from app.core.exceptions import InvalidArchiveError

ALLOWED_EXTENSIONS = {".shp", ".shx", ".dbf", ".prj", ".cpg"}
MAX_COMPRESSION_RATIO = 100.0


def extract_safe_shapefile_zip(
    zip_path: Path,
    target_dir: Path,
    max_members: int = 1000,
    max_uncompressed_bytes: int = 250 * 1024 * 1024,
) -> list[Path]:
    """Safely extracts shapefile components from a zip archive.

    Guarantees:
    - Never uses extractall().
    - Defense against Zip-Slip: sanitizes basenames and guarantees targets remain within target_dir.
    - Defense against Zip-Bombs: enforces max member count, max uncompressed size,
      and compression ratio cap.
    - Normalizes case-insensitive extensions (.SHP -> .shp).
    - Extracts nested folder members safely into target_dir.

    Returns:
        list[Path]: List of extracted .shp file paths found in archive.
    """
    if not zipfile.is_zipfile(zip_path):
        raise InvalidArchiveError("Uploaded file is not a valid ZIP archive.")

    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            infolist = archive.infolist()

            if len(infolist) > max_members:
                raise InvalidArchiveError(
                    f"Archive exceeds maximum member limit: {len(infolist)} > {max_members}"
                )

            total_uncompressed = 0
            total_compressed = 0

            # Pre-flight check on zip members
            for member in infolist:
                if member.is_dir():
                    continue

                total_uncompressed += member.file_size
                total_compressed += member.compress_size

                if total_uncompressed > max_uncompressed_bytes:
                    max_mb = max_uncompressed_bytes // (1024 * 1024)
                    raise InvalidArchiveError(
                        f"Uncompressed archive size exceeds limit ({max_mb} MB)."
                    )

            if total_compressed > 0:
                ratio = total_uncompressed / total_compressed
                if ratio > MAX_COMPRESSION_RATIO:
                    raise InvalidArchiveError(
                        f"Suspicious compression ratio ({ratio:.1f}x > {MAX_COMPRESSION_RATIO}x)."
                    )

            target_dir.mkdir(parents=True, exist_ok=True)
            extracted_shp_paths: list[Path] = []

            # Safe extraction loop
            for member in infolist:
                if member.is_dir():
                    continue

                filename = os.path.basename(member.filename)
                if not filename:
                    continue

                stem, ext = os.path.splitext(filename)
                ext_lower = ext.lower()

                if ext_lower not in ALLOWED_EXTENSIONS:
                    # Ignore non-shapefile files (e.g. .DS_Store, Thumbs.db, readme.txt)
                    continue

                # Sanitize target path - must be strictly inside target_dir
                safe_name = f"{stem}{ext_lower}"
                out_path = (target_dir / safe_name).resolve()
                if not str(out_path).startswith(str(target_dir.resolve())):
                    raise InvalidArchiveError(
                        f"Zip-slip directory traversal detected in: {member.filename}"
                    )

                # Extract file member safely
                with archive.open(member) as source, open(out_path, "wb") as target:
                    while chunk := source.read(1024 * 1024):
                        target.write(chunk)

                if ext_lower == ".shp":
                    extracted_shp_paths.append(out_path)

            return extracted_shp_paths

    except zipfile.BadZipFile as err:
        raise InvalidArchiveError(f"Corrupted or invalid zip archive: {err}") from err
