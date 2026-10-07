"""Storage abstraction and local disk storage implementation."""

import hashlib
import shutil
from pathlib import Path
from typing import BinaryIO, Protocol

from app.core.exceptions import PayloadTooLargeError


class StorageInterface(Protocol):
    """Protocol for file storage backends."""

    def save_stream(
        self,
        stream: BinaryIO,
        destination_name: str,
        max_bytes: int,
    ) -> tuple[Path, int, str]:
        """Stream data to storage, enforcing byte limit and computing SHA256 hash.

        Returns:
            tuple[Path, int, str]: (absolute_file_path, total_size_bytes, sha256_hex)
        """
        ...

    def delete_file(self, file_path: Path) -> None:
        """Remove file from storage."""
        ...


class LocalStorageService:
    """Stores files on the local filesystem."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_stream(
        self,
        stream: BinaryIO,
        destination_name: str,
        max_bytes: int,
    ) -> tuple[Path, int, str]:
        """Stream data in 1MB chunks to disk, computing sha256 and enforcing byte limits."""
        dest_path = self.base_dir / destination_name
        hasher = hashlib.sha256()
        total_bytes = 0
        chunk_size = 1024 * 1024  # 1MB chunk

        try:
            with open(dest_path, "wb") as f_out:
                while True:
                    chunk = stream.read(chunk_size)
                    if not chunk:
                        break

                    total_bytes += len(chunk)
                    if total_bytes > max_bytes:
                        max_mb = max_bytes // (1024 * 1024)
                        raise PayloadTooLargeError(
                            f"File size exceeds maximum permitted upload limit ({max_mb} MB)."
                        )

                    hasher.update(chunk)
                    f_out.write(chunk)

            return dest_path, total_bytes, hasher.hexdigest()

        except Exception:
            # Clean up partial upload if writing failed or limit was exceeded
            if dest_path.exists():
                dest_path.unlink(missing_ok=True)
            raise

    def delete_file(self, file_path: Path) -> None:
        """Delete file safely."""
        try:
            if file_path.exists():
                file_path.unlink()
        except OSError:
            pass

    def cleanup_all(self) -> None:
        """Remove all files in storage directory (useful for testing)."""
        if self.base_dir.exists():
            shutil.rmtree(self.base_dir, ignore_errors=True)
            self.base_dir.mkdir(parents=True, exist_ok=True)
