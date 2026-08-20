"""`astro pull`: download raw data from one or more sources.

Not yet implemented — this is Fase 0 (scaffold). Fase 1 probes every
endpoint in the registry first; Fase 2 wires up the actual per-source
downloaders on top of core.http / core.cache.
"""

from __future__ import annotations

import typer

from ...sources.registry import SOURCES


def run(source: str | None, all_sources: bool, tier: int | None) -> None:
    if source and source not in SOURCES:
        typer.secho(f"Unknown source key: {source!r}", fg=typer.colors.RED, err=True)
        typer.echo("Run `astro status` to see registered source keys.")
        raise typer.Exit(code=1)

    typer.secho(
        "pull: belum diimplementasikan. Registry sumber sudah terdaftar "
        f"({len(SOURCES)} sumber), tapi downloader per-sumber baru ditambahkan "
        "di Fase 2 setelah probing endpoint (Fase 1) selesai.",
        fg=typer.colors.YELLOW,
    )
    raise typer.Exit(code=1)
