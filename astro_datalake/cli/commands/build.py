"""`astro build`: normalize raw data into the processed folder tree.

Runs every builder in astro_datalake/build/ in order (solar system, stars,
exoplanets, multiple systems, small bodies, artificial satellites, deep
sky), then the _catalog/ builders (master_index, sources.json, crosswalk,
schema). Idempotent: builders always overwrite processed/ from raw/, never
the other way around, so this is always safe to re-run.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ...core.config import settings

console = Console()

BUILDERS = [
    ("solar_system", "solar_system", "solar_system"),
    ("stars", "stars", "stars"),
    ("exoplanets", "exoplanets", "exoplanets"),
    ("multiple_systems", "multiple_systems", "multiple_systems"),
    ("small_bodies", "small_bodies", "solar_system/small_bodies"),
    ("satellites", "artificial_satellites", "solar_system/artificial_satellites"),
    ("deep_sky", "deep_sky", "deep_sky"),
]


def run() -> None:
    from ...build import catalog as catalog_builder

    settings.ensure_dirs()
    table = Table(title="Ringkasan astro build")
    table.add_column("Kategori")
    table.add_column("Objek")
    table.add_column("Catatan")

    for module_name, _label, out_subdir in BUILDERS:
        import importlib

        module = importlib.import_module(f"astro_datalake.build.{module_name}")
        out_dir = settings.data_dir / out_subdir
        console.print(f"[cyan]→ {module_name}[/cyan]")
        report = module.build(settings.raw_dir, out_dir)
        table.add_row(report.category, str(report.object_count), "; ".join(report.warnings) or "-")

    console.print(f"[cyan]→ _catalog[/cyan]")
    result = catalog_builder.build(settings.raw_dir, settings.data_dir)
    table.add_row("_catalog", str(sum(result["index_counts"].values())), f"crosswalk: {result['crosswalk_rows']} baris")

    console.print(table)
