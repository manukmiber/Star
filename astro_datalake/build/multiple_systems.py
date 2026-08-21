"""Fase 3 builder: multiple_systems/{binary,triple,quadruple,higher_order,
star_clusters}/ from WDS, SB9, and MSC (data/raw/{wds_catalog,sb9_catalog,
msc_catalog}/) plus star_clusters from OpenNGC's own Type column (OCl,
GCl, *Ass).

Fase 5 adds the per-named-system leaf folders the brief asks for
("alpha_centauri/", "sirius/", ...). None of WDS/SB9/MSC carries a common
star name — MSC's `SimbadName` is a catalogue designation like "ADS 2236" —
so the names come from a positional cross-match against HYG's `proper`
column (build/crossmatch.py, 10 arcsec). Every leaf records the separation
its identification was accepted at, so a borderline match is visible rather
than implied. Only HYG-named stars that actually appear in the WDS get a
folder: a star with no double-star entry is not a multiple system, and
inventing one would be worse than an absent folder.

The raw catalogue dumps live under `_catalogs/` so that `binary/` holds
systems and only systems. triple/quadruple/higher_order use MSC's own `Nc`
(component count) column.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

from .common import (
    BuildReport,
    latest_raw_file,
    write_category_index,
    write_category_table,
    write_json,
    write_metadata,
    write_readme,
    write_text,
)
from .crossmatch import match_nearest
from ..core.naming import slugify

VIZIER_TAP_URL = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"
HYG_URL = "https://raw.githubusercontent.com/astronexus/HYG-Database/main/hyg/CURRENT/hygdata_v41.csv"

# 30 arcsec. The match count saturates here: 274 named stars match inside
# 5", 293 inside 30", and 294 inside 120" — so the window is wide enough to
# catch the high-proper-motion cases (Alpha Centauri's WDS position is 16"
# from HYG's) without buying anything but noise beyond it. WDS row density is
# ~4/deg^2, so a chance alignment inside 30" runs about 1 in 1000.
NAME_MATCH_TOLERANCE_ARCSEC = 30.0


def build(raw_root: Path, out_root: Path) -> BuildReport:
    report = BuildReport(category="multiple_systems")

    binary_dir = out_root / "binary"
    catalogs_dir = out_root / "_catalogs"
    catalog_children = []
    wds: pl.DataFrame | None = None

    wds_path = latest_raw_file(raw_root, "wds_catalog", "wds.csv")
    if wds_path is not None:
        wds = pl.read_csv(wds_path, infer_schema_length=20000, ignore_errors=True)
        write_category_table(catalogs_dir / "wds_all", wds)
        write_metadata(catalogs_dir / "wds_all" / "metadata.json", source="wds_catalog (VizieR B/wds)", source_url=VIZIER_TAP_URL, record_count=wds.height)
        write_readme(catalogs_dir / "wds_all", "WDS", f"{wds.height} baris, Washington Double Star Catalog.", ["wds_catalog"])
        catalog_children.append("wds_all")
        report.object_count += wds.height

    sb9_dir = raw_root / "sb9_catalog"
    dated = sorted((p for p in sb9_dir.iterdir() if p.is_dir()), reverse=True) if sb9_dir.exists() else []
    if dated:
        for name in ("main", "orbits", "alias"):
            f = dated[0] / f"{name}.csv"
            if not f.exists():
                continue
            df = pl.read_csv(f, infer_schema_length=20000, ignore_errors=True)
            sub_name = f"sb9_{name}"
            write_category_table(catalogs_dir / sub_name, df)
            write_metadata(catalogs_dir / sub_name / "metadata.json", source="sb9_catalog (VizieR B/sb9)", source_url=VIZIER_TAP_URL, record_count=df.height)
            write_readme(catalogs_dir / sub_name, sub_name, f"{df.height} baris tabel SB9 `{name}`.", ["sb9_catalog"])
            catalog_children.append(sub_name)
            if name == "main":
                report.object_count += df.height

    msc_path = latest_raw_file(raw_root, "msc_catalog", "catalog.csv")
    msc = None
    if msc_path is not None:
        msc = pl.read_csv(msc_path, infer_schema_length=20000, ignore_errors=True)
        write_category_table(catalogs_dir / "msc_all", msc)
        write_metadata(catalogs_dir / "msc_all" / "metadata.json", source="msc_catalog (VizieR J/ApJS/235/6)", source_url=VIZIER_TAP_URL, record_count=msc.height)
        write_readme(catalogs_dir / "msc_all", "MSC", f"{msc.height} baris Multiple Star Catalog.", ["msc_catalog"])
        catalog_children.append("msc_all")

    write_category_index(
        catalogs_dir,
        catalog_children,
        "Dump katalog mentah (WDS/SB9/MSC) apa adanya, tanpa resolusi nama.",
        ["wds_catalog", "sb9_catalog", "msc_catalog"],
    )

    named_systems = _build_named_binaries(raw_root, binary_dir, wds, report)
    write_category_index(
        binary_dir,
        named_systems,
        "Satu folder per sistem ganda yang punya nama umum, hasil cross-match posisi "
        f"WDS x HYG (toleransi {NAME_MATCH_TOLERANCE_ARCSEC:.0f} arcsec). Katalog mentahnya "
        "ada di `../_catalogs/`.",
        ["wds_catalog", "hyg_database"],
    )

    if msc is not None and "Nc" in msc.columns:
        for name, cond in [
            ("triple", pl.col("Nc") == 3),
            ("quadruple", pl.col("Nc") == 4),
            ("higher_order", pl.col("Nc") > 4),
        ]:
            sub = msc.filter(cond)
            dir_path = out_root / name
            write_category_table(dir_path, sub)
            write_metadata(dir_path / "metadata.json", source="msc_catalog", source_url="https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync", record_count=sub.height)
            write_text(dir_path / "README.md", f"# {name}\n\n{sub.height} baris MSC dengan Nc={'>4' if name == 'higher_order' else ('3' if name == 'triple' else '4')}.\n")
            report.object_count += sub.height

    ngc_path = latest_raw_file(raw_root, "openngc", "NGC.csv")
    clusters_dir = out_root / "star_clusters"
    cluster_children = []
    if ngc_path is not None:
        ngc = pl.read_csv(ngc_path, separator=";", infer_schema_length=20000)
        for name, type_code in [("open", "OCl"), ("globular", "GCl"), ("associations", "*Ass")]:
            sub = ngc.filter(pl.col("Type") == type_code)
            dir_path = clusters_dir / name
            write_category_table(dir_path, sub)
            write_metadata(dir_path / "metadata.json", source="openngc", source_url="https://github.com/mattiaverga/OpenNGC", record_count=sub.height)
            write_text(dir_path / "README.md", f"# {name}\n\n{sub.height} objek OpenNGC Type={type_code}.\n")
            cluster_children.append(name)
            report.object_count += sub.height
    write_category_index(clusters_dir, cluster_children, "Gugus bintang, dari kolom Type di OpenNGC (OCl/GCl/*Ass).")

    return report


def _build_named_binaries(
    raw_root: Path, binary_dir: Path, wds: pl.DataFrame | None, report: BuildReport
) -> list[str]:
    """binary/<slug>/ for every HYG-named star with a WDS entry at its position."""
    hyg_path = latest_raw_file(raw_root, "hyg_database", "hygdata_v41.csv")
    if wds is None or hyg_path is None:
        report.note("binary/<nama_sistem>: butuh wds_catalog + hyg_database di raw, dilewati")
        return []

    hyg = pl.read_csv(hyg_path, infer_schema_length=20000)
    named = hyg.filter(
        pl.col("proper").is_not_null()
        & (pl.col("proper") != "")
        & pl.col("ra").is_not_null()
        & pl.col("dec").is_not_null()
    )
    if named.height == 0:
        return []

    # HYG stores RA in hours; WDS RAJ2000 is in degrees.
    target_ra = named["ra"].to_numpy() * 15.0
    target_dec = named["dec"].to_numpy()

    wds_positioned = wds.filter(pl.col("RAJ2000").is_not_null() & pl.col("DEJ2000").is_not_null())
    idx, sep = match_nearest(
        target_ra,
        target_dec,
        wds_positioned["RAJ2000"].to_numpy(),
        wds_positioned["DEJ2000"].to_numpy(),
        NAME_MATCH_TOLERANCE_ARCSEC,
    )

    wds_rows = wds_positioned.to_dicts()
    slugs: list[str] = []
    used: dict[str, int] = {}

    for i, star in enumerate(named.iter_rows(named=True)):
        if idx[i] < 0:
            continue
        wds_row = wds_rows[int(idx[i])]
        wds_id = (wds_row.get("WDS") or "").strip()

        base = slugify(star["proper"])
        n = used.get(base, 0)
        used[base] = n + 1
        slug = base if n == 0 else f"{base}__{slugify(wds_id) or n}"
        slugs.append(slug)
        target = binary_dir / slug

        # All WDS rows sharing this designation = all measured components.
        components = wds_positioned.filter(pl.col("WDS") == wds_id) if wds_id else None
        if components is not None and components.height:
            target.mkdir(parents=True, exist_ok=True)
            components.write_csv(target / "components.csv")

        write_json(target / "system.json", {
            "display_name": star["proper"],
            "wds_designation": wds_id or None,
            "discoverer_code": (wds_row.get("Disc") or "").strip() or None,
            "components_in_wds": int(components.height) if components is not None else None,
            "component_labels": (wds_row.get("Comp") or "").strip() or None,
            "primary_magnitude": wds_row.get("mag1"),
            "secondary_magnitude": wds_row.get("mag2"),
            "separation_arcsec_last": wds_row.get("sep2"),
            "position_angle_deg_last": wds_row.get("pa2"),
            "spectral_type": (wds_row.get("SpType") or "").strip() or None,
            "hyg_id": star.get("id"),
            "hip": star.get("hip"),
            "hd": star.get("hd"),
            "constellation": star.get("con"),
            "distance_pc": star.get("dist"),
            "ra_deg": float(target_ra[i]),
            "dec_deg": float(target_dec[i]),
            "identification": {
                "method": "cross-match posisi HYG proper-name -> WDS RAJ2000/DEJ2000",
                "separation_arcsec": round(float(sep[i]), 3),
                "tolerance_arcsec": NAME_MATCH_TOLERANCE_ARCSEC,
                "caveat": "Nama umum berasal dari HYG, bukan dari WDS. Identifikasi "
                "berbasis posisi: makin besar separation_arcsec, makin perlu dicek ulang. "
                "Separation di atas ~2 arcsec hampir selalu bintang bergerak-diri tinggi "
                "(posisi WDS dicatat pada epoch pengukuran, HYG pada J2000), bukan salah "
                "pasangan. Dua nama HYG yang menunjuk komponen berbeda dari satu sistem "
                "(mis. Rigil Kentaurus dan Toliman) menghasilkan dua folder dengan "
                "wds_designation yang sama.",
            },
        })
        write_metadata(
            target / "metadata.json",
            source="wds_catalog",
            source_url=VIZIER_TAP_URL,
            record_count=int(components.height) if components is not None else 1,
            derived_from=["RAJ2000", "DEJ2000", "proper"],
            classification_method=(
                "build/crossmatch.py match_nearest(), toleransi "
                f"{NAME_MATCH_TOLERANCE_ARCSEC:.0f} arcsec"
            ),
        )
        write_readme(
            target,
            star["proper"],
            f"Sistem ganda WDS `{wds_id}`"
            + (f", {components.height} baris komponen di `components.csv`." if components is not None else ".")
            + f"\n\nDicocokkan ke nama umum HYG pada jarak {float(sep[i]):.2f} arcsec.",
            ["wds_catalog", "hyg_database"],
        )

    report.note(f"binary/: {len(slugs)} sistem bernama dari {named.height} bintang HYG bernama")
    return slugs

