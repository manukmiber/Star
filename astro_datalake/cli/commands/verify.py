"""`astro verify`: checksum, row-count, empty-folder, and JSON-schema checks.

Not yet implemented — added in Fase 4, after the processed tree exists (Fase 3).
"""

from __future__ import annotations

import typer


def run() -> None:
    typer.secho(
        "verify: belum diimplementasikan. Ditambahkan di Fase 4 setelah "
        "struktur folder processed dibangun (Fase 3).",
        fg=typer.colors.YELLOW,
    )
    raise typer.Exit(code=1)
