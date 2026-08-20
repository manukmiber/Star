"""Fase 3 builder: stars/{by_name,by_constellation,by_spectral_type,
by_distance,special}/ from the HYG database (data/raw/hyg_database/).

HYG has no per-object `object_type` flag, so `special/` is limited to what
can be honestly derived from its own columns: `var` (variable-star
designation) for special/variables, and a spectral-type prefix of "D" for
special/white_dwarfs. The brief also asks for neutron_stars, pulsars,
magnetars, black_holes, brown_dwarfs, supergiants, hypergiants — HYG alone
can't support those without guessing, so those subfolders are left
un-populated with a README explaining why, rather than invented.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from .common import BuildReport, latest_raw_file, sv, write_category_index, write_category_table, write_json, write_metadata, write_text
from ..core.naming import slugify

STAR_URL = "https://raw.githubusercontent.com/astronexus/HYG-Database/main/hyg/CURRENT/hygdata_v41.csv"

DISTANCE_BANDS = [
    ("within_10pc", 0, 10),
    ("within_25pc", 10, 25),
    ("within_100pc", 25, 100),
    ("beyond", 100, None),
]


def _star_json(row: dict) -> dict:
    return {
        "display_name": row.get("proper"),
        "hip": row.get("hip"),
        "hd": row.get("hd"),
        "hr": row.get("hr"),
        "gliese": row.get("gl"),
        "bayer_flamsteed": row.get("bf"),
        "constellation": row.get("con"),
        "ra_deg": sv(row.get("ra")),
        "dec_deg": sv(row.get("dec")),
        "distance_pc": sv(row.get("dist")),
        "apparent_magnitude": sv(row.get("mag")),
        "absolute_magnitude": sv(row.get("absmag")),
        "spectral_type": row.get("spect"),
        "color_index_bv": sv(row.get("ci")),
        "luminosity_solar": sv(row.get("lum")),
        "variable_designation": row.get("var"),
        "variable_mag_min": row.get("var_min"),
        "variable_mag_max": row.get("var_max"),
        "data_source": "hyg_database",
    }


def build(raw_root: Path, out_root: Path) -> BuildReport:
    report = BuildReport(category="stars")

    hyg_path = latest_raw_file(raw_root, "hyg_database", "hygdata_v41.csv")
    if hyg_path is None:
        report.note("hygdata_v41.csv tidak ditemukan di raw — stars/ tidak dibangun")
        return report

    df = pl.read_csv(hyg_path, infer_schema_length=20000)

    # by_name/
    named = df.filter(pl.col("proper").is_not_null() & (pl.col("proper") != ""))
    by_name_dir = out_root / "by_name"
    used_slugs: dict[str, int] = {}
    name_slugs = []
    for row in named.iter_rows(named=True):
        base_slug = slugify(row["proper"])
        n = used_slugs.get(base_slug, 0)
        used_slugs[base_slug] = n + 1
        slug = base_slug if n == 0 else f"{base_slug}__{row.get('hip') or row.get('hd') or n}"
        name_slugs.append(slug)
        s_dir = by_name_dir / slug
        write_json(s_dir / "star.json", _star_json(row))
        write_metadata(s_dir / "metadata.json", source="hyg_database", source_url=STAR_URL)
        write_text(s_dir / "README.md", f"# {row['proper']}\n\nRasi: {row.get('con') or '?'}. Tipe spektral: {row.get('spect') or '?'}.\n")
        report.object_count += 1
    write_category_table(by_name_dir, named)
    write_category_index(by_name_dir, name_slugs, f"{len(name_slugs)} bintang dengan nama umum (kolom `proper` di HYG).")

    # by_constellation/
    const_dir = out_root / "by_constellation"
    const_children = []
    for (con,), sub in df.filter(pl.col("con").is_not_null() & (pl.col("con") != "")).partition_by("con", as_dict=True, include_key=True).items():
        slug = slugify(con)
        const_children.append(slug)
        write_category_table(const_dir / slug, sub)
        write_text(const_dir / slug / "README.md", f"# {con}\n\n{sub.height} bintang HYG di rasi ini.\n")
        write_metadata(const_dir / slug / "metadata.json", source="hyg_database", source_url=STAR_URL, record_count=sub.height)
    write_category_index(const_dir, const_children, "88 rasi bintang IAU (hanya yang punya bintang HYG).")

    # by_spectral_type/
    spec_dir = out_root / "by_spectral_type"
    spec_children = []
    classified = df.filter(pl.col("spect").is_not_null() & (pl.col("spect") != "")).with_columns(
        pl.col("spect").str.slice(0, 1).alias("_spec_class")
    )
    for (cls,), sub in classified.partition_by("_spec_class", as_dict=True, include_key=True).items():
        if not cls or not cls.isalpha():
            continue
        slug = slugify(cls)
        spec_children.append(slug)
        write_category_table(spec_dir / slug, sub.drop("_spec_class"))
        write_text(spec_dir / slug / "README.md", f"# Tipe spektral {cls}\n\n{sub.height} bintang (prefix `{cls}` dari kolom `spect`).\n")
        write_metadata(spec_dir / slug / "metadata.json", source="hyg_database", source_url=STAR_URL, record_count=sub.height)
    write_category_index(spec_dir, spec_children, "Dikelompokkan dari huruf pertama kolom `spect` (O,B,A,F,G,K,M,...).")

    # by_distance/
    dist_dir = out_root / "by_distance"
    dist_children = []
    for name, lo, hi in DISTANCE_BANDS:
        cond = pl.col("dist") >= lo
        if hi is not None:
            cond = cond & (pl.col("dist") < hi)
        sub = df.filter(cond)
        dist_children.append(name)
        write_category_table(dist_dir / name, sub)
        write_text(dist_dir / name / "README.md", f"# {name}\n\n{sub.height} bintang, jarak {lo}-{hi if hi else 'inf'} pc.\n")
        write_metadata(dist_dir / name / "metadata.json", source="hyg_database", source_url=STAR_URL, record_count=sub.height)
    write_category_index(dist_dir, dist_children, "Dikelompokkan dari kolom `dist` (parsec).")

    # special/
    special_dir = out_root / "special"
    variables = df.filter(pl.col("var").is_not_null() & (pl.col("var") != ""))
    write_category_table(special_dir / "variables", variables)
    write_metadata(special_dir / "variables" / "metadata.json", source="hyg_database", source_url=STAR_URL, record_count=variables.height)
    write_text(special_dir / "variables" / "README.md", f"# Variable stars\n\n{variables.height} bintang dengan kolom `var` terisi (nama/tipe variabel AAVSO).\n")

    white_dwarfs = df.filter(pl.col("spect").is_not_null() & pl.col("spect").str.starts_with("D"))
    write_category_table(special_dir / "white_dwarfs", white_dwarfs)
    write_metadata(special_dir / "white_dwarfs" / "metadata.json", source="hyg_database", source_url=STAR_URL, record_count=white_dwarfs.height)
    write_text(special_dir / "white_dwarfs" / "README.md", f"# White dwarfs\n\n{white_dwarfs.height} bintang tipe spektral berawalan `D` di HYG.\n")

    unbuilt = ["neutron_stars", "pulsars", "magnetars", "black_holes", "brown_dwarfs", "supergiants", "hypergiants"]
    for name in unbuilt:
        write_text(
            special_dir / name / "README.md",
            f"# {name}\n\nBelum dibangun: HYG tidak punya kolom object_type/luminosity-class yang "
            "cukup andal untuk mengklasifikasikan ini tanpa menebak. Butuh cross-match ke SIMBAD "
            "atau katalog khusus (mis. Villanova WD catalog, ATNF pulsar catalog) yang belum "
            "ditarik. Lihat REPORT.md.\n",
        )
    write_category_index(special_dir, ["variables", "white_dwarfs", *unbuilt], "Kategori khusus; sebagian belum dibangun (lihat README masing-masing).")
    report.note(f"special/: {len(unbuilt)} subkategori belum dibangun (butuh sumber tambahan, lihat README)")

    return report
