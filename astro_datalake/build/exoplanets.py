"""Fase 3 builder: exoplanets/by_host_star/<slug>/ — the structure the
brief calls out as its most important request ("Exoplanet on star A").

Source: NASA Exoplanet Archive `pscomppars` (one row per confirmed planet,
best-available composite parameters) drives the folder set; `ps` (all
publications per planet) supplies each host's publications.csv. Both were
pulled in Fase 2 (data/raw/exoplanet_archive_{pscomppars,ps}/).

Also builds the lighter category-level groupings (by_detection_method,
by_mission, candidates) as index + all.parquet/all.csv — not one folder
per object, since those are groupings of the same by_host_star planets,
not a separate object universe.

by_type/ and habitable_zone/ (added in Fase 5) are the same kind of
grouping, except the grouping key is computed rather than read off a
column: build/classify.py turns radius/mass/period into a size and thermal
class, and Kopparapu et al. (2013) stellar-flux limits into a habitable-zone
verdict. Every planet also carries the derived block inside its own
planet.json under `derived_classification`, with the rule and the input
values that produced it, so nothing computed can be mistaken for something
measured.
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

ARCHIVE_TAP_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"

BY_TYPE_DESCRIPTIONS = {
    "terrestrial": f"Radius < {classify.RADIUS_BINS_EARTH[0][2]} R_Bumi (atau massa < 2 M_Bumi kalau radius tidak ada).",
    "super_earth": "Radius 1,25-1,8 R_Bumi — di bawah lembah radius Fulton et al. (2017).",
    "sub_neptune": "Radius 1,8-4 R_Bumi (mini-Neptunus), di atas lembah radius.",
    "neptune_like": "Radius 4-10 R_Bumi, seukuran Neptunus sampai Saturnus.",
    "gas_giant": "Radius >= 10 R_Bumi (atau massa >= 50 M_Bumi kalau radius tidak ada).",
    "hot_jupiter": "Raksasa gas dengan periode orbit < 10 hari.",
    "warm_jupiter": "Raksasa gas dengan periode orbit 10-200 hari.",
    "cold_jupiter": "Raksasa gas dengan periode orbit >= 200 hari.",
    "hot_neptune": "Seukuran Neptunus dengan periode orbit < 10 hari.",
    "warm_neptune": "Seukuran Neptunus dengan periode orbit 10-200 hari.",
    "cold_neptune": "Seukuran Neptunus dengan periode orbit >= 200 hari.",
    "ultra_short_period": "Periode orbit < 1 hari, ukuran apa pun.",
}

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


def _f(row: dict, key: str) -> float | None:
    value = row.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _derive(row: dict) -> dict:
    """Everything build/classify.py can say about one pscomppars row.

    Carries the inputs alongside the verdict: `size_class_basis` says
    whether the size label came from a radius or a fallback mass, and
    `insolation_provenance` says whether the flux is the archive's own
    pl_insol or was recomputed as L/a^2.
    """
    radius = _f(row, "pl_rade")
    mass = _f(row, "pl_bmasse") or _f(row, "pl_masse")
    period = _f(row, "pl_orbper")

    size, basis = classify.size_class(radius, mass)
    flux, provenance = classify.insolation_earth(
        insol=_f(row, "pl_insol"),
        log_luminosity_solar=_f(row, "st_lum"),
        semi_major_axis_au=_f(row, "pl_orbsmax"),
    )
    hz = classify.habitable_zone_flux_limits(_f(row, "st_teff"))
    zone = hz.zone_of(flux) if hz else None

    return {
        "pl_name": row.get("pl_name"),
        "hostname": row.get("hostname"),
        "types": classify.exoplanet_types(radius, mass, period),
        "size_class": size,
        "size_class_basis": basis,
        "thermal_class": classify.thermal_class(period),
        "potentially_rocky": classify.is_potentially_rocky(radius, mass),
        "insolation_earth": flux,
        "insolation_provenance": provenance,
        "habitable_zone": zone,
        "hz_teff_k": hz.teff_k if hz else None,
        "hz_recent_venus": hz.recent_venus if hz else None,
        "hz_runaway_greenhouse": hz.runaway_greenhouse if hz else None,
        "hz_maximum_greenhouse": hz.maximum_greenhouse if hz else None,
        "hz_early_mars": hz.early_mars if hz else None,
    }


DERIVED_METHOD = (
    "build/classify.py: kelas ukuran dari pl_rade (fallback pl_bmasse), kelas termal dari "
    "pl_orbper, zona layak huni dari batas fluks Kopparapu et al. (2013) pada st_teff "
    "dibandingkan pl_insol (fallback st_lum/pl_orbsmax^2). Semua turunan, bukan hasil ukur."
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
    derived = _derive(row)
    derived.pop("pl_name", None)
    derived.pop("hostname", None)
    out["derived_classification"] = {"method": DERIVED_METHOD, **derived}
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
    derived_rows: list[dict] = []

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
            derived_rows.append(_derive(row))
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
    _build_grouping(out_root / "candidates" / "koi", None, None, "KOI cumulative table (Kepler Objects of Interest).", raw_key="exoplanet_archive_cumulative", raw_file="cumulative.csv", raw_root=raw_root)
    _build_grouping(out_root / "candidates" / "toi", None, None, "TESS Objects of Interest.", raw_key="exoplanet_archive_toi", raw_file="toi.csv", raw_root=raw_root)
    _build_grouping(out_root / "candidates" / "k2_candidates", None, None, "K2 planets and candidates.", raw_key="exoplanet_archive_k2pandc", raw_file="k2pandc.csv", raw_root=raw_root)

    derived = pl.DataFrame(
        derived_rows,
        schema_overrides={"types": pl.List(pl.Utf8), "potentially_rocky": pl.Boolean},
    )
    _build_by_type(out_root / "by_type", pscomppars, derived, report)
    _build_habitable_zone(out_root / "habitable_zone", pscomppars, derived, report)
    return report


def _joined(pscomppars: pl.DataFrame, derived: pl.DataFrame) -> pl.DataFrame:
    """pscomppars + the derived columns, joined on the planet name."""
    return pscomppars.join(derived.drop("hostname"), on="pl_name", how="left")


def _build_by_type(dir_path: Path, pscomppars: pl.DataFrame, derived: pl.DataFrame, report: BuildReport) -> None:
    joined = _joined(pscomppars, derived)
    children = []
    for label, description in BY_TYPE_DESCRIPTIONS.items():
        sub = joined.filter(pl.col("types").list.contains(label))
        if sub.height == 0:
            continue
        children.append(label)
        target = dir_path / label
        write_category_table(target, sub.drop("types"))
        write_metadata(
            target / "metadata.json",
            source="exoplanet_archive_pscomppars",
            source_url=ARCHIVE_TAP_URL,
            record_count=sub.height,
            derived_from=["pl_rade", "pl_bmasse", "pl_masse", "pl_orbper"],
            classification_method=DERIVED_METHOD,
        )
        write_readme(
            target,
            label,
            f"{sub.height} planet.\n\n{description}\n\nKategori ini **turunan**, dihitung di "
            "`build/classify.py` dari kolom pscomppars — bukan label yang ada di arsip. "
            "Satu planet bisa muncul di beberapa kategori (mis. `gas_giant` + `hot_jupiter`).",
            ["exoplanet_archive_pscomppars"],
        )
    unclassified = joined.filter(pl.col("types").list.len() == 0).height
    write_category_index(
        dir_path,
        children,
        "Kelas ukuran/termal turunan (lihat classify.py). Kategori sengaja tumpang tindih; "
        f"{unclassified} planet tanpa radius maupun massa tidak masuk kategori ukuran mana pun.",
        ["exoplanet_archive_pscomppars"],
    )
    report.note(f"by_type: {len(children)} kategori turunan, {unclassified} planet tanpa radius/massa")


def _build_habitable_zone(dir_path: Path, pscomppars: pl.DataFrame, derived: pl.DataFrame, report: BuildReport) -> None:
    joined = _joined(pscomppars, derived)
    buckets = {
        "conservative": pl.col("habitable_zone") == "conservative",
        "optimistic": pl.col("habitable_zone").is_in(["conservative", "optimistic"]),
        "conservative_rocky": (pl.col("habitable_zone") == "conservative") & pl.col("potentially_rocky"),
    }
    descriptions = {
        "conservative": "Fluks bintang antara batas runaway greenhouse dan maximum greenhouse "
        "(Kopparapu et al. 2013) — definisi konservatif.",
        "optimistic": "Definisi optimis (recent Venus - early Mars); memuat semua yang konservatif.",
        "conservative_rocky": "Zona konservatif DAN berpotensi berbatu (radius <= 1,6 R_Bumi, "
        "atau massa <= 10 M_Bumi kalau radius tidak ada).",
    }
    children = []
    for name, condition in buckets.items():
        sub = joined.filter(condition)
        children.append(name)
        target = dir_path / name
        write_category_table(target, sub.drop("types"))
        write_metadata(
            target / "metadata.json",
            source="exoplanet_archive_pscomppars",
            source_url=ARCHIVE_TAP_URL,
            record_count=sub.height,
            derived_from=["st_teff", "pl_insol", "st_lum", "pl_orbsmax", "pl_rade", "pl_bmasse"],
            classification_method=DERIVED_METHOD,
        )
        write_readme(
            target,
            name,
            f"{sub.height} planet.\n\n{descriptions[name]}\n\n"
            "Batas fluks dihitung ulang per bintang dari `st_teff` dengan polinomial "
            "Kopparapu et al. (2013, ApJ 765, 131; koefisien erratum 2014), yang hanya "
            "berlaku untuk 2600 K <= Teff <= 7200 K — bintang di luar rentang itu tidak "
            "diklasifikasikan sama sekali, bukan diekstrapolasi. Kolom `hz_*` di "
            "`all.parquet` menyimpan batas yang dipakai untuk tiap planet.",
            ["exoplanet_archive_pscomppars"],
        )
    # Planets the polynomial refuses: no Teff at all, or a host outside
    # 2600-7200 K. They are listed rather than silently dropped — TRAPPIST-1
    # (Teff 2566 K) lands here, and a reader looking for it deserves to find
    # out why instead of concluding the pipeline lost it.
    unassessable = joined.filter(pl.col("hz_teff_k").is_null()).with_columns(
        pl.when(pl.col("st_teff").is_null())
        .then(pl.lit("st_teff tidak ada di pscomppars"))
        .otherwise(
            pl.lit("st_teff di luar rentang validitas Kopparapu 2600-7200 K")
        )
        .alias("_unassessable_reason")
    )
    target = dir_path / "_unassessable"
    write_category_table(target, unassessable.drop("types"))
    write_metadata(
        target / "metadata.json",
        source="exoplanet_archive_pscomppars",
        source_url=ARCHIVE_TAP_URL,
        record_count=unassessable.height,
        derived_from=["st_teff"],
        classification_method=DERIVED_METHOD,
    )
    write_readme(
        target,
        "_unassessable",
        f"{unassessable.height} planet yang **tidak** diklasifikasikan zona layak huninya, "
        "dengan alasannya di kolom `_unassessable_reason`.\n\n"
        "Polinomial Kopparapu et al. (2013) hanya valid untuk 2600 K <= Teff <= 7200 K. "
        "Di luar itu jawaban yang jujur adalah 'tidak dinilai', bukan ekstrapolasi — "
        "TRAPPIST-1 (Teff 2566 K) misalnya ada di sini, bukan karena planetnya diragukan "
        "tapi karena bintangnya di bawah lantai validitas rumusnya.",
        ["exoplanet_archive_pscomppars"],
    )
    children.append("_unassessable")

    no_teff = unassessable.height
    write_category_index(
        dir_path,
        children,
        "Zona layak huni turunan (Kopparapu et al. 2013). "
        f"{no_teff} planet tidak bisa dinilai (Teff hilang atau di luar 2600-7200 K).",
        ["exoplanet_archive_pscomppars"],
    )
    conservative = joined.filter(buckets["conservative"]).height
    report.note(f"habitable_zone: {conservative} planet di zona konservatif, {no_teff} tidak dapat dinilai")


def _build_grouping(
    dir_path: Path,
    df: pl.DataFrame | None,
    group_col: str | None,
    description: str,
    raw_key: str | None = None,
    raw_file: str | None = None,
    raw_root: Path | None = None,
) -> None:
    if df is None and raw_key and raw_file:
        # raw_root used to be hardcoded to Path("data/raw") here, which quietly
        # skipped the candidate tables whenever the build ran from anywhere but
        # the project root.
        p = latest_raw_file(raw_root or Path("data/raw"), raw_key, raw_file)
        if p is None:
            return
        df = pl.read_csv(p, comment_prefix="#", infer_schema_length=10000)
        write_category_table(dir_path, df)
        write_category_index(dir_path, [], description, [raw_key])
        write_metadata(dir_path / "metadata.json", source=raw_key, source_url=ARCHIVE_TAP_URL, record_count=df.height)
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
        write_metadata(dir_path / slug / "metadata.json", source="exoplanet_archive_pscomppars", source_url=ARCHIVE_TAP_URL, record_count=sub.height)
        write_readme(dir_path / slug, str(group_val), f"{sub.height} planet.", ["exoplanet_archive_pscomppars"])
    write_category_index(dir_path, children, description, ["exoplanet_archive_pscomppars"])
