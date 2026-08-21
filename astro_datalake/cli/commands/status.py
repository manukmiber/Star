"""`astro status`: local-only summary of what's been pulled, sizes, and dates.

Does not touch the network.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from ...core.config import settings
from ...sources.registry import SOURCES

console = Console()


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}PB"


def run() -> None:
    table = Table(title="Astro Data Lake — Status Sumber")
    table.add_column("Key")
    table.add_column("Tier", justify="right")
    table.add_column("Kategori")
    table.add_column("Terpull?")
    table.add_column("Ukuran raw", justify="right")
    table.add_column("Terakhir diambil")

    total_size = 0
    pulled_count = 0
    for key, spec in sorted(SOURCES.items(), key=lambda kv: (kv[1].tier, kv[0])):
        raw_path = settings.raw_dir / key
        size = _dir_size(raw_path)
        total_size += size
        pulled = size > 0
        if pulled:
            pulled_count += 1
        status_label = "[green]ya[/green]" if pulled else "[dim]belum[/dim]"

        if raw_path.exists():
            mtimes = [f.stat().st_mtime for f in raw_path.rglob("*") if f.is_file()]
            last = datetime.fromtimestamp(max(mtimes)).strftime("%Y-%m-%d %H:%M") if mtimes else "-"
        else:
            last = "-"

        table.add_row(key, str(spec.tier), spec.category, status_label, _human_size(size), last)

    console.print(table)
    console.print(
        f"\nSumber terpull: {pulled_count}/{len(SOURCES)}   "
        f"Total ukuran data/raw: {_human_size(total_size)}"
    )

    processed_dirs = [
        "solar_system", "stars", "multiple_systems", "exoplanets", "deep_sky", "models_3d",
    ]
    console.print("\n[bold]Struktur processed:[/bold]")
    for name in processed_dirs:
        p = settings.data_dir / name
        exists = p.exists() and any(p.iterdir()) if p.exists() else False
        console.print(f"  data/{name}/  {'[green]ada[/green]' if exists else '[dim]belum dibangun[/dim]'}")
