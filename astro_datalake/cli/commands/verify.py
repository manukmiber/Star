"""`astro verify`: checksum, row-count/index-freshness, empty-folder, and
JSON-schema checks over data/. Read-only — never touches raw/ or processed/.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ...core.cache import sha256_of_file
from ...core.config import settings

console = Console()

SAMPLE_SIZE_PER_TYPE = 200


def _check_checksums() -> tuple[int, list[str]]:
    ok = 0
    bad = []
    for sidecar in settings.raw_dir.rglob("*.sha256"):
        raw_file = sidecar.with_name(sidecar.name[: -len(".sha256")])
        if not raw_file.exists():
            bad.append(f"{raw_file}: file mentah hilang (sidecar checksum ada, file tidak)")
            continue
        recorded = sidecar.read_text().split()[0].strip()
        actual = sha256_of_file(raw_file)
        if actual == recorded:
            ok += 1
        else:
            bad.append(f"{raw_file}: checksum tidak cocok (raw mungkin korup/berubah)")
    return ok, bad


def _check_master_index_fresh() -> tuple[bool, dict]:
    idx_path = settings.catalog_dir / "master_index.json"
    if not idx_path.exists():
        return False, {}
    index = json.loads(idx_path.read_text())
    marker_by_type = {
        "planet": "planet.json", "moon": "moon.json", "dwarf_planet": "dwarf_planet.json",
        "star": "star.json", "exoplanet_host_star": "host_star.json",
        "asteroid": "asteroid.json", "deep_sky_object": "deep_sky_object.json",
    }
    mismatches = {}
    for obj_type, recorded_paths in index.get("objects", {}).items():
        marker = marker_by_type.get(obj_type)
        if marker is None:
            continue
        live_count = sum(1 for _ in settings.data_dir.rglob(marker))
        if live_count != len(recorded_paths):
            mismatches[obj_type] = {"index": len(recorded_paths), "live": live_count}
    return len(mismatches) == 0, mismatches


def _check_empty_folders() -> list[str]:
    empty = []
    for d in settings.data_dir.rglob("*"):
        if not d.is_dir():
            continue
        if d.name in {"raw"} or "/raw/" in str(d):
            continue
        has_file = any(f.is_file() for f in d.iterdir())
        has_subdir = any(f.is_dir() for f in d.iterdir())
        if not has_file and not has_subdir:
            empty.append(str(d.relative_to(settings.data_dir)))
    return empty


def _check_json_schema() -> tuple[int, int, list[str]]:
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    schema_dir = settings.schema_dir
    if not schema_dir.exists():
        return 0, 0, ["schema/ tidak ditemukan"]

    resources = []
    schemas = {}
    for f in schema_dir.glob("*.json"):
        contents = json.loads(f.read_text())
        resources.append((f.name, Resource.from_contents(contents)))
        schemas[f.stem] = contents
    registry = Registry().with_resources(resources)

    # "planet.json" is used by both solar_system/ (mass_kg, gm_km3_s2, ...) and
    # exoplanets/by_host_star/.../planets/ (hostname, discovery_method, ...) — same
    # filename, different schema (matches the brief's own naming choice, see
    # build/catalog.py). Disambiguate by path, not just filename.
    marker_to_schema = {
        "moon.json": "moon", "dwarf_planet.json": "planet",
        "star.json": "star", "host_star.json": "exoplanet_host_star",
        "asteroid.json": "asteroid", "deep_sky_object.json": "deep_sky_object",
    }

    validated = 0
    failed = 0
    failures = []

    def _validate_sample(schema_name: str, files: list[Path]) -> None:
        nonlocal validated, failed
        schema = schemas.get(schema_name)
        if schema is None or not files:
            return
        validator = Draft202012Validator(schema, registry=registry)
        sample = files if len(files) <= SAMPLE_SIZE_PER_TYPE else random.sample(files, SAMPLE_SIZE_PER_TYPE)
        for f in sample:
            try:
                instance = json.loads(f.read_text())
            except json.JSONDecodeError as exc:
                failed += 1
                failures.append(f"{f}: JSON tidak valid ({exc})")
                continue
            errors = list(validator.iter_errors(instance))
            if errors:
                failed += 1
                if len(failures) < 20:
                    failures.append(f"{f}: {errors[0].message}")
            else:
                validated += 1

    solar_system_planets = list((settings.data_dir / "solar_system" / "planets").rglob("planet.json"))
    exoplanet_planets = list((settings.data_dir / "exoplanets").rglob("planet.json"))
    _validate_sample("planet", solar_system_planets)
    _validate_sample("exoplanet_planet", exoplanet_planets)

    for marker, schema_name in marker_to_schema.items():
        schema = schemas.get(schema_name)
        if schema is None:
            continue
        validator = Draft202012Validator(schema, registry=registry)
        files = list(settings.data_dir.rglob(marker))
        sample = files if len(files) <= SAMPLE_SIZE_PER_TYPE else random.sample(files, SAMPLE_SIZE_PER_TYPE)
        for f in sample:
            try:
                instance = json.loads(f.read_text())
            except json.JSONDecodeError as exc:
                failed += 1
                failures.append(f"{f}: JSON tidak valid ({exc})")
                continue
            errors = list(validator.iter_errors(instance))
            if errors:
                failed += 1
                if len(failures) < 20:
                    failures.append(f"{f}: {errors[0].message}")
            else:
                validated += 1
    return validated, failed, failures


def run() -> None:
    settings.ensure_dirs()
    table = Table(title="astro verify")
    table.add_column("Cek")
    table.add_column("Hasil")

    ck_ok, ck_bad = _check_checksums()
    table.add_row("Checksum raw/", f"{ck_ok} OK, {len(ck_bad)} bermasalah")

    fresh, mismatches = _check_master_index_fresh()
    table.add_row("master_index.json vs live", "cocok" if fresh else f"{len(mismatches)} tipe tidak cocok: {mismatches}")

    empty = _check_empty_folders()
    table.add_row("Folder kosong", f"{len(empty)} ditemukan" if empty else "tidak ada")

    validated, failed, schema_failures = _check_json_schema()
    table.add_row("JSON vs schema (sampel)", f"{validated} valid, {failed} gagal")

    console.print(table)

    if ck_bad:
        console.print("\n[red]Checksum bermasalah (contoh):[/red]")
        for msg in ck_bad[:10]:
            console.print(f"  - {msg}")
    if empty:
        console.print("\n[yellow]Folder kosong (contoh):[/yellow]")
        for e in empty[:10]:
            console.print(f"  - {e}")
    if schema_failures:
        console.print("\n[red]Kegagalan schema (contoh):[/red]")
        for msg in schema_failures[:10]:
            console.print(f"  - {msg}")

    problems = len(ck_bad) + (0 if fresh else 1) + len(empty) + failed
    if problems:
        console.print(f"\n[yellow]{problems} masalah ditemukan.[/yellow]")
        raise typer.Exit(code=1)
    console.print("\n[green]Semua cek lulus.[/green]")
