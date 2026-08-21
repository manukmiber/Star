"""`astro links`: verify every download link and report readiness."""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table

from ...core.config import settings
from ...linkcheck import (
    VERDICT_BROKEN,
    VERDICT_NEEDS_CREDENTIALS,
    VERDICT_NO_PLAN,
    VERDICT_READY,
    VERDICT_SUSPECT,
    check_sources,
    summarize,
    write_report,
)
from ...sources.registry import SOURCES

console = Console()

VERDICT_STYLE = {
    VERDICT_READY: "[green]siap[/green]",
    VERDICT_SUSPECT: "[yellow]curiga[/yellow]",
    VERDICT_BROKEN: "[red]RUSAK[/red]",
    VERDICT_NEEDS_CREDENTIALS: "[cyan]butuh kredensial[/cyan]",
    VERDICT_NO_PLAN: "[dim]tanpa downloader[/dim]",
}


def run(
    source: str | None = None,
    tier: int | None = None,
    verbose: bool = False,
    concurrency: int = 4,
) -> None:
    keys = sorted(SOURCES)
    if source:
        if source not in SOURCES:
            typer.secho(f"Unknown source key: {source!r}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        keys = [source]
    elif tier is not None:
        keys = sorted(k for k, spec in SOURCES.items() if spec.tier == tier)

    settings.ensure_dirs()
    console.print(f"Mengecek link untuk {len(keys)} sumber (paralel {concurrency})...\n")

    done = 0

    def on_done(report) -> None:
        nonlocal done
        done += 1
        console.print(
            f"  [{done}/{len(keys)}] {report.key}: "
            f"{VERDICT_STYLE.get(report.verdict, report.verdict)} — {report.reason}"
        )

    reports = asyncio.run(check_sources(keys, concurrency=concurrency, progress=on_done))
    reports.sort(key=lambda r: (r.tier, r.key))

    table = Table(title="astro links — status tiap sumber")
    table.add_column("Key")
    table.add_column("Tier", justify="right")
    table.add_column("Link", justify="right")
    table.add_column("Status")
    table.add_column("Keterangan", overflow="fold")
    for report in reports:
        table.add_row(
            report.key,
            str(report.tier),
            f"{report.working_links}/{len(report.links)}",
            VERDICT_STYLE.get(report.verdict, report.verdict),
            report.reason,
        )
    console.print()
    console.print(table)

    if verbose:
        detail = Table(title="Detail tiap link")
        detail.add_column("Key")
        detail.add_column("HTTP", justify="right")
        detail.add_column("Tipe")
        detail.add_column("Detik", justify="right")
        detail.add_column("URL", overflow="fold")
        detail.add_column("Catatan", overflow="fold")
        for report in reports:
            for link in report.links:
                detail.add_row(
                    report.key,
                    str(link.http_status or "-"),
                    link.expected_kind,
                    str(link.elapsed_seconds or "-"),
                    link.checked_url,
                    ("[green]" if link.works else "[red]") + link.detail,
                )
        console.print(detail)

    counts = summarize(reports)
    out_path = write_report(reports)
    console.print(
        f"\n[green]{counts[VERDICT_READY]} siap didownload[/green]   "
        f"[yellow]{counts[VERDICT_SUSPECT]} curiga[/yellow]   "
        f"[red]{counts[VERDICT_BROKEN]} rusak[/red]   "
        f"[cyan]{counts[VERDICT_NEEDS_CREDENTIALS]} butuh kredensial[/cyan]   "
        f"[dim]{counts[VERDICT_NO_PLAN]} tanpa downloader[/dim]"
    )
    console.print(
        f"Link diperiksa: {counts['links_working']}/{counts['links_checked']} berfungsi.  "
        f"Laporan: {out_path}"
    )

    broken = [r for r in reports if r.verdict == VERDICT_BROKEN]
    if broken:
        console.print("\n[bold red]Perlu tindakan:[/bold red]")
        for report in broken:
            console.print(f"  - {report.key}: {report.reason}")
        raise typer.Exit(code=1)
