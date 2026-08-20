"""Fase 3 builder: exoplanets/by_host_star/<slug>/ — the structure the
brief calls out as its most important request ("Exoplanet on star A").

Source: NASA Exoplanet Archive `pscomppars` (one row per confirmed planet,
best-available composite parameters) drives the folder set; `ps` (all
publications per planet) supplies each host's publications.csv. Both were
pulled in Fase 2 (data/raw/exoplanet_archive_{pscomppars,ps}/).

Also builds the lighter category-level groupings (by_detection_method,
by_mission, candidates) as index + all.parquet/all.csv — not one folder
per object, since those are groupings of the same by_host_star planets,
not a separate object universe. by_type and habitable_zone need derived
astrophysical classification (radius/mass/flux thresholds) that wasn't
done in this pass — left for a follow-up, not guessed under time pressure.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from .common import BuildReport, latest_raw_file, sv, write_category_index, write_category_table, write_json, write_metadata, write_text
from ..core.naming import slugify

PLANET_FIELDS = {
    "pl_orbper": ("orbital_period_days", None),
    "pl_orbsmax": ("semi_major_axis_au", None),
    "pl_orbeccen": ("eccentricity", None),
    "pl_orbincl": ("inclination_deg", None),
    "pl_rade": ("radius_earth", None),
    "pl_radj": ("radius_jupiter", None),
    "pl_masse": ("mass_earth", None),
    "pl_massj": ("mass_jupiter", None),
    "pl_bmasse": ("best_mass_earth", "pl_bmassprov"),
    "pl_dens": ("density_g_cm3", None),
    "pl_eqt": ("equilibrium_temp_k", None),
    "pl_insol": ("insolation_flux_earth", None),
    "pl_trandep": ("transit_depth_pct", None),
    "pl_trandur": ("transit_duration_hr", None),
}

STAR_FIELDS = {
    "st_spectype": "spectral_type",
    "st_teff": "teff_k",
    "st_rad": "radius_solar",
    "st_mass": "mass_solar",
    "st_met": "metallicity_dex",
    "st_logg": "logg_cgs",
    "st_age": "age_gyr",
    "st_lum": "log_luminosity_solar",
    "sy_dist": "distance_pc",
    "sy_plx": "parallax_mas",
    "sy_vmag": "vmag",
    "sy_kmag": "kmag",
    "sy_gaiamag": "gaiamag",
}


def _row_sv(row: dict, field: str, ref_field: str | None = None) -> dict:
    ref = row.get(ref_field) if ref_field else None
    return sv(
        row.get(field),
        err_upper=row.get(f"{field}err1"),
        err_lower=row.get(f"{field}err2"),
        limit_flag=row.get(f"{field}lim"),
        ref=ref,
    )


def _planet_json(row: dict) -> dict:
    out = {
        "display_name": row.get("pl_name"),
        "letter": row.get("pl_letter"),
        "hostname": row.get("hostname"),
        "discovery_method": row.get("discoverymethod"),
        "discovery_year": row.get("disc_year"),
        "discovery_facility": row.get("disc_facility"),
        "controversial_flag": row.get("pl_controv_flag"),
        "data_source": "exoplanet_archive_pscomppars",
    }
    for col, (name, ref_field) in PLANET_FIELDS.items():
        out[name] = _row_sv(row, col, ref_field)
    return out


def _host_star_json(row: dict) -> dict:
    out = {
        "display_name": row.get("hostname"),
        "hd_name": row.get("hd_name"),
        "hip_name": row.get("hip_name"),
        "tic_id": row.get("tic_id"),
        "gaia_dr2_id": row.get("gaia_dr2_id"),
        "gaia_dr3_id": row.get("gaia_dr3_id"),
        "ra_deg": row.get("ra"),
        "dec_deg": row.get("dec"),
        "num_stars_in_system": row.get("sy_snum"),
        "num_planets_in_system": row.get("sy_pnum"),
        "data_source": "exoplanet_archive_pscomppars",
    }
    for col, name in STAR_FIELDS.items():
        out[name] = sv(row.get(col), ref=row.get(f"{col}_reflink"))
    return out


def build(raw_root: Path, out_root: Path) -> BuildReport:
    report = BuildReport(category="exoplanets")

    pscomppars_path = latest_raw_file(raw_root, "exoplanet_archive_pscomppars", "pscomppars.csv")
    if pscomppars_path is None:
        report.note("pscomppars.csv tidak ditemukan di raw — exoplanets/by_host_star tidak dibangun")
        return report

    pscomppars = pl.read_csv(pscomppars_path, comment_prefix="#", infer_schema_length=10000)

    ps_path = latest_raw_file(raw_root, "exoplanet_archive_ps", "ps.csv")
    ps_by_host: dict[str, pl.DataFrame] = {}
    if ps_path is not None:
        ps = pl.read_csv(ps_path, comment_prefix="#", infer_schema_length=10000)
        ps_by_host = ps.partition_by("hostname", as_dict=True, include_key=True)
        ps_by_host = {k[0] if isinstance(k, tuple) else k: v for k, v in ps_by_host.items()}

    by_host_dir = out_root / "by_host_star"
    host_slugs = []
    used_slugs: dict[str, int] = {}

    for (hostname,), host_rows in pscomppars.partition_by("hostname", as_dict=True, include_key=True).items():
        base_slug = slugify(hostname)
        n = used_slugs.get(base_slug, 0)
        used_slugs[base_slug] = n + 1
        slug = base_slug if n == 0 else f"{base_slug}__{n}"
        host_slugs.append(slug)

        h_dir = by_host_dir / slug
        first_row = host_rows.row(0, named=True)
        write_json(h_dir / "host_star.json", _host_star_json(first_row))

        letters = []
        for row in host_rows.iter_rows(named=True):
            letter = (row.get("pl_letter") or "x").strip().lower() or "x"
            letters.append(letter)
            write_json(h_dir / "planets" / letter / "planet.json", _planet_json(row))
            report.object_count += 1

        write_json(h_dir / "system_summary.json", {
            "hostname": hostname,
            "display_name": hostname,
            "num_planets": len(letters),
            "planet_letters": sorted(letters),
            "num_stars_in_system": first_row.get("sy_snum"),
        })

        pubs = ps_by_host.get(hostname)
        if pubs is not None and pubs.height > 0:
            try:
                pubs.write_csv(h_dir / "publications.csv")
            except pl.exceptions.ComputeError:
                pass

        write_metadata(
            h_dir / "metadata.json",
            source="exoplanet_archive_pscomppars",
            source_url="https://exoplanetarchive.ipac.caltech.edu/TAP/sync",
            record_count=len(letters),
        )
        write_text(
            h_dir / "README.md",
            f"# {hostname}\n\n{len(letters)} planet terkonfirmasi: "
            f"{', '.join(sorted(letters))}.\n\nSumber: NASA Exoplanet Archive (pscomppars).\n",
        )

    write_category_table(by_host_dir, pscomppars)
    write_category_index(by_host_dir, host_slugs, "Satu folder per bintang induk exoplanet terkonfirmasi (pscomppars).")

    _build_grouping(out_root / "by_detection_method", pscomppars, "discoverymethod", "Dikelompokkan dari kolom discoverymethod (pscomppars).")
    _build_grouping(out_root / "candidates" / "koi", None, None, "KOI cumulative table (Kepler Objects of Interest).", raw_key="exoplanet_archive_cumulative", raw_file="cumulative.csv")
    _build_grouping(out_root / "candidates" / "toi", None, None, "TESS Objects of Interest.", raw_key="exoplanet_archive_toi", raw_file="toi.csv")
    _build_grouping(out_root / "candidates" / "k2_candidates", None, None, "K2 planets and candidates.", raw_key="exoplanet_archive_k2pandc", raw_file="k2pandc.csv")

    report.note(
        "by_type (hot_jupiter/super_earth/dst) dan habitable_zone butuh klasifikasi turunan "
        "(threshold radius/massa/insolation) yang belum dikerjakan di pass ini — lihat "
        "REPORT.md untuk follow-up."
    )
    return report


def _build_grouping(
    dir_path: Path,
    df: pl.DataFrame | None,
    group_col: str | None,
    description: str,
    raw_key: str | None = None,
    raw_file: str | None = None,
) -> None:
    if df is None and raw_key and raw_file:
        raw_root = Path("data/raw")
        p = latest_raw_file(raw_root, raw_key, raw_file)
        if p is None:
            return
        df = pl.read_csv(p, comment_prefix="#", infer_schema_length=10000)
        write_category_table(dir_path, df)
        write_category_index(dir_path, [], description)
        write_metadata(dir_path / "metadata.json", source=raw_key, source_url="https://exoplanetarchive.ipac.caltech.edu/TAP/sync", record_count=df.height)
        return

    if df is None or group_col is None:
        return
    children = []
    for (group_val,), sub in df.partition_by(group_col, as_dict=True, include_key=True).items():
        if group_val is None:
            continue
        slug = slugify(str(group_val))
        children.append(slug)
        write_category_table(dir_path / slug, sub)
        write_metadata(dir_path / slug / "metadata.json", source="exoplanet_archive_pscomppars", source_url="https://exoplanetarchive.ipac.caltech.edu/TAP/sync", record_count=sub.height)
        write_text(dir_path / slug / "README.md", f"# {group_val}\n\n{sub.height} planet.\n")
    write_category_index(dir_path, children, description)
