"""Astro Data Lake CLI.

  astro links                # tes semua link + laporan kesiapan download
  astro pull <source>        # tarik satu sumber
  astro pull --all --tier 1  # tarik semua sumber di tier tertentu
  astro build                # normalisasi raw -> processed + bikin struktur folder
  astro verify                # cek checksum, cek row count, cek folder kosong
  astro status                # ringkasan: sumber apa saja yang sudah ada, ukuran, tanggal
  astro manifest             # tulis ulang public/manifest.json (indeks download)
  astro doctor               # cek mesin ini (path, disk, paket, terminal, jaringan)
  astro tui                  # TUI interaktif (juga jalan di Termux)
  astro spacetrack ...       # query Space-Track sesuai dokumentasi API-nya
"""

from __future__ import annotations

from pathlib import Path

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
def links(
    source: str = typer.Argument(None, help="Check a single source key (default: all)."),
    tier: int = typer.Option(None, "--tier", help="Restrict to a tier: 1, 2, or 3.", min=1, max=3),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show every URL checked."),
    concurrency: int = typer.Option(4, "--concurrency", "-j", help="Parallel sources.", min=1, max=16),
) -> None:
    """Test every download link and report which sources are ready to pull."""
    from .commands import links as links_cmd

    links_cmd.run(source=source, tier=tier, verbose=verbose, concurrency=concurrency)


def _require_optional(*modules: str) -> None:
    """Fail with install instructions instead of a raw ImportError."""
    from ..core.optional import install_hint, missing_for

    missing = missing_for(*modules)
    if missing:
        for module in missing:
            typer.secho(install_hint(module), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)


@app.command()
def build() -> None:
    """Normalize raw data into the processed per-object/per-system folder tree."""
    _require_optional("polars", "numpy", "bs4")
    from .commands import build as build_cmd

    build_cmd.run()


@app.command()
def verify() -> None:
    """Verify checksums, row counts, empty folders, and JSON-schema conformance."""
    _require_optional("jsonschema")
    from .commands import verify as verify_cmd

    verify_cmd.run()


spacetrack_app = typer.Typer(
    help="Query Space-Track.org per its documented API (space-track.org/documentation#/api).",
    no_args_is_help=True,
)
app.add_typer(spacetrack_app, name="spacetrack")


@spacetrack_app.command("policy")
def spacetrack_policy() -> None:
    """Show presets, credential state, and the documented retrieval-rate status."""
    from .commands import spacetrack as st_cmd

    st_cmd.show_policy()


@spacetrack_app.command("query")
def spacetrack_query(
    class_name: str = typer.Argument(
        None, help="API class, e.g. gp, satcat, decay, cdm_public, boxscore."
    ),
    preset: str = typer.Option(None, "--preset", help="Use a documented preset query instead."),
    limit: int = typer.Option(None, "--limit", help="Cap the number of rows."),
    response_format: str = typer.Option("json", "--format", help="json|csv|xml|tle|3le|kvn|html."),
    norad: str = typer.Option(None, "--norad", help="NORAD id(s), comma-separated for one request."),
    predicate: list[str] = typer.Option(
        None, "--predicate", "-P", help="Extra filter as NAME=VALUE (repeatable), e.g. -P epoch=>now-1."
    ),
    orderby: str = typer.Option(None, "--orderby", help="Sort predicate, e.g. 'norad_cat_id asc'."),
    out: Path = typer.Option(None, "--out", help="Write the body to this file."),
    save_raw: bool = typer.Option(False, "--save", help="Store under data/raw/spacetrack/ with a checksum."),
    force: bool = typer.Option(False, "--force", help="Ignore the documented retrieval-rate guard."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the URL and stop."),
) -> None:
    """Run one Space-Track query and show, save, or write out the result."""
    if not class_name and not preset:
        typer.secho("Sebutkan CLASS atau --preset.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    from .commands import spacetrack as st_cmd

    st_cmd.run_query(
        class_name=class_name,
        preset=preset,
        limit=limit,
        response_format=response_format,
        norad=norad,
        predicate=predicate,
        orderby=orderby,
        out=out,
        save_raw=save_raw,
        force=force,
        dry_run=dry_run,
    )


@spacetrack_app.command("modeldef")
def spacetrack_modeldef(
    class_name: str = typer.Argument(..., help="API class to describe, e.g. gp."),
) -> None:
    """Print a class's predicate definitions (the API's own /modeldef)."""
    from .commands import spacetrack as st_cmd

    st_cmd.show_modeldef(class_name)


@app.command()
def doctor(
    skip_network: bool = typer.Option(
        False, "--offline", help="Skip the network reachability checks."
    ),
) -> None:
    """Check this machine (paths, disk, packages, terminal, network) — Termux included."""
    from .commands import doctor as doctor_cmd

    doctor_cmd.run(skip_network=skip_network)


@app.command()
def tui() -> None:
    """Open the interactive terminal UI (sources, links, pull, Space-Track)."""
    try:
        from ..tui import run as run_tui
    except ImportError as exc:  # pragma: no cover - depends on the install
        typer.secho(
            f"TUI needs the `textual` package: {exc}\n"
            "Install it with:  pip install textual   (or: uv sync)",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1) from exc

    run_tui()


@app.command()
def manifest(
    output: str = typer.Option(None, "--output", "-o", help="Tujuan file manifest."),
    check: bool = typer.Option(
        False, "--check", help="Jangan tulis; keluar 1 kalau manifest sudah basi."
    ),
) -> None:
    """Regenerate public/manifest.json (the download index) from the link registry."""
    from pathlib import Path

    from ..manifest import (
        NoSourceCheckoutError,
        default_manifest_path,
        manifest_is_current,
        write_manifest,
    )

    try:
        path = default_manifest_path() if output is None else Path(output)
    except NoSourceCheckoutError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
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
