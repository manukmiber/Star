"""Fase 3 builder: sun/, planets/, dwarf_planets/{pluto}/ and their moons.

Sources used (all already in data/raw/, never re-fetched here):
  - jpl_horizons: per-body OBJ_DATA free-text physical parameters (Sun, the
    8 planets, Pluto) — regex-extracted, see PHYSICAL_FIELD_PATTERNS.
  - jpl_sat_phys_par: GM / mean radius / mean density for well-characterized
    moons (46 of 460 — most irregular moons have no measured physical
    parameters yet, which is a real gap in the upstream data, not ours).
  - jpl_sat_elem: mean orbital elements for all 460 numbered/named moons.
  - jpl_sat_discovery: discoverer / year for named moons.

nssdc_planetary_factsheet is NOT used — see its notes in sources/registry.py
(the endpoint 307-redirects to an unrelated NASA landing page; dead despite
returning HTTP 200 during Fase 1's status-code-only probe).
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl

from .common import BuildReport, latest_raw_dir, sv, write_category_index, write_category_table, write_json, write_metadata, write_text
from .html_tables import parse_table_by_selector
from ..core.naming import planet_slug, slugify

G_NEWTON = 6.6743e-11  # m^3 kg^-1 s^-2 (CODATA)

PLANETS = [
    (1, "Mercury", "mercury"),
    (2, "Venus", "venus"),
    (3, "Earth", "earth"),
    (4, "Mars", "mars"),
    (5, "Jupiter", "jupiter"),
    (6, "Saturn", "saturn"),
    (7, "Uranus", "uranus"),
    (8, "Neptune", "neptune"),
]

PHYSICAL_FIELD_PATTERNS: dict[str, list[str]] = {
    "mass_1e24_kg": [r"Mass\s*x?10\^?24\s*\(?kg\)?\s*=\s*([\d.]+)", r"Mass,\s*10\^24\s*kg\s*=\s*([\d.]+)"],
    "vol_mean_radius_km": [r"Vol\.?\s*Mean Radius(?:\s*\(km\))?\s*=\s*([\d.]+)"],
    "equatorial_radius_km": [r"Equ\.?\s*radius,?\s*km\s*=\s*([\d.]+)"],
    "density_g_cm3": [r"Density,?\s*g/cm\^?3\s*=\s*([\d.]+)"],
    "gm_km3_s2": [r"GM,?\s*km\^?3/s\^?2\s*=\s*([\d.]+)"],
    "sidereal_rotation_hr": [r"Mean sidereal day,?\s*hr\s*=\s*([\d.]+)", r"Sidereal rot period,?\s*hr\s*=\s*([\d.]+)"],
    "mean_solar_day_s": [r"Mean solar day.*?,\s*s\s*=\s*([\d.]+)"],
    "surface_gravity_m_s2": [r"g_e,?\s*m/s\^?2.*?=\s*([\d.]+)", r"Surface gravity,?\s*m/s\^?2\s*=\s*([\d.]+)"],
    "escape_velocity_km_s": [r"Escape velocity,?\s*km/s\s*=\s*([\d.]+)"],
    "sidereal_orbit_period_days": [r"Sidereal orb\. period,?\s*d(?:ay)?\s*=\s*([\d.]+)", r"Sidereal orbit period\s*=\s*([\d.]+)\s*d"],
}


def _extract_fields(text: str) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for field, patterns in PHYSICAL_FIELD_PATTERNS.items():
        value = None
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                try:
                    value = float(m.group(1))
                except ValueError:
                    value = None
                break
        out[field] = value
    return out


def _load_horizons(raw_root: Path, name: str) -> dict:
    d = latest_raw_dir(raw_root, "jpl_horizons")
    if d is None:
        return {}
    f = d / f"{name}.json"
    if not f.exists():
        return {}
    import json

    payload = json.loads(f.read_text())
    text = payload.get("result", "")
    fields = _extract_fields(text)
    fields["_raw_obj_data"] = text
    return fields


def _to_float(s: str) -> float | None:
    s = s.strip()
    if not s or s in {"n/a", "-", "*"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _load_phys_par(raw_root: Path) -> dict[tuple[str, str], dict]:
    d = latest_raw_dir(raw_root, "jpl_sat_phys_par")
    if d is None:
        return {}
    html = (d / "phys_par.html").read_text()
    records = parse_table_by_selector(html, {"id": "sat_phys_par"})
    out = {}
    for r in records:
        key = (r["Planet"], r["Satellite"])
        out[key] = {
            "gm_km3_s2": sv(_to_float(r["GM (km 3 /s 2 ) value"]), ref=r.get("GM (km 3 /s 2 ) ref") or None,
                             err_upper=_to_float(r["GM (km 3 /s 2 ) sigma"]), err_lower=_to_float(r["GM (km 3 /s 2 ) sigma"])),
            "mean_radius_km": sv(_to_float(r["Mean Radius (km) value"]), ref=r.get("Mean Radius (km) ref") or None,
                                  err_upper=_to_float(r["Mean Radius (km) sigma"]), err_lower=_to_float(r["Mean Radius (km) sigma"])),
            "mean_density_g_cm3": sv(_to_float(r["Mean Density (g/cm 3 ) value"]), ref=r.get("Mean Density (g/cm 3 ) ref") or None,
                                      err_upper=_to_float(r["Mean Density (g/cm 3 ) sigma"]), err_lower=_to_float(r["Mean Density (g/cm 3 ) sigma"])),
        }
    return out


def _load_elem(raw_root: Path) -> list[dict]:
    d = latest_raw_dir(raw_root, "jpl_sat_elem")
    if d is None:
        return []
    html = (d / "elem.html").read_text()
    return parse_table_by_selector(html, {"id": "sat_elem"})


def _load_discovery(raw_root: Path) -> dict[tuple[str, str], dict]:
    d = latest_raw_dir(raw_root, "jpl_sat_discovery")
    if d is None:
        return {}
    html = (d / "discovery.html").read_text()
    records = parse_table_by_selector(html, {"class_": "sat-discovery"})
    out = {}
    current_planet = None
    header_re = re.compile(r"Satellites of (\w+)")
    for r in records:
        if "col_0" in r:
            m = header_re.search(r["col_0"])
            if m:
                current_planet = m.group(1)
            continue
        if current_planet is None or "IAU name" not in r or not r["IAU name"]:
            continue
        out[(current_planet, r["IAU name"])] = {
            "year_discovered": r.get("year discovered") or None,
            "discoverer": r.get("discoverer(s)/spacecraft mission") or None,
            "provisional_designation": r.get("provisional designation") or None,
        }
    return out


def _body_json(name: str, horizons_fields: dict) -> dict:
    mass_kg = None
    if horizons_fields.get("mass_1e24_kg") is not None:
        mass_kg = horizons_fields["mass_1e24_kg"] * 1e24
    return {
        "display_name": name,
        "mass_kg": sv(mass_kg, ref="jpl_horizons OBJ_DATA"),
        "mass_1e24_kg": sv(horizons_fields.get("mass_1e24_kg"), ref="jpl_horizons OBJ_DATA"),
        "vol_mean_radius_km": sv(horizons_fields.get("vol_mean_radius_km"), ref="jpl_horizons OBJ_DATA"),
        "equatorial_radius_km": sv(horizons_fields.get("equatorial_radius_km"), ref="jpl_horizons OBJ_DATA"),
        "density_g_cm3": sv(horizons_fields.get("density_g_cm3"), ref="jpl_horizons OBJ_DATA"),
        "gm_km3_s2": sv(horizons_fields.get("gm_km3_s2"), ref="jpl_horizons OBJ_DATA"),
        "sidereal_rotation_hr": sv(horizons_fields.get("sidereal_rotation_hr"), ref="jpl_horizons OBJ_DATA"),
        "mean_solar_day_s": sv(horizons_fields.get("mean_solar_day_s"), ref="jpl_horizons OBJ_DATA"),
        "surface_gravity_m_s2": sv(horizons_fields.get("surface_gravity_m_s2"), ref="jpl_horizons OBJ_DATA"),
        "escape_velocity_km_s": sv(horizons_fields.get("escape_velocity_km_s"), ref="jpl_horizons OBJ_DATA"),
        "sidereal_orbit_period_days": sv(horizons_fields.get("sidereal_orbit_period_days"), ref="jpl_horizons OBJ_DATA"),
        "data_source": "jpl_horizons",
    }


def _moon_json(planet: str, sat_name: str, phys: dict, elem_rows: list[dict], discovery: dict) -> dict:
    elem = elem_rows[0] if elem_rows else {}
    disco = discovery.get((planet, sat_name), {})
    p = phys.get((planet, sat_name), {})
    gm = p.get("gm_km3_s2", {}).get("value") if p else None
    mass_kg = (gm * 1e9 / G_NEWTON) if gm else None  # GM in km^3/s^2 -> m^3/s^2 (*1e9)
    return {
        "display_name": sat_name,
        "planet": planet,
        "naif_id": elem.get("Code") or None,
        "discoverer": disco.get("discoverer"),
        "year_discovered": disco.get("year_discovered"),
        "provisional_designation": disco.get("provisional_designation"),
        "gm_km3_s2": p.get("gm_km3_s2", sv(None)),
        "mean_radius_km": p.get("mean_radius_km", sv(None)),
        "mean_density_g_cm3": p.get("mean_density_g_cm3", sv(None)),
        "mass_kg": sv(mass_kg, ref="derived from GM via G=6.6743e-11 (CODATA)" if mass_kg else None),
        "semi_major_axis_km": sv(_to_float(elem.get("a (km)", "")), ref=elem.get("Ephemeris") or None),
        "eccentricity": sv(_to_float(elem.get("e", ""))),
        "inclination_deg": sv(_to_float(elem.get("i (deg)", ""))),
        "orbital_period_days": sv(_to_float(elem.get("P (days)", ""))),
        "epoch_iso": elem.get("Epoch (TDB)") or None,
        "data_source": "jpl_sat_phys_par + jpl_sat_elem + jpl_sat_discovery",
    }


def build(raw_root: Path, out_root: Path) -> BuildReport:
    report = BuildReport(category="solar_system")

    phys_par = _load_phys_par(raw_root)
    elem = _load_elem(raw_root)
    discovery = _load_discovery(raw_root)

    elem_by_body: dict[tuple[str, str], list[dict]] = {}
    for r in elem:
        elem_by_body.setdefault((r["Planet"], r["Satellite"]), []).append(r)

    # Sun
    sun_fields = _load_horizons(raw_root, "sun")
    sun_dir = out_root / "sun"
    write_json(sun_dir / "star.json", _body_json("Sun", sun_fields))
    write_metadata(sun_dir / "metadata.json", source="jpl_horizons", source_url="https://ssd.jpl.nasa.gov/api/horizons.api")
    write_text(sun_dir / "README.md", "# Sun\n\nParameter fisik dari JPL Horizons OBJ_DATA.\n")
    report.object_count += 1

    planets_dir = out_root / "planets"
    planet_slugs = []
    for order, name, slug_base in PLANETS:
        slug = planet_slug(order, name)
        planet_slugs.append(slug)
        p_dir = planets_dir / slug
        horizons_fields = _load_horizons(raw_root, slug_base)
        write_json(p_dir / "planet.json", _body_json(name, horizons_fields))
        write_metadata(p_dir / "metadata.json", source="jpl_horizons", source_url="https://ssd.jpl.nasa.gov/api/horizons.api")
        report.object_count += 1

        moons_of_planet = sorted({sat for (pl_, sat) in elem_by_body if pl_ == name})
        moon_rows = []
        for sat in moons_of_planet:
            m_slug = slugify(sat)
            m_dir = p_dir / "moons" / m_slug
            m_json = _moon_json(name, sat, phys_par, elem_by_body[(name, sat)], discovery)
            write_json(m_dir / "moon.json", m_json)
            elem_df = pl.DataFrame(elem_by_body[(name, sat)])
            elem_df.write_csv(m_dir / "orbital_elements.csv")
            write_metadata(
                m_dir / "metadata.json",
                source="jpl_sat_elem + jpl_sat_phys_par + jpl_sat_discovery",
                source_url="https://ssd.jpl.nasa.gov/sats/",
            )
            write_text(m_dir / "README.md", f"# {sat}\n\nBulan {name}. Data: JPL SSD Planetary Satellites.\n")
            moon_rows.append(m_json)
            report.object_count += 1

        if moon_rows:
            write_category_table(p_dir / "moons", pl.DataFrame(moon_rows), )
            write_category_index(p_dir / "moons", [slugify(s) for s in moons_of_planet], f"Bulan-bulan {name}.")
        write_text(p_dir / "README.md", f"# {name}\n\nPlanet ke-{order} dari Matahari. {len(moons_of_planet)} bulan terdaftar.\n")

    write_category_index(planets_dir, planet_slugs, "8 planet tata surya, prefix urutan dari Matahari.")

    # Pluto as the one dwarf planet whose moons are in the JPL satellite tables.
    dwarf_dir = out_root / "dwarf_planets" / "pluto"
    pluto_fields = _load_horizons(raw_root, "pluto")
    write_json(dwarf_dir / "dwarf_planet.json", _body_json("Pluto", pluto_fields))
    write_metadata(dwarf_dir / "metadata.json", source="jpl_horizons", source_url="https://ssd.jpl.nasa.gov/api/horizons.api")
    report.object_count += 1
    pluto_moons = sorted({sat for (pl_, sat) in elem_by_body if pl_ == "Pluto"})
    pluto_moon_rows = []
    for sat in pluto_moons:
        m_slug = slugify(sat)
        m_dir = dwarf_dir / "moons" / m_slug
        m_json = _moon_json("Pluto", sat, phys_par, elem_by_body[("Pluto", sat)], discovery)
        write_json(m_dir / "moon.json", m_json)
        pl.DataFrame(elem_by_body[("Pluto", sat)]).write_csv(m_dir / "orbital_elements.csv")
        write_metadata(m_dir / "metadata.json", source="jpl_sat_elem + jpl_sat_phys_par + jpl_sat_discovery", source_url="https://ssd.jpl.nasa.gov/sats/")
        write_text(m_dir / "README.md", f"# {sat}\n\nBulan Pluto. Data: JPL SSD Planetary Satellites.\n")
        pluto_moon_rows.append(m_json)
        report.object_count += 1
    if pluto_moon_rows:
        write_category_table(dwarf_dir / "moons", pl.DataFrame(pluto_moon_rows))
        write_category_index(dwarf_dir / "moons", [slugify(s) for s in pluto_moons], "Bulan-bulan Pluto.")
    write_text(dwarf_dir / "README.md", f"# Pluto\n\nPlanet katai. {len(pluto_moons)} bulan terdaftar (JPL SSD).\n")

    report.note(f"{len(elem_by_body)} kombinasi (planet, moon) unik dari jpl_sat_elem")
    return report
