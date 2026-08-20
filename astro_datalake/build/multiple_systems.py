"""Fase 3 builder: multiple_systems/{binary,triple,quadruple,higher_order,
star_clusters}/ from WDS, SB9, and MSC (data/raw/{wds_catalog,sb9_catalog,
msc_catalog}/) plus star_clusters from OpenNGC's own Type column (OCl,
GCl, *Ass).

Per-named-system leaf folders (e.g. "alpha_centauri/") are NOT built here:
none of WDS/SB9/MSC carry common star names directly (MSC's `SimbadName`
is catalog designations like "ADS 2236", not "Alpha Centauri"), and
resolving that needs a name crossmatch against HYG/SIMBAD that's deferred
along with the rest of the crosswalk work (see catalog.py). triple/
quadruple/higher_order use MSC's own `Nc` (component count) column.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from .common import BuildReport, latest_raw_file, write_category_index, write_category_table, write_metadata, write_text


def build(raw_root: Path, out_root: Path) -> BuildReport:
    report = BuildReport(category="multiple_systems")

    binary_dir = out_root / "binary"
    binary_children = []

    wds_path = latest_raw_file(raw_root, "wds_catalog", "wds.csv")
    if wds_path is not None:
        wds = pl.read_csv(wds_path, infer_schema_length=20000, ignore_errors=True)
        write_category_table(binary_dir / "wds_all", wds)
        write_metadata(binary_dir / "wds_all" / "metadata.json", source="wds_catalog (VizieR B/wds)", source_url="https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync", record_count=wds.height)
        write_text(binary_dir / "wds_all" / "README.md", f"# WDS\n\n{wds.height} sistem, Washington Double Star Catalog.\n")
        binary_children.append("wds_all")
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
            write_category_table(binary_dir / sub_name, df)
            write_metadata(binary_dir / sub_name / "metadata.json", source="sb9_catalog (VizieR B/sb9)", source_url="https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync", record_count=df.height)
            binary_children.append(sub_name)
            if name == "main":
                report.object_count += df.height

    msc_path = latest_raw_file(raw_root, "msc_catalog", "catalog.csv")
    msc = None
    if msc_path is not None:
        msc = pl.read_csv(msc_path, infer_schema_length=20000, ignore_errors=True)
        write_category_table(binary_dir / "msc_all", msc)
        write_metadata(binary_dir / "msc_all" / "metadata.json", source="msc_catalog (VizieR J/ApJS/235/6)", source_url="https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync", record_count=msc.height)
        binary_children.append("msc_all")

    write_category_index(binary_dir, binary_children, "Katalog biner mentah (WDS/SB9/MSC), belum di-resolve ke nama umum.")

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

    report.note("Folder per-sistem bernama (mis. alpha_centauri/) belum dibangun — butuh crossmatch nama yang di-defer ke catalog.py/crosswalk.")
    return report
