"""Fase 3 builder: data/_catalog/ — master_index.json, sources.json,
crosswalk.parquet, schema/.

crosswalk.parquet is intentionally partial: it's HYG's own id/hip/hd/hr/gl
columns (HYG already cross-references those catalogs per star), which is
honest and traceable but does NOT yet include Gaia DR3 source_id, TIC, KIC,
or SIMBAD main_id — those need a real crossmatch (by coordinates or name)
against SIMBAD/Gaia that was deferred (see sources/registry.py notes on
simbad_tap and gaia_dr3_tap). Extending the crosswalk is the natural next
step, not done here to avoid faking join keys that were never resolved.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from .common import latest_raw_file, write_json, write_text
from ..sources.registry import SOURCES

LEAF_MARKERS = {
    "planet.json": "planet",
    "moon.json": "moon",
    "dwarf_planet.json": "dwarf_planet",
    "star.json": "star",
    "host_star.json": "exoplanet_host_star",
    "asteroid.json": "asteroid",
    "deep_sky_object.json": "deep_sky_object",
}


def build_master_index(data_root: Path) -> dict:
    index: dict[str, list[str]] = {}
    for marker, obj_type in LEAF_MARKERS.items():
        paths = sorted(str(p.parent.relative_to(data_root)) for p in data_root.rglob(marker))
        index[obj_type] = paths
    write_json(data_root / "_catalog" / "master_index.json", {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts": {k: len(v) for k, v in index.items()},
        "objects": index,
    })
    return index


def build_sources_json(raw_root: Path, catalog_dir: Path) -> None:
    entries = []
    for key, spec in sorted(SOURCES.items()):
        base = raw_root / key
        dated = sorted((p for p in base.iterdir() if p.is_dir()), reverse=True) if base.exists() else []
        entries.append({
            "key": key,
            "name": spec.name,
            "tier": spec.tier,
            "category": spec.category,
            "base_url": spec.base_url,
            "license": spec.license,
            "requires_credentials": spec.requires_credentials,
            "pulled": bool(dated),
            "last_pulled_date": dated[0].name if dated else None,
            "notes": spec.notes,
        })
    write_json(catalog_dir / "sources.json", entries)


def build_crosswalk(raw_root: Path, catalog_dir: Path) -> int:
    hyg_path = latest_raw_file(raw_root, "hyg_database", "hygdata_v41.csv")
    if hyg_path is None:
        return 0
    df = pl.read_csv(hyg_path, infer_schema_length=20000)
    crosswalk = df.select([
        pl.col("id").alias("hyg_id"),
        pl.col("hip").alias("hip"),
        pl.col("hd").alias("hd"),
        pl.col("hr").alias("hr"),
        pl.col("gl").alias("gliese"),
        pl.col("proper").alias("common_name"),
    ])
    crosswalk.write_parquet(catalog_dir / "crosswalk.parquet")
    write_text(
        catalog_dir / "crosswalk.README.md",
        "# crosswalk.parquet\n\n"
        "Kolom: hyg_id, hip, hd, hr, gliese, common_name — semuanya dari HYG database "
        "sendiri (hyg_database), bukan crossmatch independen. Gaia DR3 source_id, TIC, "
        "KIC, dan SIMBAD main_id BELUM ada di sini — butuh crossmatch koordinat/nama yang "
        "belum dikerjakan (lihat notes simbad_tap/gaia_dr3_tap di sources/registry.py).\n",
    )
    return crosswalk.height


SCHEMAS = {
    "planet": {
        "type": "object",
        "properties": {
            "display_name": {"type": "string"},
            "mass_kg": {"$ref": "sourced_value.json"},
            "vol_mean_radius_km": {"$ref": "sourced_value.json"},
            "density_g_cm3": {"$ref": "sourced_value.json"},
            "gm_km3_s2": {"$ref": "sourced_value.json"},
            "sidereal_rotation_hr": {"$ref": "sourced_value.json"},
            "sidereal_orbit_period_days": {"$ref": "sourced_value.json"},
            "data_source": {"type": "string"},
        },
    },
    "moon": {
        "type": "object",
        "properties": {
            "display_name": {"type": "string"},
            "planet": {"type": "string"},
            "naif_id": {"type": ["string", "null"]},
            "discoverer": {"type": ["string", "null"]},
            "year_discovered": {"type": ["string", "null"]},
            "gm_km3_s2": {"$ref": "sourced_value.json"},
            "mean_radius_km": {"$ref": "sourced_value.json"},
            "mass_kg": {"$ref": "sourced_value.json"},
            "semi_major_axis_km": {"$ref": "sourced_value.json"},
            "eccentricity": {"$ref": "sourced_value.json"},
            "orbital_period_days": {"$ref": "sourced_value.json"},
        },
    },
    "star": {
        "type": "object",
        "properties": {
            "display_name": {"type": ["string", "null"]},
            "hip": {"type": ["integer", "null"]},
            "hd": {"type": ["integer", "null"]},
            "constellation": {"type": ["string", "null"]},
            "distance_pc": {"$ref": "sourced_value.json"},
            "apparent_magnitude": {"$ref": "sourced_value.json"},
            "spectral_type": {"type": ["string", "null"]},
        },
    },
    "exoplanet_planet": {
        "type": "object",
        "properties": {
            "display_name": {"type": "string"},
            "letter": {"type": ["string", "null"]},
            "hostname": {"type": "string"},
            "discovery_method": {"type": ["string", "null"]},
            "discovery_year": {"type": ["integer", "null"]},
            "orbital_period_days": {"$ref": "sourced_value.json"},
            "radius_earth": {"$ref": "sourced_value.json"},
            "mass_earth": {"$ref": "sourced_value.json"},
        },
    },
    "exoplanet_host_star": {
        "type": "object",
        "properties": {
            "display_name": {"type": "string"},
            "hd_name": {"type": ["string", "null"]},
            "hip_name": {"type": ["string", "null"]},
            "tic_id": {"type": ["string", "null"]},
            "num_planets_in_system": {"type": ["integer", "null"]},
            "teff_k": {"$ref": "sourced_value.json"},
        },
    },
    "asteroid": {
        "type": "object",
        "properties": {
            "display_name": {"type": "string"},
            "full_name": {"type": "string"},
            "spkid": {"type": ["integer", "null"]},
            "orbit_class": {"type": "string"},
            "is_neo": {"type": "boolean"},
            "is_pha": {"type": "boolean"},
            "semi_major_axis_au": {"type": ["number", "null"]},
            "eccentricity": {"type": ["number", "null"]},
        },
    },
    "deep_sky_object": {
        "type": "object",
        "properties": {
            "display_name": {"type": "string"},
            "type": {"type": ["string", "null"]},
            "constellation": {"type": ["string", "null"]},
            "messier_number": {"type": ["integer", "null"]},
        },
    },
    "sourced_value": {
        "type": "object",
        "properties": {
            "value": {"type": ["number", "string", "null"]},
            "err_upper": {"type": ["number", "null"]},
            "err_lower": {"type": ["number", "null"]},
            "limit_flag": {"type": ["string", "null"]},
            "ref": {"type": ["string", "null"]},
        },
        "required": ["value"],
    },
}


def build_schemas(schema_dir: Path) -> None:
    schema_dir.mkdir(parents=True, exist_ok=True)
    for name, schema in SCHEMAS.items():
        write_json(schema_dir / f"{name}.json", {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": name, **schema})


def build(raw_root: Path, data_root: Path) -> dict:
    catalog_dir = data_root / "_catalog"
    index = build_master_index(data_root)
    build_sources_json(raw_root, catalog_dir)
    crosswalk_rows = build_crosswalk(raw_root, catalog_dir)
    build_schemas(catalog_dir / "schema")
    return {"index_counts": {k: len(v) for k, v in index.items()}, "crosswalk_rows": crosswalk_rows}
