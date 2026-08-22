"""Fase 3 builder: solar_system/artificial_satellites/ from CelesTrak
GP (per-group elements) and SATCAT (full catalog, incl. decayed).

by_orbit/ uses documented apogee/perigee/inclination/period thresholds on
SATCAT (not an upstream field) — a standard, commonly-used classification,
not fabricated data. by_purpose/ reuses CelesTrak's own GROUP taxonomy
(each group we pulled already represents a purpose). by_operator/ groups
by SATCAT's OWNER field (country/agency code — not a curated company
taxonomy like "Starlink"/"OneWeb", since SATCAT doesn't carry that; the
brief's example operator names are covered via by_purpose/communications,
which is the celestrak_gp_starlink pull).
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from .common import BuildReport, latest_raw_file, write_category_index, write_category_table, write_metadata, write_text
from ..core.naming import slugify

CELESTRAK_GROUPS_BY_PURPOSE = {
    "communications": ["celestrak_gp_starlink"],
    "navigation": ["celestrak_gp_gps_ops", "celestrak_gp_galileo"],
    "earth_observation": ["celestrak_gp_weather"],
    "science": ["celestrak_gp_science"],
    "military": ["celestrak_gp_military"],
    "cubesat": ["celestrak_gp_cubesat"],
}

ORBIT_THRESHOLDS_NOTE = (
    "Klasifikasi orbit dari kolom APOGEE/PERIGEE/INCLINATION/PERIOD (km, km, deg, menit) "
    "di SATCAT, pakai ambang umum: GEO = period 1400-1450 min & apogee/perigee 35000-36500 km; "
    "LEO = apogee & perigee < 2000 km; MEO = 2000 km <= perigee < 35000 km (bukan GEO); "
    "HEO = eksentrik tinggi (apogee - perigee > 5000 km, di luar LEO); "
    "polar = inclination 80-100 deg; sso = inclination 96-102 deg & LEO altitude."
)


def _load_gp(raw_root: Path, key: str) -> pl.DataFrame | None:
    p = latest_raw_file(raw_root, key, "gp.json")
    if p is None:
        return None
    import json

    records = json.loads(p.read_text())
    if not records:
        return None
    return pl.DataFrame(records)


def build(raw_root: Path, out_root: Path) -> BuildReport:
    report = BuildReport(category="artificial_satellites")

    satcat_path = latest_raw_file(raw_root, "celestrak_satcat", "satcat.csv")
    if satcat_path is None:
        report.note("satcat.csv tidak ditemukan — artificial_satellites/ tidak dibangun")
        return report
    satcat = pl.read_csv(satcat_path, infer_schema_length=20000)
    report.object_count = satcat.height

    # by_orbit/
    orbit_dir = out_root / "by_orbit"
    is_geo = (pl.col("PERIOD") >= 1400) & (pl.col("PERIOD") <= 1450) & (pl.col("APOGEE") >= 35000) & (pl.col("APOGEE") <= 36500)
    is_leo = (pl.col("APOGEE") < 2000) & (pl.col("PERIGEE") < 2000)
    is_heo = (~is_leo) & (~is_geo) & ((pl.col("APOGEE") - pl.col("PERIGEE")) > 5000)
    is_polar = (pl.col("INCLINATION") >= 80) & (pl.col("INCLINATION") <= 100)
    is_sso = (pl.col("INCLINATION") >= 96) & (pl.col("INCLINATION") <= 102) & is_leo
    is_meo = (~is_leo) & (~is_geo) & (~is_heo) & (pl.col("PERIGEE") >= 2000)

    orbit_children = []
    for name, cond in [("leo", is_leo), ("meo", is_meo), ("geo", is_geo), ("heo", is_heo), ("polar", is_polar), ("sso", is_sso)]:
        sub = satcat.filter(cond)
        orbit_children.append(name)
        write_category_table(orbit_dir / name, sub)
        write_metadata(orbit_dir / name / "metadata.json", source="celestrak_satcat", source_url="https://celestrak.org/pub/satcat.csv", record_count=sub.height)
        write_text(orbit_dir / name / "README.md", f"# {name.upper()}\n\n{sub.height} objek. {ORBIT_THRESHOLDS_NOTE}\n")
    write_category_index(orbit_dir, orbit_children, ORBIT_THRESHOLDS_NOTE)

    # by_operator/ (SATCAT OWNER code)
    owner_dir = out_root / "by_operator"
    owner_children = []
    for (owner,), sub in satcat.filter(pl.col("OWNER").is_not_null()).partition_by("OWNER", as_dict=True, include_key=True).items():
        slug = slugify(str(owner))
        owner_children.append(slug)
        write_category_table(owner_dir / slug, sub)
        write_metadata(owner_dir / slug / "metadata.json", source="celestrak_satcat", source_url="https://celestrak.org/pub/satcat.csv", record_count=sub.height)
    write_category_index(owner_dir, owner_children, "Dikelompokkan dari kolom OWNER di SATCAT (kode negara/organisasi, bukan taksonomi operator komersial).")

    # by_purpose/ (from CelesTrak's own per-group pulls)
    purpose_dir = out_root / "by_purpose"
    purpose_children = []
    for purpose, keys in CELESTRAK_GROUPS_BY_PURPOSE.items():
        frames = [df for k in keys if (df := _load_gp(raw_root, k)) is not None]
        if not frames:
            continue
        combined = pl.concat(frames, how="diagonal_relaxed")
        purpose_children.append(purpose)
        write_category_table(purpose_dir / purpose, combined)
        write_metadata(purpose_dir / purpose / "metadata.json", source=" + ".join(keys), source_url="https://celestrak.org/NORAD/elements/gp.php", record_count=combined.height)
        write_text(purpose_dir / purpose / "README.md", f"# {purpose}\n\n{combined.height} objek, dari CelesTrak GROUP={'/'.join(k.replace('celestrak_gp_', '') for k in keys)}.\n")
    write_category_index(purpose_dir, purpose_children, "Dari taksonomi GROUP milik CelesTrak sendiri (starlink/gps-ops+galileo/weather/science/military/cubesat).")

    # space_stations/
    stations = _load_gp(raw_root, "celestrak_gp_stations")
    stations_dir = out_root / "space_stations"
    station_children = []
    if stations is not None:
        for name, match in [("iss", "ISS"), ("tiangong", "TIANGONG")]:
            sub = stations.filter(pl.col("OBJECT_NAME").str.contains(match))
            if sub.height == 0:
                continue
            station_children.append(name)
            write_category_table(stations_dir / name, sub)
            write_metadata(stations_dir / name / "metadata.json", source="celestrak_gp_stations", source_url="https://celestrak.org/NORAD/elements/gp.php?GROUP=stations", record_count=sub.height)
    write_category_index(stations_dir, station_children, "Stasiun luar angkasa aktif, dari CelesTrak GROUP=stations.")

    # decayed/
    decayed = satcat.filter(pl.col("DECAY_DATE").is_not_null())
    write_category_table(out_root / "decayed", decayed)
    write_metadata(out_root / "decayed" / "metadata.json", source="celestrak_satcat", source_url="https://celestrak.org/pub/satcat.csv", record_count=decayed.height)
    write_text(out_root / "decayed" / "README.md", f"# Decayed\n\n{decayed.height} objek dengan DECAY_DATE terisi di SATCAT.\n")

    write_category_table(out_root, satcat)
    write_text(out_root / "README.md", f"# Artificial satellites\n\n{satcat.height} objek total (SATCAT). Lihat by_orbit/, by_operator/, by_purpose/, space_stations/, decayed/.\n")

    return report
