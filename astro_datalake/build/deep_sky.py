"""Fase 3 builder: deep_sky/{messier,ngc,ic,nebulae,galaxies}/ from
OpenNGC (data/raw/openngc/NGC.csv — despite the filename it covers both
NGC and IC catalog entries, one row per object, `Name` prefixed NGC/IC).
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from .common import BuildReport, latest_raw_file, write_category_index, write_category_table, write_json, write_metadata, write_text
from ..core.naming import slugify

NEBULA_TYPES = {"Neb", "HII", "EmN", "PN", "RfN", "SNR", "Cl+N"}
GALAXY_TYPES = {"G", "GPair", "GTrpl", "GGroup"}


def _obj_json(row: dict) -> dict:
    return {
        "display_name": row.get("Name"),
        "common_names": row.get("Common names"),
        "type": row.get("Type"),
        "constellation": row.get("Const"),
        "ra": row.get("RA"),
        "dec": row.get("Dec"),
        "messier_number": row.get("M"),
        "v_mag": row.get("V-Mag"),
        "major_axis_arcmin": row.get("MajAx"),
        "minor_axis_arcmin": row.get("MinAx"),
        "identifiers": row.get("Identifiers"),
        "data_source": "openngc",
    }


def build(raw_root: Path, out_root: Path) -> BuildReport:
    report = BuildReport(category="deep_sky")

    ngc_path = latest_raw_file(raw_root, "openngc", "NGC.csv")
    if ngc_path is None:
        report.note("NGC.csv tidak ditemukan di raw — deep_sky/ tidak dibangun")
        return report

    df = pl.read_csv(ngc_path, separator=";", infer_schema_length=20000)

    # messier/
    messier = df.filter(pl.col("M").is_not_null())
    messier_dir = out_root / "messier"
    messier_slugs = []
    for row in messier.iter_rows(named=True):
        slug = f"m{int(row['M']):03d}"
        messier_slugs.append(slug)
        obj_dir = messier_dir / slug
        write_json(obj_dir / "deep_sky_object.json", _obj_json(row))
        write_metadata(obj_dir / "metadata.json", source="openngc", source_url="https://github.com/mattiaverga/OpenNGC")
        write_text(obj_dir / "README.md", f"# M{int(row['M'])} ({row.get('Name')})\n\nTipe: {row.get('Type')}. Rasi: {row.get('Const')}.\n")
        report.object_count += 1
    write_category_table(messier_dir, messier)
    write_category_index(messier_dir, messier_slugs, "110 objek Messier (kolom M di OpenNGC).")

    # ngc/, ic/
    for prefix, name in [("NGC", "ngc"), ("IC", "ic")]:
        sub = df.filter(pl.col("Name").str.starts_with(prefix))
        dir_path = out_root / name
        write_category_table(dir_path, sub)
        write_metadata(dir_path / "metadata.json", source="openngc", source_url="https://github.com/mattiaverga/OpenNGC", record_count=sub.height)
        write_text(dir_path / "README.md", f"# {name.upper()}\n\n{sub.height} objek katalog {prefix} (OpenNGC).\n")
        report.object_count += sub.height

    # nebulae/, galaxies/
    nebulae = df.filter(pl.col("Type").is_in(list(NEBULA_TYPES)))
    galaxies = df.filter(pl.col("Type").is_in(list(GALAXY_TYPES)))
    for name, sub in [("nebulae", nebulae), ("galaxies", galaxies)]:
        dir_path = out_root / name
        write_category_table(dir_path, sub)
        write_metadata(dir_path / "metadata.json", source="openngc", source_url="https://github.com/mattiaverga/OpenNGC", record_count=sub.height)
        write_text(dir_path / "README.md", f"# {name}\n\n{sub.height} objek (Type di {sorted(NEBULA_TYPES if name == 'nebulae' else GALAXY_TYPES)}).\n")

    write_category_index(out_root, ["messier", "ngc", "ic", "nebulae", "galaxies"], "Deep-sky objects dari OpenNGC.")
    return report
