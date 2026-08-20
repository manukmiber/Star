"""Fase 1: probe every registered source with a small request (HEAD or a
tiny/limited GET) to check liveness, before any real downloader is written.

Run with:  uv run python -m astro_datalake.probe

Writes results to data/_catalog/sources.json (url, retrieved_at, license,
status, http_status, error) and prints a live/dead summary table.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import httpx
from rich.console import Console
from rich.table import Table

from .core.config import settings
from .core.http import get, head
from .core.logging import setup_logging
from .sources.registry import SOURCES

console = Console()


async def probe_one(client: httpx.AsyncClient, key: str) -> dict:
    spec = SOURCES[key]
    started = asyncio.get_event_loop().time()
    result = {
        "key": key,
        "name": spec.name,
        "tier": spec.tier,
        "category": spec.category,
        "base_url": spec.base_url,
        "probe_url": spec.probe_url,
        "probe_method": spec.probe_method,
        "license": spec.license,
        "notes": spec.notes,
        "requires_credentials": spec.requires_credentials,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }
    if spec.requires_credentials:
        result.update(alive=None, http_status=None, error="skipped: requires credentials")
        return result
    try:
        fn = head if spec.probe_method == "HEAD" else get
        response = await fn(
            client, spec.probe_url, raise_for_status=False, timeout=spec.probe_timeout
        )
        elapsed = asyncio.get_event_loop().time() - started
        alive = response.status_code < 400
        result.update(
            alive=alive,
            http_status=response.status_code,
            elapsed_seconds=round(elapsed, 2),
            content_length=response.headers.get("content-length"),
            content_type=response.headers.get("content-type"),
            error=None if alive else f"HTTP {response.status_code}",
        )
    except Exception as exc:  # noqa: BLE001 - we want to record any probe failure
        result.update(alive=False, http_status=None, error=f"{type(exc).__name__}: {exc}")
    return result


async def probe_all() -> list[dict]:
    results = []
    async with httpx.AsyncClient(
        headers={"User-Agent": settings.user_agent}, follow_redirects=True
    ) as client:
        for key in sorted(SOURCES):
            results.append(await probe_one(client, key))
    return results


def render_summary(results: list[dict]) -> None:
    table = Table(title="Fase 1 — Probe Endpoint")
    table.add_column("Key")
    table.add_column("Tier", justify="right")
    table.add_column("Status")
    table.add_column("HTTP")
    table.add_column("Catatan")

    alive_count = dead_count = skipped_count = 0
    for r in results:
        if r["alive"] is None:
            status = "[dim]skip[/dim]"
            skipped_count += 1
        elif r["alive"]:
            status = "[green]hidup[/green]"
            alive_count += 1
        else:
            status = "[red]MATI[/red]"
            dead_count += 1
        table.add_row(
            r["key"], str(r["tier"]), status,
            str(r.get("http_status") or "-"), r.get("error") or "",
        )
    console.print(table)
    console.print(
        f"\nHidup: {alive_count}   Mati: {dead_count}   "
        f"Skip (butuh kredensial): {skipped_count}   Total: {len(results)}"
    )


def main() -> None:
    setup_logging()
    settings.ensure_dirs()
    results = asyncio.run(probe_all())
    render_summary(results)

    out_path = settings.catalog_dir / "sources.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    console.print(f"\nHasil ditulis ke {out_path}")

    dead = [r for r in results if r["alive"] is False]
    if dead:
        console.print("\n[bold red]Endpoint mati (perlu dicatat di CHANGELOG.md / cari pengganti):[/bold red]")
        for r in dead:
            console.print(f"  - {r['key']}: {r['probe_url']} -> {r['error']}")


if __name__ == "__main__":
    main()
