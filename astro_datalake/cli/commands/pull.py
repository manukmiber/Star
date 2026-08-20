"""`astro pull`: download raw data from one or more sources.

Delegates the actual HTTP work to astro_datalake.downloaders.DOWNLOAD_PLAN
(built during Fase 2 against the live, verified endpoints from Fase 1).
A source with no plan entry is deliberately skipped — see notes on that
source in sources/registry.py for why (needs credentials, no clean bulk
endpoint found, or deferred to a later tier).
"""

from __future__ import annotations

import asyncio
from datetime import date

import typer
from rich.console import Console
from rich.table import Table

from ...core.cache import is_cached, write_raw
from ...core.config import settings
from ...core.http import make_client
from ...downloaders import DOWNLOAD_PLAN
from ...sources.registry import SOURCES

console = Console()


async def _pull_one(client, key: str) -> dict:
    fetcher = DOWNLOAD_PLAN.get(key)
    if fetcher is None:
        return {"key": key, "status": "skipped", "detail": "belum ada download plan (lihat notes di registry.py)"}

    try:
        files = await fetcher(client)
    except Exception as exc:  # noqa: BLE001 - report any fetch failure, don't crash the batch
        return {"key": key, "status": "error", "detail": f"{type(exc).__name__}: {exc}"}

    today = date.today().isoformat()
    written = cached = 0
    for filename, content in files:
        raw_path = settings.raw_dir / key / today / filename
        if is_cached(raw_path):
            cached += 1
            continue
        write_raw(raw_path, content)
        written += 1
    return {
        "key": key,
        "status": "ok",
        "detail": f"{written} file baru, {cached} sudah ter-cache (checksum cocok)",
    }


async def _pull_many(keys: list[str]) -> list[dict]:
    results = []
    async with make_client() as client:
        for key in keys:
            console.print(f"[cyan]→ {key}[/cyan]")
            result = await _pull_one(client, key)
            results.append(result)
            color = {"ok": "green", "skipped": "yellow", "error": "red"}[result["status"]]
            console.print(f"  [{color}]{result['status']}[/{color}]: {result['detail']}")
    return results


def run(source: str | None, all_sources: bool, tier: int | None) -> None:
    if source:
        if source not in SOURCES:
            typer.secho(f"Unknown source key: {source!r}", fg=typer.colors.RED, err=True)
            typer.echo("Run `astro status` to see registered source keys.")
            raise typer.Exit(code=1)
        keys = [source]
    elif all_sources:
        if tier is None:
            typer.secho(
                "--all butuh --tier (agar tidak menebak tier mana yang mau ditarik).",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=1)
        keys = sorted(k for k, spec in SOURCES.items() if spec.tier == tier)
    else:
        typer.secho("Sebutkan source key, atau pakai --all --tier N.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    settings.ensure_dirs()
    results = asyncio.run(_pull_many(keys))

    table = Table(title="Ringkasan astro pull")
    table.add_column("Key")
    table.add_column("Status")
    table.add_column("Detail")
    for r in results:
        table.add_row(r["key"], r["status"], r["detail"])
    console.print(table)

    ok = sum(1 for r in results if r["status"] == "ok")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    errors = sum(1 for r in results if r["status"] == "error")
    console.print(f"\n{ok} berhasil, {skipped} dilewati (belum ada plan), {errors} error.")
    if errors:
        raise typer.Exit(code=1)
