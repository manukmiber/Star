"""Astro Data Lake CLI.

  astro pull <source>        # tarik satu sumber
  astro pull --all --tier 1  # tarik semua sumber di tier tertentu
  astro build                # normalisasi raw -> processed + bikin struktur folder
  astro verify                # cek checksum, cek row count, cek folder kosong
  astro status                # ringkasan: sumber apa saja yang sudah ada, ukuran, tanggal
  astro manifest              # tulis ulang public/manifest.json (indeks download)
"""

from __future__ import annotations

import typer

from ..core.config import settings
from ..core.logging import setup_logging

app = typer.Typer(help="Local astronomical data lake CLI.", no_args_is_help=True)


@app.callback()
def main() -> None:
    settings.ensure_dirs()
    setup_logging()


@app.command()
def pull(
    source: str = typer.Argument(None, help="Source key to pull (see `astro status`)."),
    all_sources: bool = typer.Option(
        False, "--all", help="Pull every source matching --tier (or all sources)."
    ),
    tier: int = typer.Option(
        None, "--tier", help="Restrict to a tier: 1, 2, or 3.", min=1, max=3
    ),
) -> None:
    """Pull raw data from one source, or all sources in a tier."""
    from .commands import pull as pull_cmd

    pull_cmd.run(source=source, all_sources=all_sources, tier=tier)


@app.command()
def build() -> None:
    """Normalize raw data into the processed per-object/per-system folder tree."""
    from .commands import build as build_cmd

    build_cmd.run()


@app.command()
def verify() -> None:
    """Verify checksums, row counts, empty folders, and JSON-schema conformance."""
    from .commands import verify as verify_cmd

    verify_cmd.run()


@app.command()
def manifest(
    output: str = typer.Option(None, "--output", "-o", help="Tujuan file manifest."),
    check: bool = typer.Option(
        False, "--check", help="Jangan tulis; keluar 1 kalau manifest sudah basi."
    ),
) -> None:
    """Regenerate public/manifest.json (the download index) from the link registry."""
    from pathlib import Path

    from ..manifest import default_manifest_path, manifest_is_current, write_manifest

    path = default_manifest_path() if output is None else Path(output)
    if check:
        if manifest_is_current(path):
            typer.secho(f"{path} is up to date.", fg=typer.colors.GREEN)
            return
        typer.secho(
            f"{path} is stale — regenerate with `astro manifest`.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)
    written = write_manifest(path)
    typer.secho(
        f"Wrote {written} ({written.stat().st_size:,} bytes)", fg=typer.colors.GREEN
    )


@app.command()
def status() -> None:
    """Summarize which sources have been pulled, their sizes, and last-pull dates."""
    from .commands import status as status_cmd

    status_cmd.run()


if __name__ == "__main__":
    app()
