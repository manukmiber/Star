"""Raw-file caching: checksum-based skip so we never re-download or overwrite raw data."""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sidecar_path(raw_path: Path) -> Path:
    return raw_path.with_name(raw_path.name + ".sha256")


def read_cached_checksum(raw_path: Path) -> str | None:
    sidecar = sidecar_path(raw_path)
    if not sidecar.exists():
        return None
    return sidecar.read_text().split()[0].strip()


def is_cached(raw_path: Path) -> bool:
    """True if raw_path exists and its checksum sidecar matches the file on disk."""
    if not raw_path.exists():
        return False
    recorded = read_cached_checksum(raw_path)
    if recorded is None:
        return False
    return sha256_of_file(raw_path) == recorded


def write_raw(raw_path: Path, data: bytes) -> str:
    """Write raw bytes + a .sha256 sidecar. Never call this if is_cached() is True."""
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(data)
    checksum = sha256_of_bytes(data)
    sidecar_path(raw_path).write_text(f"{checksum}  {raw_path.name}\n")
    return checksum
