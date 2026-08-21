"""Fase 3 builder: stars/{by_name,by_constellation,by_spectral_type,
by_distance,special}/ from the HYG database (data/raw/hyg_database/).

HYG has no per-object `object_type` flag, so what `special/` can say from
HYG alone is limited to its own columns: `var` (variable-star designation)
for special/variables, and a spectral-type prefix of "D" for
special/white_dwarfs.

Fase 5 fills the seven categories HYG could not support — neutron_stars,
pulsars, magnetars, black_holes, brown_dwarfs, supergiants, hypergiants —
from catalogues that carry the object type as data rather than as
inference: SIMBAD's `otypes` table (pulled as bounded per-type queries,
see downloaders.py), the ATNF Pulsar Catalogue for the pulsar/magnetar
census (its own `Type` column flags AXP = magnetar), and BlackCAT for the
black-hole X-ray transients. Where HYG can corroborate a category from its
spectral strings — luminosity class I for supergiants, Ia+ for hypergiants
— that cut is written alongside as a separate file, never merged into the
catalogue's own list.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from . import classify
from .common import (
    BuildReport,
    latest_raw_file,
    sv,
    write_category_index,
    write_category_table,
    write_json,
    write_metadata,
    write_readme,
    write_text,
)
from ..core.naming import slugify

STAR_URL = "https://raw.githubusercontent.com/astronexus/HYG-Database/main/hyg/CURRENT/hygdata_v41.csv"
SIMBAD_TAP_URL = "https://simbad.cds.unistra.fr/simbad/sim-tap/sync"
VIZIER_TAP_URL = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"

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

    special_children = ["variables", "white_dwarfs"]
    special_children += _build_typed_specials(raw_root, special_dir, df, report)

    write_category_index(
        special_dir,
        special_children,
        "Kategori khusus. `variables`/`white_dwarfs` berasal dari kolom HYG sendiri; "
        "sisanya dari katalog yang memang menyimpan tipe objek sebagai data "
        "(SIMBAD otypes, ATNF Pulsar Catalogue, BlackCAT).",
        ["hyg_database", "simbad_tap", "atnf_pulsar_catalog", "blackcat_bh_transients"],
    )
    return report


# --- special/ categories that HYG cannot support on its own ----------------

SIMBAD_SPECIALS = {
    "brown_dwarfs": ("otype_brown_dwarfs.csv", "BD*", "katai coklat"),
    "neutron_stars": ("otype_neutron_stars.csv", "N*", "bintang neutron"),
    "black_holes": ("otype_black_holes.csv", "BH", "lubang hitam"),
    "supergiants": ("otype_supergiants.csv", "sg*", "maharaksasa (supergiant)"),
    "hypergiants": ("otype_hypergiants.csv", "sp_type Ia+", "hipergiant"),
}


def _read_csv(path: Path | None) -> pl.DataFrame | None:
    if path is None:
        return None
    df = pl.read_csv(path, infer_schema_length=20000, ignore_errors=True)
    return df if df.height else None


def _build_typed_specials(
    raw_root: Path, special_dir: Path, hyg: pl.DataFrame, report: BuildReport
) -> list[str]:
    """SIMBAD/ATNF/BlackCAT-backed subfolders under stars/special/.

    A category with no raw file still gets a folder and a README saying what
    is missing — an empty promise is better than a silent gap, and `astro
    verify` checks for folders with neither data nor an explanation.
    """
    built: list[str] = []

    for name, (filename, criterion, label_id) in SIMBAD_SPECIALS.items():
        df = _read_csv(latest_raw_file(raw_root, "simbad_tap", filename))
        target = special_dir / name
        if df is None:
            write_readme(
                target,
                name,
                f"Belum terisi: `data/raw/simbad_tap/*/{filename}` tidak ada. "
                "Jalankan `astro pull simbad_tap` lalu `astro build` lagi.",
                ["simbad_tap"],
            )
            continue
        write_category_table(target, df)
        write_metadata(
            target / "metadata.json",
            source="simbad_tap",
            source_url=SIMBAD_TAP_URL,
            record_count=df.height,
        )
        write_readme(
            target,
            name,
            f"{df.height} objek bertipe `{criterion}` di SIMBAD ({label_id}).\n\n"
            "Diambil lewat query ADQL terbatas ke tabel `otypes`/`basic`, bukan dump "
            "penuh. Tipe objek datang dari SIMBAD sendiri — tidak ada penebakan tipe "
            "dari warna atau magnitudo di sini.",
            ["simbad_tap"],
        )
        built.append(name)
        report.object_count += df.height

    # HYG corroboration for the two categories its spectral strings can reach.
    hyg_spect = hyg.filter(pl.col("spect").is_not_null() & (pl.col("spect") != ""))
    for name, predicate, note in [
        (
            "supergiants",
            classify.is_supergiant,
            "kelas luminositas I (Ia/Iab/Ib) dari kolom `spect` HYG",
        ),
        (
            "hypergiants",
            classify.is_hypergiant,
            "kelas luminositas Ia+ / Ia-0 dari kolom `spect` HYG",
        ),
    ]:
        mask = [predicate(v) for v in hyg_spect["spect"].to_list()]
        subset = hyg_spect.filter(pl.Series(mask))
        target = special_dir / name
        target.mkdir(parents=True, exist_ok=True)
        subset.write_parquet(target / "hyg_luminosity_class.parquet")
        write_json(
            target / "hyg_luminosity_class.metadata.json",
            {
                "source": "hyg_database",
                "source_url": STAR_URL,
                "record_count": subset.height,
                "derived_from": ["spect"],
                "classification_method": (
                    f"build/classify.py luminosity_class(): {note}. Daftar terpisah dari "
                    "all.parquet (SIMBAD) dan sengaja tidak digabung — dua sensus berbeda "
                    "dengan cakupan berbeda."
                ),
            },
        )

    # Pulsars and magnetars: ATNF's own census and its own Type flag.
    atnf = _read_csv(latest_raw_file(raw_root, "atnf_pulsar_catalog", "psr.csv"))
    if atnf is None:
        write_readme(
            special_dir / "pulsars",
            "pulsars",
            "Belum terisi: `data/raw/atnf_pulsar_catalog/*/psr.csv` tidak ada. "
            "Jalankan `astro pull atnf_pulsar_catalog`.",
            ["atnf_pulsar_catalog"],
        )
        write_readme(
            special_dir / "magnetars",
            "magnetars",
            "Belum terisi: ikut `pulsars`, sumbernya sama (kolom `Type` = AXP).",
            ["atnf_pulsar_catalog"],
        )
    else:
        write_category_table(special_dir / "pulsars", atnf)
        write_metadata(
            special_dir / "pulsars" / "metadata.json",
            source="atnf_pulsar_catalog",
            source_url=VIZIER_TAP_URL,
            record_count=atnf.height,
        )
        write_readme(
            special_dir / "pulsars",
            "pulsars",
            f"{atnf.height} pulsar dari ATNF Pulsar Catalogue (VizieR B/psr/psr).\n\n"
            "Semua objek di sini juga bintang neutron; `../neutron_stars/` memuat objek "
            "yang SIMBAD beri tipe `N*` (sensus berbeda, jauh lebih kecil).\n\n"
            "Catatan versi: salinan VizieR ini beku di 2536 pulsar, sedangkan katalog "
            "ATNF yang hidup sudah lewat 3500. Jumlah di sini bukan hasil query yang "
            "terpotong — itu memang seluruh isi tabelnya (lihat notes di registry.py).",
            ["atnf_pulsar_catalog"],
        )
        built.append("pulsars")
        report.object_count += atnf.height

        if "Type" in atnf.columns:
            magnetars = atnf.filter(
                pl.col("Type").is_not_null() & pl.col("Type").str.contains("AXP")
            )
            write_category_table(special_dir / "magnetars", magnetars)
            write_metadata(
                special_dir / "magnetars" / "metadata.json",
                source="atnf_pulsar_catalog",
                source_url=VIZIER_TAP_URL,
                record_count=magnetars.height,
                derived_from=["Type"],
                classification_method="baris ATNF dengan kolom `Type` memuat 'AXP' "
                "(anomalous X-ray pulsar = magnetar menurut katalognya sendiri)",
            )
            write_readme(
                special_dir / "magnetars",
                "magnetars",
                f"{magnetars.height} magnetar: baris ATNF yang kolom `Type`-nya memuat "
                "`AXP` (anomalous X-ray pulsar). Flag itu milik katalognya, bukan "
                "klasifikasi kami.",
                ["atnf_pulsar_catalog"],
            )
            built.append("magnetars")

    # BlackCAT sits alongside the SIMBAD BH list rather than merging into it.
    blackcat = _read_csv(latest_raw_file(raw_root, "blackcat_bh_transients", "blackcat.csv"))
    if blackcat is not None:
        target = special_dir / "black_holes"
        target.mkdir(parents=True, exist_ok=True)
        blackcat.write_parquet(target / "blackcat_xray_transients.parquet")
        write_json(
            target / "blackcat_xray_transients.metadata.json",
            {
                "source": "blackcat_bh_transients",
                "source_url": VIZIER_TAP_URL,
                "record_count": blackcat.height,
                "note": "BlackCAT (Corral-Santana et al. 2016): sensus transien sinar-X "
                "lubang hitam bermassa bintang, termasuk kandidat. Terpisah dari "
                "all.parquet (SIMBAD otype=BH) karena kriterianya berbeda.",
            },
        )

    return built
