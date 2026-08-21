"""`astro doctor`: check that this machine can actually run the pipeline.

Written mostly for Termux, where the failure modes are specific: a Python
built without a compiler toolchain, a terminal too narrow for the TUI, no
storage permission, or DNS that only works on Wi-Fi.
"""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import sys
from pathlib import Path

import httpx
from rich.console import Console
from rich.table import Table

from ...core.config import on_termux, settings
from ...core.optional import OPTIONAL_MODULES, install_hint, is_available
from ...sources import spacetrack as st

console = Console()

OK = "[green]ok[/green]"
WARN = "[yellow]perhatian[/yellow]"
BAD = "[red]masalah[/red]"

#: One host per major data provider, for a fast reachability check.
NETWORK_TARGETS = [
    ("JPL SSD", "https://ssd-api.jpl.nasa.gov/sentry.api"),
    ("CelesTrak", "https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=json"),
    ("CDS VizieR", "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync?request=doQuery&lang=adql&format=csv&query=select+top+1+*+from+%22B%2Fwds%2Fwds%22"),
    ("Space-Track", "https://www.space-track.org/"),
]


async def _check_network() -> list[tuple[str, str, str]]:
    rows = []
    async with httpx.AsyncClient(
        headers={"User-Agent": settings.user_agent}, follow_redirects=True, timeout=20.0
    ) as client:
        for name, url in NETWORK_TARGETS:
            try:
                response = await client.get(url)
                status = OK if response.status_code < 400 else WARN
                rows.append((f"Jaringan: {name}", status, f"HTTP {response.status_code}"))
            except Exception as exc:  # noqa: BLE001 - any failure is the finding
                rows.append((f"Jaringan: {name}", BAD, f"{type(exc).__name__}: {exc}"))
    return rows


def run(skip_network: bool = False) -> None:
    rows: list[tuple[str, str, str]] = []

    version = sys.version_info
    rows.append(
        (
            "Python",
            OK if version >= (3, 11) else BAD,
            f"{platform.python_version()} ({sys.executable})",
        )
    )
    rows.append(
        (
            "Platform",
            OK,
            f"{platform.system()} {platform.machine()}"
            + (" [bold]— Termux terdeteksi[/bold]" if on_termux() else ""),
        )
    )

    root: Path = settings.project_root
    try:
        settings.ensure_dirs()
        probe = settings.data_dir / ".doctor-write-test"
        probe.write_text("ok")
        probe.unlink()
        write_status, write_detail = OK, f"{root} (bisa ditulis)"
    except OSError as exc:
        write_status, write_detail = BAD, f"{root} tidak bisa ditulis: {exc}"
    rows.append(("Folder data", write_status, write_detail))

    try:
        usage = shutil.disk_usage(root)
        free_gb = usage.free / 1024**3
        disk_status = OK if free_gb > 5 else (WARN if free_gb > 1 else BAD)
        rows.append(
            (
                "Ruang disk",
                disk_status,
                f"{free_gb:.1f} GB kosong dari {usage.total / 1024**3:.1f} GB "
                "(tier 2 butuh ~20 GB)",
            )
        )
    except OSError as exc:
        rows.append(("Ruang disk", WARN, str(exc)))

    for module, (extra, purpose) in OPTIONAL_MODULES.items():
        if is_available(module):
            rows.append((f"Paket {module}", OK, purpose))
        else:
            hint = install_hint(module).replace("\n", "  ")
            rows.append((f"Paket {module}", WARN, hint))

    size = shutil.get_terminal_size(fallback=(80, 24))
    if size.columns >= 80:
        term_status, term_detail = OK, f"{size.columns}x{size.lines} — layout lebar"
    elif size.columns >= 40:
        term_status, term_detail = (
            OK,
            f"{size.columns}x{size.lines} — TUI pakai layout sempit (mode HP)",
        )
    else:
        term_status, term_detail = (
            WARN,
            f"{size.columns}x{size.lines} — terlalu sempit, perkecil font Termux",
        )
    rows.append(("Terminal", term_status, term_detail))
    rows.append(
        (
            "TERM",
            OK if os.environ.get("TERM") else WARN,
            os.environ.get("TERM") or "belum diset (coba: export TERM=xterm-256color)",
        )
    )

    creds = st.credentials_from_env()
    rows.append(
        (
            "Kredensial Space-Track",
            OK if creds else WARN,
            f"identity: {creds[0]}"
            if creds
            else f"belum diset ({st.ENV_IDENTITY} / {st.ENV_PASSWORD}) — sumber ini dilewati",
        )
    )

    if not skip_network:
        rows.extend(asyncio.run(_check_network()))

    table = Table(title="astro doctor")
    table.add_column("Pemeriksaan")
    table.add_column("Status")
    table.add_column("Detail", overflow="fold")
    for name, status, detail in rows:
        table.add_row(name, status, detail)
    console.print(table)

    problems = sum(1 for _, status, _ in rows if status == BAD)
    warnings = sum(1 for _, status, _ in rows if status == WARN)
    if problems:
        console.print(f"\n[red]{problems} masalah[/red], {warnings} perhatian.")
    elif warnings:
        console.print(f"\n[yellow]{warnings} perhatian[/yellow], tidak ada masalah fatal.")
    else:
        console.print("\n[green]Semua pemeriksaan lolos.[/green]")
