"""Fase 3 builder: data/_catalog/ — master_index.json, sources.json,
crosswalk.parquet, schema/.

crosswalk.parquet started as HYG's own id/hip/hd/hr/gl columns. Fase 5
widens it with the identifiers those columns could not reach: SIMBAD's
main_id, object type and spectral type, plus Gaia DR3 source_id, TIC and
2MASS designations, all joined on the Hipparcos number through SIMBAD's
`ident` table (pulled as bounded ADQL queries, see downloaders.py), and the
exoplanet-host names from pscomppars. Every column names the source it came
from in crosswalk.README.md; nothing is inferred by position here — a HIP
number either has a counterpart in SIMBAD's identifier table or the cell is
null.

Fase 5 also sweeps the finished tree and writes the attribution each source
requires into every folder's README.md (attribution_pass below). CDS/VizieR,
CelesTrak and the MPC all ask for attribution in derived products, and
having it only in metadata.json was not enough.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from .common import (
    ATTRIBUTION_BEGIN,
    ATTRIBUTION_END,
    attribution_block,
    latest_raw_file,
    source_keys_of,
    write_json,
    write_text,
)
from ..sources.registry import SOURCES

LEAF_MARKERS = {
    "planet.json": "planet",
    "moon.json": "moon",
    "dwarf_planet.json": "dwarf_planet",
    "star.json": "star",
    "host_star.json": "exoplanet_host_star",
    "asteroid.json": "asteroid",
    "deep_sky_object.json": "deep_sky_object",
    "system.json": "multiple_system",
    "shower.json": "meteor_shower",
    "model_3d.json": "model_3d",
}


def object_folders(data_root: Path, marker: str) -> list[str]:
    """Folders holding a real object, relative to data/.

    `_catalog/schema/` is excluded: it holds the JSON Schemas, whose
    filenames are deliberately the same as the leaf files they validate
    (moon.json, planet.json, ...). Without this the index counted each
    schema as one more moon.
    """
    return sorted(
        str(path.parent.relative_to(data_root))
        for path in data_root.rglob(marker)
        if "_catalog" not in path.parent.relative_to(data_root).parts
    )


def build_master_index(data_root: Path) -> dict:
    index: dict[str, list[str]] = {}
    for marker, obj_type in LEAF_MARKERS.items():
        index[obj_type] = object_folders(data_root, marker)
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


def _simbad_xwalk(raw_root: Path, filename: str, value_column: str) -> pl.DataFrame | None:
    """One SIMBAD ident join, keyed by integer HIP number.

    SIMBAD stores identifiers as text ("HIP 71683"), so the numeric key has
    to be parsed out before it can join to HYG's `hip`. Duplicates are real
    (one HIP can carry several TIC entries); they are collapsed to the first
    value with a count kept alongside, so a many-to-one join never silently
    multiplies the crosswalk's rows.
    """
    path = latest_raw_file(raw_root, "simbad_tap", filename)
    if path is None:
        return None
    df = pl.read_csv(path, infer_schema_length=10000, ignore_errors=True)
    if "hip_id" not in df.columns:
        return None
    source_col = "other_id" if "other_id" in df.columns else None
    df = df.with_columns(
        pl.col("hip_id").str.extract(r"HIP\s+(\d+)", 1).cast(pl.Int64, strict=False).alias("hip")
    ).filter(pl.col("hip").is_not_null())
    if source_col:
        df = df.rename({source_col: value_column})
        return df.group_by("hip").agg([
            pl.col(value_column).first(),
            pl.len().alias(f"{value_column}_count"),
        ])
    keep = [c for c in df.columns if c not in ("hip_id", "hip")]
    return df.group_by("hip").agg([pl.col(c).first() for c in keep])


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

    joined_sources = ["hyg_database"]
    for filename, column in [
        ("xwalk_hip_main_id.csv", None),
        ("xwalk_hip_gaia_dr3.csv", "gaia_dr3_id"),
        ("xwalk_hip_tic.csv", "tic_id"),
        ("xwalk_hip_twomass.csv", "twomass_id"),
        ("xwalk_hip_hd.csv", "simbad_hd_id"),
    ]:
        side = _simbad_xwalk(raw_root, filename, column or "simbad_main_id")
        if side is None:
            continue
        if "simbad_tap" not in joined_sources:
            joined_sources.append("simbad_tap")
        rename = {"main_id": "simbad_main_id", "otype": "simbad_otype", "sp_type": "simbad_sp_type"}
        side = side.rename({k: v for k, v in rename.items() if k in side.columns})
        crosswalk = crosswalk.join(side, on="hip", how="left")

    # Exoplanet hosts: pscomppars carries its own HIP/TIC/Gaia identifiers.
    ps_path = latest_raw_file(raw_root, "exoplanet_archive_pscomppars", "pscomppars.csv")
    if ps_path is not None:
        hosts = (
            pl.read_csv(ps_path, comment_prefix="#", infer_schema_length=10000)
            .select(["hostname", "hip_name", "tic_id", "gaia_dr2_id"])
            .with_columns(
                pl.col("hip_name").str.extract(r"HIP\s+(\d+)", 1).cast(pl.Int64, strict=False).alias("hip")
            )
            .filter(pl.col("hip").is_not_null())
            .group_by("hip")
            .agg([
                pl.col("hostname").first().alias("exoplanet_hostname"),
                pl.col("tic_id").first().alias("exoplanet_archive_tic_id"),
                pl.col("gaia_dr2_id").first().alias("gaia_dr2_id"),
            ])
        )
        crosswalk = crosswalk.join(hosts, on="hip", how="left")
        joined_sources.append("exoplanet_archive_pscomppars")

    crosswalk.write_parquet(catalog_dir / "crosswalk.parquet")

    # HYG writes missing text fields as "" rather than null, so an is_not_null
    # count would report full coverage for columns that are mostly blank.
    filled = {}
    for column in crosswalk.columns:
        if column == "hyg_id":
            continue
        series = crosswalk[column]
        if series.dtype == pl.Utf8:
            filled[column] = int((series.is_not_null() & (series.str.strip_chars() != "")).sum())
        else:
            filled[column] = int(series.is_not_null().sum())
    coverage = "\n".join(f"| `{c}` | {n} |" for c, n in filled.items())
    write_text(
        catalog_dir / "crosswalk.README.md",
        "# crosswalk.parquet\n\n"
        f"{crosswalk.height} baris, satu per bintang HYG.\n\n"
        "## Asal tiap kolom\n\n"
        "- `hyg_id`, `hip`, `hd`, `hr`, `gliese`, `common_name` — dari HYG sendiri.\n"
        "- `simbad_main_id`, `simbad_otype`, `simbad_sp_type`, `gaia_dr3_id`, `tic_id`, "
        "`twomass_id`, `simbad_hd_id` — dari tabel `ident`/`basic` SIMBAD, di-join lewat "
        "nomor HIP (bukan lewat posisi).\n"
        "- `exoplanet_hostname`, `exoplanet_archive_tic_id`, `gaia_dr2_id` — dari "
        "pscomppars NASA Exoplanet Archive, juga lewat nomor HIP.\n"
        "- Kolom `*_count` = berapa identifier yang SIMBAD punya untuk HIP itu; nilai yang "
        "disimpan adalah yang pertama. Kalau `> 1`, jangan pakai nilainya buta-buta.\n\n"
        "## Cakupan (jumlah baris yang terisi)\n\n"
        "| kolom | terisi |\n|---|---:|\n" + coverage + "\n\n"
        "## Yang masih kosong\n\n"
        "KIC (Kepler Input Catalog) tidak dimasukkan: SIMBAD cuma punya 347 identifier KIC "
        "yang beririsan dengan HIP, jadi kolomnya akan hampir seluruhnya null. Bintang "
        "tanpa nomor HIP (mayoritas host exoplanet TESS/Kepler) belum punya baris di sini "
        "— kuncinya HIP, dan menambahkan kunci kedua butuh crossmatch posisi tersendiri.\n\n"
        + attribution_block(joined_sources) + "\n",
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
    "model_3d": {
        "type": "object",
        "properties": {
            "display_name": {"type": "string"},
            "category": {"type": "string"},
            "object_type": {"type": ["string", "null"]},
            "classified_by": {"type": "string"},
            "file_count": {"type": "integer"},
            "has_mesh": {"type": "boolean"},
            "has_texture": {"type": "boolean"},
            "formats": {"type": "array", "items": {"type": "string"}},
            "sources": {"type": "array", "items": {"type": "object"}},
            "files": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["display_name", "category", "files"],
    },
    "multiple_system": {
        "type": "object",
        "properties": {
            "display_name": {"type": "string"},
            "wds_designation": {"type": ["string", "null"]},
            "components_in_wds": {"type": ["integer", "null"]},
            "primary_magnitude": {"type": ["number", "null"]},
            "secondary_magnitude": {"type": ["number", "null"]},
            "hip": {"type": ["integer", "null"]},
            "identification": {
                "type": "object",
                "properties": {
                    "method": {"type": "string"},
                    "separation_arcsec": {"type": ["number", "null"]},
                    "tolerance_arcsec": {"type": "number"},
                },
                "required": ["method", "separation_arcsec"],
            },
        },
        "required": ["display_name", "identification"],
    },
    "meteor_shower": {
        "type": "object",
        "properties": {
            "display_name": {"type": "string"},
            "iau_code": {"type": ["string", "null"]},
            "iau_number": {"type": ["string", "null"]},
            "activity": {"type": ["string", "null"]},
            "radiant_ra_deg": {"type": ["string", "null"]},
            "radiant_dec_deg": {"type": ["string", "null"]},
            "parent_body": {"type": ["string", "null"]},
            "solution_count": {"type": "integer"},
        },
        "required": ["display_name", "solution_count"],
    },
    "sourced_value": {
        "type": "object",
        "properties": {
            "value": {"type": ["number", "string", "null"]},
            "err_upper": {"type": ["number", "null"]},
            "err_lower": {"type": ["number", "null"]},
            "limit_flag": {"type": ["number", "string", "null"]},
            "ref": {"type": ["string", "null"]},
        },
        "required": ["value"],
    },
}


def build_schemas(schema_dir: Path) -> None:
    schema_dir.mkdir(parents=True, exist_ok=True)
    for name, schema in SCHEMAS.items():
        write_json(schema_dir / f"{name}.json", {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": name, **schema})


def attribution_pass(data_root: Path) -> int:
    """Stamp each folder's README.md with the attribution its source requires.

    Driven by metadata.json's `source`, so it covers folders written by
    builders that predate the attribution helpers too. Idempotent: the block
    sits between HTML markers and is replaced, not appended, on every run.
    """
    stamped = 0
    used_sources: set[str] = set()
    for metadata_path in data_root.rglob("metadata.json"):
        try:
            source = json.loads(metadata_path.read_text()).get("source", "")
        except (json.JSONDecodeError, OSError):
            continue
        keys = source_keys_of(source)
        if not keys:
            continue
        used_sources.update(keys)
        readme_path = metadata_path.parent / "README.md"
        body = readme_path.read_text() if readme_path.exists() else f"# {metadata_path.parent.name}\n"
        if ATTRIBUTION_BEGIN in body:
            head, _, tail = body.partition(ATTRIBUTION_BEGIN)
            _, _, after = tail.partition(ATTRIBUTION_END)
            body = head.rstrip() + "\n" + after.lstrip("\n")
        write_text(readme_path, body.rstrip() + "\n\n" + attribution_block(keys))
        stamped += 1

    write_text(
        data_root / "ATTRIBUTION.md",
        "# Atribusi sumber data\n\n"
        "Setiap folder di bawah `data/` punya blok atribusi sendiri di README.md-nya, "
        "dihasilkan dari `source` di metadata.json folder itu. Daftar di bawah adalah "
        "gabungan seluruh sumber yang benar-benar terpakai di build terakhir.\n\n"
        + attribution_block(sorted(used_sources))
        + "\n\nCatatan: CDS/VizieR (WDS, SB9, MSC, ATNF, BlackCAT), SIMBAD, CelesTrak, "
        "dan MPC secara eksplisit meminta atribusi di setiap karya turunan. Kalau kamu "
        "menerbitkan apa pun dari data lake ini, sertakan baris-baris di atas.\n",
    )
    return stamped


def build(raw_root: Path, data_root: Path) -> dict:
    catalog_dir = data_root / "_catalog"
    index = build_master_index(data_root)
    build_sources_json(raw_root, catalog_dir)
    crosswalk_rows = build_crosswalk(raw_root, catalog_dir)
    build_schemas(catalog_dir / "schema")
    attributed = attribution_pass(data_root)
    return {
        "index_counts": {k: len(v) for k, v in index.items()},
        "crosswalk_rows": crosswalk_rows,
        "attributed_folders": attributed,
    }
