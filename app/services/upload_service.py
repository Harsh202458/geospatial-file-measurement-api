"""File upload validation, streaming persistence, and record creation."""

import uuid
from pathlib import Path
from typing import BinaryIO

from app.core.config import Settings
from app.core.exceptions import InvalidArchiveError, UnsupportedFormatError
from app.db.models import UploadedFile
from app.repositories.file_repository import FileRepository
from app.storage.local import LocalStorageService


class UploadService:
    """Orchestrates upload validation, disk writing, and file record persistence."""

    def __init__(
        self,
        file_repo: FileRepository,
        storage_service: LocalStorageService,
        settings: Settings,
    ) -> None:
        self.file_repo = file_repo
        self.storage_service = storage_service
        self.settings = settings

    def process_upload(
        self,
        stream: BinaryIO,
        filename: str,
    ) -> tuple[UploadedFile, Path]:
        """Validate format/magic bytes, stream to disk, and persist PENDING record.

        Returns:
            tuple[UploadedFile, Path]: (created_record, stored_file_path)
        """
        clean_filename = Path(filename).name
        ext = Path(clean_filename).suffix.lower()

        if ext == ".zip":
            file_format = "SHAPEFILE"
        elif ext == ".kml":
            file_format = "KML"
        else:
            raise UnsupportedFormatError(
                f"Unsupported file format '{ext}'. Must be a Shapefile (.zip) or KML (.kml)."
            )

        # Validate magic bytes by reading header preview
        header = stream.read(512)
        stream.seek(0)

        if file_format == "SHAPEFILE":
            # ZIP magic bytes: PK\x03\x04 or empty archive PK\x05\x06
            if not (header.startswith(b"PK\x03\x04") or header.startswith(b"PK\x05\x06")):
                raise InvalidArchiveError(
                    "Invalid archive signature. File is not a valid zip archive."
                )
        elif file_format == "KML":
            lower_header = header.lower()
            if not (b"<?xml" in lower_header or b"<kml" in lower_header):
                raise UnsupportedFormatError("File does not contain valid KML/XML markup.")

        # Assign unique ID
        file_id = str(uuid.uuid4())
        safe_storage_name = f"{file_id}_{clean_filename}"

        # Stream write to storage
        dest_path, size_bytes, sha256_hash = self.storage_service.save_stream(
            stream=stream,
            destination_name=safe_storage_name,
            max_bytes=self.settings.max_upload_bytes,
        )

        # Persist DB record
        record = self.file_repo.create(
            filename=clean_filename,
            file_format=file_format,
            size_bytes=size_bytes,
            sha256=sha256_hash,
            file_id=file_id,
        )

        return record, dest_path
