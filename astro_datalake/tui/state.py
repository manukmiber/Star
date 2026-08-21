"""Shared, framework-free state for the TUI.

Keeping the data model out of the widget code means the same logic is
testable without spinning up a terminal, and the TUI stays a thin view over
the CLI's own machinery (registry, downloaders, linkcheck, cache).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..core.config import settings
from ..downloaders import DOWNLOAD_PLAN, declared_requests
from ..sources import spacetrack as st
from ..sources.registry import SOURCES, SourceSpec


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}PB"


def dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


@dataclass
class SourceRow:
    """One row of the sources table: registry facts + what's on disk."""

    spec: SourceSpec
    raw_bytes: int = 0
    last_pull: datetime | None = None
    link_verdict: str = ""
    link_reason: str = ""
    selected: bool = False

    @property
    def key(self) -> str:
        return self.spec.key

    @property
    def has_downloader(self) -> bool:
        return DOWNLOAD_PLAN.get(self.spec.key) is not None

    @property
    def request_count(self) -> int:
        if self.spec.key == "spacetrack":
            from ..downloaders import SPACETRACK_REQUESTS

            return len(SPACETRACK_REQUESTS)
        return len(declared_requests(self.spec.key))

    @property
    def pulled(self) -> bool:
        return self.raw_bytes > 0

    @property
    def readiness(self) -> str:
        """Short status word shown in the table."""
        if self.spec.requires_credentials and not self.has_downloader:
            return "kredensial"
        if not self.has_downloader:
            return "manual"
        if self.pulled:
            return "terpull"
        return "siap"


@dataclass
class AppState:
    """Everything the TUI shows, refreshed from disk on demand."""

    rows: dict[str, SourceRow] = field(default_factory=dict)
    last_link_check: datetime | None = None

    def load(self) -> None:
        for key, spec in SOURCES.items():
            row = self.rows.get(key) or SourceRow(spec=spec)
            row.spec = spec
            raw_path = settings.raw_dir / key
            row.raw_bytes = dir_size(raw_path)
            mtimes = (
                [f.stat().st_mtime for f in raw_path.rglob("*") if f.is_file()]
                if raw_path.exists()
                else []
            )
            row.last_pull = (
                datetime.fromtimestamp(max(mtimes), tz=timezone.utc) if mtimes else None
            )
            self.rows[key] = row
        self._load_link_report()

    def _load_link_report(self) -> None:
        import json

        report_path = settings.catalog_dir / "link-check.json"
        if not report_path.exists():
            return
        try:
            payload = json.loads(report_path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        checked_at = payload.get("checked_at")
        if checked_at:
            try:
                self.last_link_check = datetime.fromisoformat(checked_at)
            except ValueError:
                self.last_link_check = None
        for entry in payload.get("sources", []):
            row = self.rows.get(entry.get("key", ""))
            if row is not None:
                row.link_verdict = entry.get("verdict", "")
                row.link_reason = entry.get("reason", "")

    # -- filtering / selection ------------------------------------------
    def filtered(
        self, *, tier: int | None = None, query: str = "", only_ready: bool = False
    ) -> list[SourceRow]:
        query = query.strip().lower()
        rows = []
        for row in self.rows.values():
            if tier is not None and row.spec.tier != tier:
                continue
            if only_ready and not row.has_downloader:
                continue
            if query and query not in f"{row.key} {row.spec.name} {row.spec.category}".lower():
                continue
            rows.append(row)
        return sorted(rows, key=lambda r: (r.spec.tier, r.key))

    @property
    def selected_keys(self) -> list[str]:
        return sorted(key for key, row in self.rows.items() if row.selected)

    def clear_selection(self) -> None:
        for row in self.rows.values():
            row.selected = False

    # -- summary ---------------------------------------------------------
    def totals(self) -> dict[str, int]:
        rows = list(self.rows.values())
        return {
            "sources": len(rows),
            "ready": sum(1 for r in rows if r.has_downloader),
            "pulled": sum(1 for r in rows if r.pulled),
            "bytes": sum(r.raw_bytes for r in rows),
            "links": sum(r.request_count for r in rows),
            "selected": len(self.selected_keys),
        }


def spacetrack_status() -> dict[str, object]:
    """Credential + retrieval-policy snapshot for the Space-Track panel."""
    ledger = st.RetrievalLedger(settings.raw_dir / "spacetrack" / "retrieval-ledger.json")
    classes = []
    for name, (description, factory) in st.PRESETS.items():
        allowed, reason = ledger.check(name)
        last = ledger.last_pull(name)
        classes.append(
            {
                "class": name,
                "description": description,
                "allowed": allowed,
                "reason": reason,
                "last_pull": last,
                "url": factory().url(),
            }
        )
    creds = st.credentials_from_env()
    return {
        "has_credentials": creds is not None,
        "identity": creds[0] if creds else None,
        "classes": classes,
        "ledger_path": ledger.path,
    }
