"""Master registry of every data source this project can pull from.

This is the single source of truth mapping each source to:
  - a stable `key` (used as the folder name under data/raw/<key>/)
  - a `tier` (1/2/3, see README "Tiering")
  - a `probe_url` + `probe_method` used by Fase 1 to check the endpoint is alive
  - `license` / `notes`, filled in / corrected during probing

IMPORTANT: tiers below are our best-effort mapping of the task brief's
Tier 1/2/3 lists onto concrete endpoints. A few sources are not explicitly
named in the brief's tier lists (e.g. USGS Gazetteer, IAU star names,
OpenNGC); those are annotated with `notes` explaining the assumption. Tier
assignments get revisited in Fase 5's report before anything in Tier 2/3
actually runs.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceSpec:
    key: str
    name: str
    tier: int
    category: str
    base_url: str
    probe_url: str
    probe_method: str = "GET"
    probe_timeout: float = 20.0
    license: str | None = None
    notes: str = ""
    requires_credentials: bool = False


SOURCES: dict[str, SourceSpec] = {}


def register(spec: SourceSpec) -> None:
    if spec.key in SOURCES:
        raise ValueError(f"Duplicate source key: {spec.key}")
    SOURCES[spec.key] = spec


# ---------------------------------------------------------------------------
# [A] Tata surya — planet & benda utama
# ---------------------------------------------------------------------------
register(SourceSpec(
    key="nssdc_planetary_factsheet",
    name="NASA NSSDC Planetary Fact Sheets",
    tier=1,
    category="solar_system/planets",
    base_url="https://nssdc.gsfc.nasa.gov/planetary/factsheet/",
    probe_url="https://nssdc.gsfc.nasa.gov/planetary/factsheet/",
    license="Public domain (NASA)",
    notes="DEAD despite HTTP 200 (verified 2026-08-20 in Fase 3, after Fase 1's probe wrongly "
    "marked it alive on status code alone): the whole /planetary/factsheet/ path — including "
    "per-planet pages like marsfact.html — 307-redirects to https://www.nasa.gov/nssdc/, a "
    "generic 'NSSDC status' landing page with none of the actual fact-sheet data. No live "
    "replacement URL found for the classic per-planet comparison table. Physical parameters "
    "for planets are pulled from jpl_horizons's OBJ_DATA instead (already source [A] in the "
    "brief), which covers the same ground (mass, radius, density, gravity, rotation, etc.) "
    "straight from JPL, and — added 2026-08-21 — from le_systeme_solaire, which returns the "
    "same comparison-table quantities for 554 bodies (planets, dwarf planets and moons) in "
    "one JSON response. Re-verified 2026-08-21: marsfact.html and planet_table_ratio.html "
    "both return the byte-identical 245 kB nasa.gov landing page, so the redirect is not "
    "path-specific and there is nothing left to salvage here. This source is excluded from "
    "the build; the raw 2026-08-20 response is kept as-is (it is the honest evidence of what "
    "the endpoint actually returns) but never parsed as fact-sheet content.",
))
register(SourceSpec(
    key="le_systeme_solaire",
    name="Le Systeme Solaire REST API (bulk physical parameters, all bodies)",
    tier=1,
    category="solar_system/planets",
    base_url="https://api.le-systeme-solaire.net/rest/bodies/",
    probe_url="https://api.le-systeme-solaire.net/rest/bodies/",
    license="Open data, attribution requested (api.le-systeme-solaire.net)",
    notes="Replacement for the dead nssdc_planetary_factsheet. One request returns "
    "554 bodies (8 planets, 4 dwarf planets, 479 moons, 55 asteroids, 7 comets, the "
    "Sun) with mass, volume, density, gravity, escape velocity, mean/equatorial/polar "
    "radius, flattening, sidereal orbit and rotation, axial tilt, mean temperature, "
    "orbital elements and discovery circumstances — i.e. the same ground the fact "
    "sheets covered, plus moons. Requires an `Authorization: Bearer <key>` header; "
    "a free key ships as the default in core/config.py "
    "(ASTRO_DL_SOLARSYSTEM_API_KEY overrides it). Verified 2026-08-21: 200, 497 kB.",
))
register(SourceSpec(
    key="jpl_horizons",
    name="JPL Horizons API (ephemeris & physical parameters)",
    tier=1,
    category="solar_system/planets",
    base_url="https://ssd.jpl.nasa.gov/api/horizons.api",
    probe_url="https://ssd.jpl.nasa.gov/api/horizons.api?format=json&COMMAND='399'&OBJ_DATA='YES'&MAKE_EPHEM='NO'",
    license="Public domain (NASA/JPL)",
    notes="Only physical parameters + minimal ephemeris pulled at Tier 1, not full trajectory grids.",
))
register(SourceSpec(
    key="usgs_gazetteer",
    name="IAU/USGS Gazetteer of Planetary Nomenclature",
    tier=1,
    category="solar_system/planets",
    base_url="https://planetarynames.wr.usgs.gov/",
    probe_url="https://planetarynames.wr.usgs.gov/SearchResults?Target=19_Earth",
    license="Public domain (USGS/IAU)",
    notes="Promoted to Tier 1 on 2026-08-21 after the size was actually measured: an "
    "empty POST to /SearchResults bulk-exports the whole gazetteer in a single HTML "
    "table — 16,353 approved features across all bodies (~43 MB), not the 'tens of "
    "thousands, unknown size' the Fase 1 note assumed. The per-body GIS shapefiles at "
    "/GIS_Downloads are only needed if feature geometry (not centre coordinates) is "
    "wanted.",
))

# ---------------------------------------------------------------------------
# [B] Satelit alami (bulan)
# ---------------------------------------------------------------------------
register(SourceSpec(
    key="jpl_sat_phys_par",
    name="JPL Planetary Satellite Physical Parameters",
    tier=1,
    category="solar_system/moons",
    base_url="https://ssd.jpl.nasa.gov/sats/phys_par/",
    probe_url="https://ssd.jpl.nasa.gov/sats/phys_par/",
    license="Public domain (NASA/JPL)",
))
register(SourceSpec(
    key="jpl_sat_elem",
    name="JPL Planetary Satellite Mean Elements",
    tier=1,
    category="solar_system/moons",
    base_url="https://ssd.jpl.nasa.gov/sats/elem/",
    probe_url="https://ssd.jpl.nasa.gov/sats/elem/",
    license="Public domain (NASA/JPL)",
))
register(SourceSpec(
    key="jpl_sat_discovery",
    name="JPL Satellite Discovery Circumstances",
    tier=1,
    category="solar_system/moons",
    base_url="https://ssd.jpl.nasa.gov/sats/discovery.html",
    probe_url="https://ssd.jpl.nasa.gov/sats/discovery.html",
    license="Public domain (NASA/JPL)",
))

# ---------------------------------------------------------------------------
# [C] Asteroid, komet, TNO
# ---------------------------------------------------------------------------
register(SourceSpec(
    key="sbdb_query_neo",
    name="JPL SBDB Query API — NEO classes (IEO/ATE/APO/AMO)",
    tier=1,
    category="solar_system/small_bodies",
    base_url="https://ssd-api.jpl.nasa.gov/sbdb_query.api",
    probe_url=(
        "https://ssd-api.jpl.nasa.gov/sbdb_query.api"
        "?fields=full_name,spkid,pdes,a,e,i,H&sb-class=APO&limit=5"
    ),
    license="Public domain (NASA/JPL)",
))
register(SourceSpec(
    key="sbdb_query_full",
    name="JPL SBDB Query API — all classes (MBA/IMB/OMB/MCA/TJN/CEN/TNO/AST/HTC/JFC/etc.)",
    tier=2,
    category="solar_system/small_bodies",
    base_url="https://ssd-api.jpl.nasa.gov/sbdb_query.api",
    probe_url=(
        "https://ssd-api.jpl.nasa.gov/sbdb_query.api"
        "?fields=full_name,spkid,pdes,a,e,i,H&sb-class=MBA&limit=5"
    ),
    license="Public domain (NASA/JPL)",
    notes="MBA alone is ~1.2M objects; brief marks 'SBDB full semua kelas' as Tier 2.",
))
register(SourceSpec(
    key="mpc_mpcorb",
    name="Minor Planet Center — MPCORB full orbit database",
    tier=2,
    category="solar_system/small_bodies",
    base_url="https://www.minorplanetcenter.net/iau/MPCORB/MPCORB.DAT.gz",
    probe_url="https://www.minorplanetcenter.net/iau/MPCORB/MPCORB.DAT.gz",
    probe_method="HEAD",
    license="See MPC data-use policy (CC-ish, attribution required — verify at probe time)",
    notes="~1.4M objects, explicitly Tier 2 in the brief.",
))
register(SourceSpec(
    key="mpc_comet_els",
    name="MPC Comet Elements",
    tier=2,
    category="solar_system/small_bodies",
    base_url="https://www.minorplanetcenter.net/iau/MPCORB/CometEls.txt",
    probe_url="https://www.minorplanetcenter.net/iau/MPCORB/CometEls.txt",
    probe_method="HEAD",
    license="See MPC data-use policy (verify at probe time)",
    notes="Not explicitly in the brief's Tier 1 comet/asteroid list (only NEO+Sentry+CAD "
    "are named); file itself is small (a few thousand rows) so may be promotable to "
    "Tier 1 once confirmed.",
))
register(SourceSpec(
    key="cneos_cad",
    name="CNEOS Close Approach Data API",
    tier=1,
    category="solar_system/small_bodies",
    base_url="https://ssd-api.jpl.nasa.gov/cad.api",
    probe_url="https://ssd-api.jpl.nasa.gov/cad.api?date-min=2024-01-01&date-max=2024-01-02",
    license="Public domain (NASA/JPL)",
))
register(SourceSpec(
    key="cneos_sentry",
    name="CNEOS Sentry (impact risk list)",
    tier=1,
    category="solar_system/small_bodies",
    base_url="https://ssd-api.jpl.nasa.gov/sentry.api",
    probe_url="https://ssd-api.jpl.nasa.gov/sentry.api",
    license="Public domain (NASA/JPL)",
))

# ---------------------------------------------------------------------------
# [D] Exoplanet
# ---------------------------------------------------------------------------
_EXOPLANET_ARCHIVE_TABLES = {
    "pscomppars": "One row per planet, best-available composite parameters (primary for folder structure).",
    "ps": "All publications per planet (historical).",
    "k2pandc": "K2 planets and candidates.",
    "toi": "TESS Objects of Interest.",
    "cumulative": "Kepler KOI cumulative table.",
    "stellarhosts": "Host-star parameters.",
}
for _table, _desc in _EXOPLANET_ARCHIVE_TABLES.items():
    register(SourceSpec(
        key=f"exoplanet_archive_{_table}",
        name=f"NASA Exoplanet Archive TAP — {_table}",
        tier=1,
        category="exoplanets",
        base_url="https://exoplanetarchive.ipac.caltech.edu/TAP/sync",
        probe_url=(
            "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
            f"?query=select+top+5+*+from+{_table}&format=csv"
        ),
        license="Public domain (NASA); attribution requested by IPAC",
        notes=_desc,
    ))
register(SourceSpec(
    key="open_exoplanet_catalogue",
    name="Open Exoplanet Catalogue (XML, cross-check)",
    tier=1,
    category="exoplanets",
    base_url="https://github.com/OpenExoplanetCatalogue/open_exoplanet_catalogue",
    probe_url="https://raw.githubusercontent.com/OpenExoplanetCatalogue/open_exoplanet_catalogue/master/README.md",
    license="MIT (per repo)",
    notes="The main repo has one XML per system (thousands of files) and its tarball "
    "endpoints (api.github.com / codeload.github.com) are blocked here — but the OEC "
    "project publishes the whole catalogue as a single gzipped XML in its companion "
    "repo, refreshed on every commit: raw.githubusercontent.com/OpenExoplanetCatalogue/"
    "oec_gzip/master/systems.xml.gz. Verified 2026-08-21: 200, 1.05 MB. That is what "
    "the downloader uses, so this source is no longer skipped.",
))
register(SourceSpec(
    key="exoplanet_eu",
    name="exoplanet.eu catalog (CSV)",
    tier=1,
    category="exoplanets",
    base_url="https://exoplanet.eu/catalog/csv/",
    probe_url="https://exoplanet.eu/catalog/csv/",
    probe_timeout=45.0,
    license="Verify at probe time (exoplanet.eu terms of use)",
    notes="http:// 301-redirects to https://; the endpoint is alive but slow to fully "
    "respond (~1.5MB+ received within 25s, still streaming) — needs a generous timeout "
    "for the real pull in Fase 2, not just the default HTTP client timeout.",
))

# ---------------------------------------------------------------------------
# [E] Bintang
# ---------------------------------------------------------------------------
register(SourceSpec(
    key="hyg_database",
    name="HYG Database (120k stars, common + Bayer/Flamsteed names)",
    tier=1,
    category="stars",
    base_url="https://github.com/astronexus/HYG-Database",
    probe_url="https://raw.githubusercontent.com/astronexus/HYG-Database/main/hyg/CURRENT/hygdata_v41.csv",
    probe_method="HEAD",
    license="CC BY-SA 4.0 (per repo)",
    notes="Starting point for the stars/ tree per the brief. Verified 2026-08-20: current "
    "file is hygdata_v41.csv (v4.1), not hyg_v42.csv as guessed initially — see CHANGELOG.",
))
register(SourceSpec(
    key="simbad_tap",
    name="SIMBAD TAP (identifiers, object types, cross-match)",
    tier=1,
    category="stars",
    base_url="https://simbad.cds.unistra.fr/simbad/sim-tap/sync",
    probe_url=(
        "https://simbad.cds.unistra.fr/simbad/sim-tap/sync"
        "?request=doQuery&lang=adql&format=csv"
        "&query=select+top+5+main_id,ra,dec+from+basic"
    ),
    license="CDS — attribution required",
    notes="Used for targeted cross-match queries, not a full dump. `basic` alone is >15M "
    "rows with unbounded scope, so it is never bulk-dumped. Fase 5 pulls seven bounded "
    "ADQL queries instead (verified live 2026-08-20): five object-type slices that feed "
    "stars/special/ (otypes BD*/N*/BH/sg*, plus MK luminosity class Ia+ for hypergiants) "
    "and four HIP<->{main_id,Gaia DR3,TIC,2MASS,HD} identifier joins over the `ident` "
    "table that feed _catalog/crosswalk.parquet. Each returns 10^2-10^5 rows and runs in "
    "seconds. Two facts confirmed on 2026-08-21 while wiring links.py: magnitudes live in "
    "`allfluxes`, not `basic`, so any magnitude cut needs the join (a bare `where V < 10` "
    "returns HTTP 400 'Unknown column V'); and SIMBAD's TAP silently truncates at "
    "MAXREC=50000 — a `V < 10` join matches 362,857 rows but returns exactly 50,000 with "
    "no warning, which is why every TAP target now sends MAXREC explicitly and the "
    "downloader refuses a result that comes back sitting exactly on the limit."
))
register(SourceSpec(
    key="gaia_dr3_tap",
    name="Gaia DR3 via ESA TAP (full source catalog)",
    tier=3,
    category="stars",
    base_url="https://gea.esac.esa.int/tap-server/tap",
    probe_url=(
        "https://gea.esac.esa.int/tap-server/tap/sync"
        "?REQUEST=doQuery&LANG=ADQL&FORMAT=csv"
        "&QUERY=select+top+5+source_id,ra,dec+from+gaiadr3.gaia_source"
    ),
    license="ESA/Gaia — attribution required",
    notes="1.81e9 rows. Default Tier 3 subset: parallax > 10 mas OR phot_g_mean_mag < 12 "
    "(see brief section 3) = 3,602,117 rows, counted live on 2026-08-21 rather than "
    "estimated. The Fase 1 HTTP 503 was a transient ESA-side outage; the server answers "
    "normally again. The subset is split into 182 `random_index` slices of 10M each. "
    "Slice width is a correctness constraint, not a speed knob: at 50M wide the sync "
    "endpoint repeatably returned 90,113 of a matching 99,309 rows with no warning "
    "anywhere — VOTable QUERY_STATUS still reads OK, because that INFO is written "
    "before rows stream, and an explicit MAXREC does not change the number. At 5M and "
    "10M the returned row count equals the catalogue count exactly (spot-checked at "
    "slices 0, 90 and 181). Never pulled without an explicit --tier 3 instruction.",
))
register(SourceSpec(
    key="vizier_tap",
    name="VizieR TAP (access to thousands of catalogs)",
    tier=1,
    category="stars",
    base_url="https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync",
    probe_url=(
        "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"
        "?request=doQuery&lang=adql&format=csv"
        "&query=select+top+5+*+from+\"B/wds/wds\""
    ),
    license="CDS — attribution required per catalog",
    notes="Used per-catalog (WDS, SB9, MSC), not a bulk dump. Its own downloadable "
    "artifact is METAcat — VizieR's index of every catalogue it serves — via the ASU "
    "endpoint. Note TAP_SCHEMA queries against TAPVizieR return HTTP 500 (server-side "
    "SQL translation bug, re-checked 2026-08-21), so METAcat is the working way to "
    "enumerate catalogues.",
))
register(SourceSpec(
    key="iau_star_names",
    name="IAU Catalog of Star Names (IAU-CSN)",
    tier=1,
    category="stars",
    base_url="https://www.pas.rochester.edu/~emamajek/WGSN/IAU-CSN.txt",
    probe_url="https://www.pas.rochester.edu/~emamajek/WGSN/IAU-CSN.txt",
    license="CC BY (IAU-produced products); cite per file header",
    notes="The brief's iau.org/public/themes/naming_stars/ page 404s (verified 2026-08-20 — "
    "see CHANGELOG). Replaced with the machine-readable IAU-CSN maintained by the IAU "
    "Division C Working Group on Star Names (WGSN) itself, which the iau.org page even "
    "points to as the canonical data file.",
))

# ---------------------------------------------------------------------------
# [F] Sistem biner & multiple
# ---------------------------------------------------------------------------
register(SourceSpec(
    key="wds_catalog",
    name="Washington Double Star Catalog (via VizieR B/wds)",
    tier=1,
    category="multiple_systems",
    base_url="https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync",
    probe_url=(
        "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"
        "?request=doQuery&lang=adql&format=csv"
        "&query=select+top+5+*+from+\"B/wds/wds\""
    ),
    license="CDS — attribution required",
))
register(SourceSpec(
    key="sb9_catalog",
    name="SB9: Spectroscopic Binary Orbits",
    tier=1,
    category="multiple_systems",
    base_url="https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync",
    probe_url=(
        "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"
        "?request=doQuery&lang=adql&format=csv&query=select+top+5+*+from+\"B/sb9/main\""
    ),
    license="CDS — attribution required",
    notes="ULB's own mainform.cgi is a search-only CGI form with no obvious bulk-export "
    "URL (verified 2026-08-20). SB9 is mirrored on VizieR as B/sb9/{main,orbits,alias} — "
    "used instead for the actual pull.",
))
register(SourceSpec(
    key="kepler_eb_catalog",
    name="Kepler Eclipsing Binary Catalog",
    tier=1,
    category="multiple_systems",
    base_url="https://keplerebs.villanova.edu/?format=csv",
    probe_url="https://keplerebs.villanova.edu/",
    license="Verify at probe time (Villanova KEBC terms)",
    notes="Plain http:// 400s on this server (verified 2026-08-20 — see CHANGELOG); use "
    "https://. Full bulk export found: https://keplerebs.villanova.edu/?format=csv "
    "returns the whole catalog (2920 systems) as one flat CSV — no pagination needed.",
))
register(SourceSpec(
    key="msc_catalog",
    name="Multiple Star Catalog (MSC, VizieR J/ApJS/235/6)",
    tier=1,
    category="multiple_systems",
    base_url="https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync",
    probe_url=(
        "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"
        "?request=doQuery&lang=adql&format=csv"
        "&query=select+top+5+*+from+\"J/ApJS/235/6/catalog\""
    ),
    license="CDS — attribution required",
    notes="Table is J/ApJS/235/6/catalog (there is no 'table1' — verified via TAP_SCHEMA "
    "2026-08-20, see CHANGELOG). Other tables in this catalog: notes, orbits, systems.",
))
register(SourceSpec(
    key="gaia_dr3_nss",
    name="Gaia DR3 Non-Single Stars (gaiadr3.nss_two_body_orbit)",
    tier=2,
    category="multiple_systems",
    base_url="https://gea.esac.esa.int/tap-server/tap",
    probe_url=(
        "https://gea.esac.esa.int/tap-server/tap/sync"
        "?REQUEST=doQuery&LANG=ADQL&FORMAT=csv"
        "&QUERY=select+top+5+*+from+gaiadr3.nss_two_body_orbit"
    ),
    license="ESA/Gaia — attribution required",
    notes="~800k rows; smaller than the full Gaia source catalog but still large, so "
    "Tier 2. The Fase 1 HTTP 503 was a transient ESA-side outage — re-probed 2026-08-21 "
    "and the table answers normally.",
))

# ---------------------------------------------------------------------------
# [G] Satelit buatan (artificial)
# ---------------------------------------------------------------------------
_CELESTRAK_GROUPS = [
    "active", "stations", "starlink", "gps-ops", "galileo", "weather",
    "science", "geo", "cubesat", "military", "last-30-days",
]
for _group in _CELESTRAK_GROUPS:
    register(SourceSpec(
        key=f"celestrak_gp_{_group.replace('-', '_')}",
        name=f"CelesTrak GP data — group={_group}",
        tier=1,
        category="solar_system/artificial_satellites",
        base_url="https://celestrak.org/NORAD/elements/gp.php",
        probe_url=f"https://celestrak.org/NORAD/elements/gp.php?GROUP={_group}&FORMAT=json",
        license="CelesTrak — attribution requested",
    ))
register(SourceSpec(
    key="celestrak_satcat",
    name="CelesTrak SATCAT (full catalog incl. decayed objects)",
    tier=2,
    category="solar_system/artificial_satellites",
    base_url="https://celestrak.org/pub/satcat.csv",
    probe_url="https://celestrak.org/pub/satcat.csv",
    probe_method="HEAD",
    license="CelesTrak — attribution requested",
))
register(SourceSpec(
    key="spacetrack",
    name="Space-Track.org",
    tier=1,
    category="solar_system/artificial_satellites",
    base_url="https://www.space-track.org/",
    probe_url="https://www.space-track.org/ajaxauth/login",
    requires_credentials=True,
    notes="Requires a free account. SKIP if ASTRO_DL_SPACETRACK_USER/PASS are not set; "
    "record the skip in CHANGELOG.md.",
))
register(SourceSpec(
    key="ucs_satellite_db",
    name="UCS Satellite Database",
    tier=1,
    category="solar_system/artificial_satellites",
    base_url="https://www.ucs.org/resources/satellite-database",
    probe_url="https://www.ucs.org/media/11492",
    license="Verify at probe time (UCS terms of use)",
    notes="ucsusa.org redirects to ucs.org. The landing page only offers an email opt-in "
    "form, which is why Fase 1 marked this credentialed — but that was wrong: the "
    "underlying media link https://www.ucs.org/media/11492 is public and "
    "unauthenticated, redirecting to the current dated .xlsx under /sites/default/files/. "
    "Verified 2026-08-21: 200, 1.5 MB, spreadsheetml content type. No opt-in needed, so "
    "requires_credentials is now False and the source is pulled normally.",
))

# ---------------------------------------------------------------------------
# [H] Deep sky (opsional, tier 3 per brief header)
# ---------------------------------------------------------------------------
register(SourceSpec(
    key="openngc",
    name="OpenNGC (NGC/IC objects)",
    tier=3,
    category="deep_sky",
    base_url="https://github.com/mattiaverga/OpenNGC",
    probe_url="https://raw.githubusercontent.com/mattiaverga/OpenNGC/master/database_files/NGC.csv",
    probe_method="HEAD",
    license="CC BY-SA 4.0 (per repo)",
    notes="Brief files this whole section under '(opsional, tier 3)', though NGC+IC is "
    "only ~13000 rows — small enough to reconsider as Tier 1 on confirmation.",
))
register(SourceSpec(
    key="messier_catalog",
    name="Messier catalog",
    tier=3,
    category="deep_sky",
    base_url="https://github.com/mattiaverga/OpenNGC",
    probe_url="https://raw.githubusercontent.com/mattiaverga/OpenNGC/master/database_files/NGC.csv",
    license="CC BY-SA 4.0 (per repo)",
    notes="Messier objects are a subset of OpenNGC (M column); same Tier-3-by-brief caveat as above.",
))


# ---------------------------------------------------------------------------
# [I] Fase 5 — sumber tambahan untuk menutup gap yang tercatat di REPORT.md §5
# ---------------------------------------------------------------------------
register(SourceSpec(
    key="atnf_pulsar_catalog",
    name="ATNF Pulsar Catalogue (via VizieR B/psr)",
    tier=1,
    category="stars/special",
    base_url="https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync",
    probe_url=(
        "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"
        "?request=doQuery&lang=adql&format=csv"
        "&query=select+top+5+*+from+\"B/psr/psr\""
    ),
    license="CDS — attribution required (Manchester et al. 2005, AJ 129, 1993)",
    notes="Fills stars/special/{pulsars,magnetars}, which HYG alone could not support "
    "(see REPORT.md §5). The catalogue's own `Type` column carries AXP for the "
    "anomalous X-ray pulsars / magnetars — that is the flag used, not a guess. "
    "CAVEAT: VizieR's copy is a frozen snapshot of 2536 pulsars (confirmed by "
    "`select count(*)` on 2026-08-20 — it is the whole table, not a truncated query), "
    "while the live ATNF catalogue at atnf.csiro.au is past 3500. Pulled from VizieR "
    "anyway because it is the only bulk endpoint with stable ADQL access; the live "
    "catalogue's own interface is an HTML form. Re-check the row count when a newer "
    "VizieR version lands.",
))
register(SourceSpec(
    key="blackcat_bh_transients",
    name="BlackCAT: stellar-mass black holes in X-ray transients (VizieR J/A+A/587/A61)",
    tier=1,
    category="stars/special",
    base_url="https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync",
    probe_url=(
        "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"
        "?request=doQuery&lang=adql&format=csv"
        "&query=select+top+5+*+from+\"J/A%2BA/587/A61/tablea1\""
    ),
    license="CDS — attribution required (Corral-Santana et al. 2016, A&A 587, A61)",
    notes="Table name is J/A+A/587/A61/tablea1 (verified 2026-08-20; there is no "
    "'blackcat' table). Feeds stars/special/black_holes/ alongside the SIMBAD otype=BH "
    "slice: SIMBAD lists only the handful of objects typed BH outright, BlackCAT lists "
    "the X-ray transient census with orbital data.",
))
register(SourceSpec(
    key="iau_meteor_data_center",
    name="IAU Meteor Data Center — shower list",
    tier=1,
    category="solar_system/small_bodies/meteor_showers",
    base_url="https://www.ta3.sk/IAUC22DB/MDC2022/",
    probe_url="https://www.ta3.sk/IAUC22DB/MDC2022/Etc/streamestablisheddata2026.txt",
    license="IAU MDC — cite Jopek & Jenniskens; see file header",
    notes="The official IAU shower nomenclature database. Fixed-width-ish pipe-delimited "
    "text with a 98-line self-describing header. Two files pulled: the established-shower "
    "list (IAU-accepted showers) and the full list (established + working list). Filenames "
    "carry the year of the edition (…2026.txt, verified 2026-08-20 from the MDC download "
    "links) — re-check the link list when the edition rolls over.",
))
register(SourceSpec(
    key="jpl_horizons_elements",
    name="JPL Horizons — heliocentric osculating elements of the giant planets",
    tier=1,
    category="solar_system/planets",
    base_url="https://ssd.jpl.nasa.gov/api/horizons.api",
    probe_url=(
        "https://ssd.jpl.nasa.gov/api/horizons.api?format=text&COMMAND='5'&OBJ_DATA='NO'"
        "&MAKE_EPHEM='YES'&EPHEM_TYPE='ELEMENTS'&CENTER='500@10'&TLIST=2461200.5"
    ),
    license="Public domain (NASA/JPL)",
    notes="Jupiter's and Neptune's elements at JD 2461200.5 — the epoch most SBDB orbit "
    "solutions use. Two derived splits need them and nothing else does: the Jupiter-trojan "
    "L4/L5 camp (Jupiter's mean longitude at the asteroid's epoch) and the location of "
    "Neptune's mean-motion resonances (from Neptune's semi-major axis) for the TNO "
    "sub-classes. Separate from the `jpl_horizons` key so the OBJ_DATA physical-parameter "
    "pull keeps its own raw folder.",
))
register(SourceSpec(
    key="sbdb_query_hyperbolic",
    name="JPL SBDB — hyperbolic and parabolic orbits (interstellar candidates)",
    tier=1,
    category="solar_system/small_bodies/comets",
    base_url="https://ssd-api.jpl.nasa.gov/sbdb_query.api",
    probe_url="https://ssd-api.jpl.nasa.gov/sbdb_query.api?fields=full_name,e,class&sb-class=HYP&limit=5",
    license="Public domain (NASA/JPL)",
    notes="SBDB orbit classes HYP (hyperbolic comet), PAR (parabolic comet) and HYA "
    "(hyperbolic asteroid), all skipped by the Fase 2 pull — they are what "
    "comets/interstellar/ needs. Two things learned while wiring this up (2026-08-20): "
    "(1) a hyperbolic osculating orbit does NOT make an object interstellar — Oort-cloud "
    "comets are routinely perturbed past e=1, and 515 of the 520 HYP comets sit below "
    "e=1.01; (2) SBDB does not use the IAU 'I' designations in `full_name` at all — "
    "1I/'Oumuamua is filed as \"'Oumuamua (A/2017 U1)\" under class HYA, 2I/Borisov as "
    "\"C/2019 Q4 (Borisov)\" and 3I/ATLAS as \"C/2025 N1 (ATLAS)\", both HYP. The builder "
    "therefore matches on primary designation against an explicit three-entry table of "
    "IAU interstellar designations, and keeps the merely-hyperbolic objects in a separate "
    "file instead of mislabelling them.",
))


def sources_by_tier(tier: int) -> list[SourceSpec]:
    return [s for s in SOURCES.values() if s.tier == tier]


def sources_by_category(category: str) -> list[SourceSpec]:
    return [s for s in SOURCES.values() if s.category == category]
