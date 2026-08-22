"""`astro spacetrack`: talk to Space-Track.org directly.

Thin, honest wrapper over sources/spacetrack.py — every subcommand prints
the exact URL it will request before requesting it, so what the tool does is
checkable against https://www.space-track.org/documentation#/api.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

import typer
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table

from ...core.cache import write_raw
from ...core.config import settings
from ...sources import spacetrack as st

console = Console()


def _ledger() -> st.RetrievalLedger:
    return st.RetrievalLedger(settings.raw_dir / "spacetrack" / "retrieval-ledger.json")


def show_policy() -> None:
    """List the presets, their documented retrieval rate, and when each is due."""
    ledger = _ledger()
    creds = st.credentials_from_env()
    if creds:
        console.print(f"[green]Kredensial terpasang[/green] — identity: {creds[0]}\n")
    else:
        console.print(
            f"[yellow]Kredensial belum diset.[/yellow]\n"
            f"  export {st.ENV_IDENTITY}='email-akun-anda'\n"
            f"  export {st.ENV_PASSWORD}='password-anda'\n"
            "  Akun gratis: https://www.space-track.org/auth/createAccount\n"
        )

    table = Table(title="Space-Track — preset & batas pengambilan")
    table.add_column("Preset")
    table.add_column("Boleh sekarang?")
    table.add_column("Terakhir")
    table.add_column("Aturan", overflow="fold")
    for name, (description, factory) in st.PRESETS.items():
        allowed, reason = ledger.check(name)
        last = ledger.last_pull(name)
        table.add_row(
            name,
            "[green]ya[/green]" if allowed else "[yellow]belum[/yellow]",
            last.strftime("%Y-%m-%d %H:%M UTC") if last else "[dim]belum pernah[/dim]",
            reason,
        )
    console.print(table)
    console.print(
        "\n[dim]Klien menahan diri di bawah batas resmi: <30 permintaan/menit, "
        "<300/jam, jeda minimal 2 detik.[/dim]"
    )
    console.print(f"[dim]Ledger: {ledger.path}[/dim]")


def _build_query(
    class_name: str,
    limit: int | None,
    response_format: str,
    norad: str | None,
    predicate: list[str] | None,
    orderby: str | None,
) -> st.Query:
    predicates: dict[str, str] = {}
    if norad:
        predicates["norad_cat_id"] = norad
    for item in predicate or []:
        if "=" not in item:
            raise typer.BadParameter(f"--predicate harus berbentuk NAMA=NILAI, dapat {item!r}")
        name, value = item.split("=", 1)
        predicates[name.strip()] = value.strip()
    return st.Query(
        class_name=class_name,
        predicates=predicates,
        orderby=orderby,
        limit=limit,
        response_format=response_format,
    )


def run_query(
    class_name: str,
    preset: str | None = None,
    limit: int | None = None,
    response_format: str = "json",
    norad: str | None = None,
    predicate: list[str] | None = None,
    orderby: str | None = None,
    out: Path | None = None,
    save_raw: bool = False,
    force: bool = False,
    dry_run: bool = False,
) -> None:
    if preset:
        if preset not in st.PRESETS:
            raise typer.BadParameter(
                f"preset tak dikenal: {preset!r}. Pilihan: {', '.join(st.PRESETS)}"
            )
        spec = st.PRESETS[preset][1]()
        if limit is not None:
            spec.limit = limit
        if response_format != "json":
            spec.response_format = response_format
    else:
        spec = _build_query(class_name, limit, response_format, norad, predicate, orderby)

    url = spec.url()
    console.print(f"[cyan]GET[/cyan] {url}\n")
    if dry_run:
        console.print("[dim]--dry-run: tidak ada permintaan yang dikirim.[/dim]")
        return

    ledger = _ledger()
    allowed, reason = ledger.check(spec.class_name)
    if not allowed and not force:
        console.print(f"[yellow]Ditahan oleh aturan frekuensi resmi:[/yellow] {reason}")
        console.print("[dim]Pakai --force kalau anda yakin (risiko suspensi akun ada di anda).[/dim]")
        raise typer.Exit(code=2)

    creds = st.credentials_from_env()
    if creds is None:
        console.print(
            f"[red]Kredensial belum diset.[/red] Set {st.ENV_IDENTITY} dan {st.ENV_PASSWORD}."
        )
        raise typer.Exit(code=1)

    async def go() -> bytes:
        async with st.SpaceTrackClient(
            *creds, user_agent=settings.user_agent
        ) as client:
            response = await client.query(spec)
            return response.content

    try:
        content = asyncio.run(go())
    except st.SpaceTrackError as exc:
        console.print(f"[red]{type(exc).__name__}:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    rows = None
    if spec.response_format == "json" and content.strip():
        try:
            parsed = json.loads(content)
            rows = len(parsed) if isinstance(parsed, list) else 1
        except ValueError:
            rows = None
    console.print(
        f"[green]Selesai[/green] — {len(content)} byte"
        + (f", {rows} baris" if rows is not None else "")
    )

    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(content)
        console.print(f"Ditulis ke {out}")
    if save_raw:
        raw_path = (
            settings.raw_dir / "spacetrack" / date.today().isoformat() / spec.suggested_filename()
        )
        write_raw(raw_path, content)
        console.print(f"Disimpan (dengan checksum) di {raw_path}")
    ledger.record(spec.class_name, url, len(content))

    if not out and not save_raw:
        preview = content[:2000].decode("utf-8", "replace")
        console.print(
            Syntax(preview, "json" if spec.response_format == "json" else "text", word_wrap=True)
        )
        if len(content) > 2000:
            console.print(f"[dim]… dipotong, total {len(content)} byte.[/dim]")


def show_modeldef(class_name: str) -> None:
    """Print a class's predicate definitions straight from the API."""
    creds = st.credentials_from_env()
    if creds is None:
        console.print(
            f"[red]Kredensial belum diset.[/red] Set {st.ENV_IDENTITY} dan {st.ENV_PASSWORD}."
        )
        raise typer.Exit(code=1)

    spec = st.Query(class_name=class_name, action="modeldef")
    console.print(f"[cyan]GET[/cyan] {spec.url()}\n")

    async def go():
        async with st.SpaceTrackClient(*creds, user_agent=settings.user_agent) as client:
            return await client.modeldef(class_name)

    try:
        fields = asyncio.run(go())
    except st.SpaceTrackError as exc:
        console.print(f"[red]{type(exc).__name__}:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    table = Table(title=f"Space-Track modeldef — class/{class_name}")
    table.add_column("Predicate")
    table.add_column("Tipe")
    table.add_column("Null?")
    for field in fields if isinstance(fields, list) else []:
        table.add_row(
            str(field.get("Field", "")),
            str(field.get("Type", "")),
            str(field.get("Null", "")),
        )
    console.print(table)
