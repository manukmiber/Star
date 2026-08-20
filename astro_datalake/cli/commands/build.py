"""`astro build`: normalize raw -> processed and build the per-object folder tree.

Not yet implemented — added in Fase 3, after Tier 1 raw data exists (Fase 2).
"""

from __future__ import annotations

import typer


def run() -> None:
    typer.secho(
        "build: belum diimplementasikan. Ditambahkan di Fase 3 setelah data "
        "Tier 1 tertarik (Fase 2).",
        fg=typer.colors.YELLOW,
    )
    raise typer.Exit(code=1)
