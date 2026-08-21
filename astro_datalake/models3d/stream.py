"""Stream-to-disk download helpers for binary asset trees.

Same guarantees as core.cache (checksum sidecar per file, never re-download
what already matches, never overwrite raw), but the bytes go to disk as they
arrive: some of these files are >1 GB, so `response.content` is not an option.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from ..core.cache import is_cached, sidecar_path
from ..core.config import settings
from ..core.http import rate_limiter


@dataclass
class StreamReport:
    """What one stream fetcher did, reported back to `astro pull`."""

    key: str
    root: Path | None = None  # raw dir every `files[].path` is relative to
    downloaded: int = 0
    cached: int = 0
    bytes_written: int = 0
    files: list[dict] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def detail(self) -> str:
        parts = [
            f"{self.downloaded} file baru",
            f"{self.cached} ter-cache",
            f"{human_bytes(self.bytes_written)} ditulis",
        ]
        if self.skipped:
            parts.append(f"{len(self.skipped)} dilewati")
        if self.errors:
            parts.append(f"{len(self.errors)} gagal")
        return ", ".join(parts)


def human_bytes(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


def filename_from_url(url: str) -> str:
    name = unquote(urlparse(url).path.rsplit("/", 1)[-1])
    return name or "index.html"


async def stream_download(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    *,
    max_bytes: int | None = None,
    timeout: float = 300.0,
    attempts: int = 3,
) -> tuple[int, bool]:
    """Download `url` to `dest` with a .sha256 sidecar.

    Returns (bytes_written, was_cached). Raises on HTTP/transport failure after
    `attempts` tries; callers record the failure instead of aborting the batch.
    A file bigger than `max_bytes` (per Content-Length) raises `TooLarge` so the
    caller can log a skip rather than blowing the disk budget.
    """
    if is_cached(dest):
        return dest.stat().st_size, True

    import hashlib

    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            await rate_limiter.wait(url)
            async with client.stream("GET", url, timeout=timeout) as response:
                response.raise_for_status()
                length = response.headers.get("content-length")
                if max_bytes is not None and length and int(length) > max_bytes:
                    raise TooLarge(url, int(length), max_bytes)
                dest.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                written = 0
                partial = dest.with_name(dest.name + ".part")
                with partial.open("wb") as fh:
                    async for chunk in response.aiter_bytes(1024 * 256):
                        digest.update(chunk)
                        written += len(chunk)
                        if max_bytes is not None and written > max_bytes:
                            fh.close()
                            partial.unlink(missing_ok=True)
                            raise TooLarge(url, written, max_bytes)
                        fh.write(chunk)
                partial.replace(dest)
                sidecar_path(dest).write_text(f"{digest.hexdigest()}  {dest.name}\n")
                return written, False
        except TooLarge:
            raise
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                await asyncio.sleep(2 ** attempt)
    assert last_error is not None
    raise last_error


class TooLarge(RuntimeError):
    def __init__(self, url: str, size: int, limit: int):
        super().__init__(f"{url}: {human_bytes(size)} > batas {human_bytes(limit)}")
        self.url = url
        self.size = size
        self.limit = limit


def raw_dest(key: str, pull_date: str | None = None) -> Path:
    return settings.raw_dir / key / (pull_date or date.today().isoformat())


def write_manifest(dest: Path, report: StreamReport, *, source_key: str, source_url: str) -> None:
    """One manifest per pull: what was fetched, from where, and its checksum.

    Git-cloned trees keep no per-file sidecars (that would dirty the working
    tree), so the manifest is what `astro verify` checks them against.
    """
    payload = {
        "source": source_key,
        "source_url": source_url,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "file_count": len(report.files),
        "bytes_total": sum(f.get("size", 0) for f in report.files),
        "skipped": report.skipped,
        "errors": report.errors,
        "files": sorted(report.files, key=lambda f: f["path"]),
        **report.extra,
    }
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "manifest.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
