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
    "straight from JPL. This source is excluded from the build; the raw 2026-08-20 response "
    "is kept as-is (it's the honest evidence of what the endpoint actually returns) but never "
    "parsed as fact-sheet content.",
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
    tier=2,
    category="solar_system/planets",
    base_url="https://planetarynames.wr.usgs.gov/",
    probe_url="https://planetarynames.wr.usgs.gov/SearchResults?Target=19_Earth",
    license="Public domain (USGS/IAU)",
    notes="Not explicitly listed in the brief's Tier 1 list; nomenclature covers tens of "
    "thousands of surface features, so provisionally Tier 2 pending size confirmation.",
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
    notes="No single combined data file — one XML per system (thousands of files) under "
    "systems/. api.github.com and codeload.github.com are blocked for this session (repo "
    "not in this session's GitHub scope), so directory listing / tarball download aren't "
    "reachable here; per-file raw.githubusercontent.com fetches would mean thousands of "
    "requests at the 1 req/s policy. Skipped in this pull; a proper pull needs either a "
    "`git clone` step outside this session's GitHub-scope restriction, or the repo added "
    "to session scope via add_repo.",
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
    "rows with unbounded scope, so it's not pulled in Fase 2; Fase 3's crosswalk build "
    "queries it per-object (by HYG/exoplanet-host name or coordinates) instead.",
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
    notes="1.8B rows. Default Tier 3 subset: parallax > 10 mas OR phot_g_mean_mag < 12 "
    "(see brief section 3). Never pulled without explicit go-ahead. Probe on 2026-08-20 "
    "got HTTP 503 from the ESA TAP server (likely maintenance/load, not a dead endpoint) "
    "— re-check before any Tier 3 pull.",
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
    notes="Used per-catalog (WDS, MSC, etc.), not a bulk dump.",
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
    notes="~800k rows; smaller than the full Gaia source catalog but still large, "
    "provisionally Tier 2 pending size confirmation. Probe on 2026-08-20 got HTTP 503 "
    "from the ESA TAP server (same as gaia_dr3_tap) — re-check before pulling.",
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
    probe_url="https://www.ucs.org/resources/satellite-database",
    license="Verify at probe time (UCS terms of use)",
    requires_credentials=True,
    notes="ucsusa.org redirects to ucs.org (verified 2026-08-20). The page no longer links "
    "a direct .xlsx/.csv download — it now routes to an email opt-in form "
    "(forms.ucs.org/get-satellite-database-updates/). Treated like a credentialed source "
    "and skipped rather than scraping a page that isn't the actual dataset; a human would "
    "need to request the file directly from UCS.",
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
# [I] Model 3D & tekstur (Fase 8)
#
# Kategori "models_3d/*". Berbeda dari sumber lain di file ini, isinya file
# biner (mesh + tekstur), bukan tabel — jadi ditarik lewat stream fetcher di
# astro_datalake/models3d/ (tulis langsung ke disk), bukan DOWNLOAD_PLAN.
# ---------------------------------------------------------------------------
register(SourceSpec(
    key="nasa_3d_resources",
    name="NASA 3D Resources (model, tekstur, model cetak 3D)",
    tier=2,
    category="models_3d/nasa",
    base_url="https://github.com/nasa/NASA-3D-Resources",
    probe_url="https://raw.githubusercontent.com/nasa/NASA-3D-Resources/master/meta.json",
    license="Public domain / NASA Open Source Agreement v1.3 (lihat meta.json + usage guidelines repo)",
    notes="Situs lama nasa3d.arc.nasa.gov sudah mati — 301 ke science.nasa.gov/3d-resources/ "
    "(diverifikasi 2026-08-21), dan halaman itu sendiri menunjuk balik ke repo GitHub ini "
    "sebagai sumber file. Jadi repo-nya yang ditarik (git clone --depth 1), bukan situsnya. "
    "~4,6 GB, 1199 file, 3 direktori: '3D Models' (227 objek: Hubble, JWST, Cassini, Voyager, "
    "Juno, Kepler, Chandra, Rosetta, ISS, rover, dst.), '3D Printing' (108 objek: STL siap "
    "cetak, termasuk komet/asteroid), 'Images and Textures' (50 set: tekstur planet, bulan, "
    "dan peta bintang Tycho/Hipparcos/Yale). Tier 2 karena ukurannya.",
))
register(SourceSpec(
    key="nasa_science_3d",
    name="NASA Science 3D Resources (halaman per-model + aset STL/GLB)",
    tier=1,
    category="models_3d/nasa",
    base_url="https://science.nasa.gov/3d-resources/",
    probe_url="https://science.nasa.gov/wp-json/smd/v1/content-list?science_org=6504&number_of_items=1&current_page=1&post_types=any&response_format=json",
    license="Public domain (NASA), lihat NASA media usage guidelines",
    notes="Katalog resmi pengganti nasa3d.arc.nasa.gov. Daftar item diambil dari REST WordPress "
    "science.nasa.gov (smd/v1/content-list, science_org=6504) — endpoint HTML-nya mengabaikan "
    "current_page/number_of_items sehingga tidak bisa dipaginasi, endpoint JSON-nya bisa. "
    "Tiap halaman detail memuat file di assets.science.nasa.gov (STL per-bagian untuk model "
    "cetak, PNG pratinjau) yang TIDAK selalu ada di repo GitHub, jadi sumber ini bukan duplikat "
    "nasa_3d_resources. Deskripsi per-model dari sini dipakai sebagai metadata di data/models_3d/.",
))
register(SourceSpec(
    key="pds_sbn_shape_models",
    name="PDS Small Bodies Node — shape model komet, asteroid, satelit",
    tier=1,
    category="models_3d/small_bodies",
    base_url="https://sbn.psi.edu/pds/shape-models/",
    probe_url="https://sbn.psi.edu/pds/shape-models/js/app.Data.js",
    license="Public domain (NASA PDS); tiap dataset punya referensi/atribusi sendiri di dataset.html-nya",
    notes="Katalog shape model-nya ada di app.Data.js (halaman itu sendiri di-render JS, jadi "
    "HTML-nya kosong). 63 objek: 5 komet (67P/Churyumov-Gerasimenko, 81P/Wild 2, 103P/Hartley 2, "
    "9P/Tempel 1, 1P/Halley), 36 asteroid (Bennu, Ryugu, Itokawa, Eros, Vesta, Ceres, Apophis, "
    "Arrokoth, dst.), 22 satelit alami. Format: OBJ turunan + file primer PDS (WRL/TAB/BDS) + "
    "pratinjau PNG + USDZ untuk sebagian.",
))
register(SourceSpec(
    key="damit_shape_models",
    name="DAMIT — Database of Asteroid Models from Inversion Techniques",
    tier=2,
    category="models_3d/small_bodies",
    base_url="https://damit.cuni.cz/projects/damit/",
    probe_url="https://damit.cuni.cz/projects/damit/exports",
    license="CC BY 4.0 (atribusi ke DAMIT / Durech et al. wajib)",
    notes="Export lengkap satu file tar.gz (~1,32 GB) berisi ribuan model bentuk asteroid hasil "
    "inversi kurva cahaya, plus tabel CSV-nya. URL 'latest' stabil: "
    "/projects/damit/exports/complete/latest. Tier 2 karena ukurannya.",
))
register(SourceSpec(
    key="nasa_svs_texture_kits",
    name="NASA Scientific Visualization Studio — CGI texture kit",
    tier=2,
    category="models_3d/textures",
    base_url="https://svs.gsfc.nasa.gov/",
    probe_url="https://svs.gsfc.nasa.gov/api/4720/",
    license="Public domain (NASA/GSFC SVS), atribusi diminta",
    notes="Yang ditarik: CGI Moon Kit (halaman 4720) — peta warna LROC + displacement LOLA "
    "beresolusi tinggi untuk merender Bulan. Halaman SVS lain tidak bisa dicari otomatis: "
    "endpoint /api/search/ mengabaikan parameter q (selalu mengembalikan seluruh 10.554 item, "
    "diverifikasi 2026-08-21), jadi ID halaman disebut eksplisit, bukan hasil pencarian. "
    "File di atas MAX_TEXTURE_BYTES (lihat models3d/plan.py) dilewati dan dicatat.",
))
register(SourceSpec(
    key="nasa_blue_marble_textures",
    name="NASA Earth Observatory — koleksi Blue Marble",
    tier=1,
    category="models_3d/textures",
    base_url="https://science.nasa.gov/earth/earth-observatory/collections/blue-marble/",
    probe_url="https://science.nasa.gov/earth/earth-observatory/collections/blue-marble/",
    license="Public domain (NASA Earth Observatory), atribusi diminta",
    notes="visibleearth.nasa.gov/collection/1484 sekarang 301 ke halaman koleksi di "
    "science.nasa.gov (diverifikasi 2026-08-21). Halaman koleksinya sendiri cuma indeks — "
    "file gambarnya ada di halaman-halaman fitur yang ditautkannya, dilayani dari "
    "assets.science.nasa.gov (path eoimages.gsfc.nasa.gov yang lama sudah tidak ditaut, dan "
    "direktorinya tidak bisa di-listing). Halaman fitur yang di-crawl disebut eksplisit di "
    "models3d/plan.py, dibatasi ke aset ber-path 'bluemarble' supaya tidak menyeret gambar "
    "artikel Earth Observatory lain.",
))
register(SourceSpec(
    key="usgs_planetary_mosaics",
    name="USGS Astrogeology Astropedia — mosaik global planet/bulan",
    tier=3,
    category="models_3d/textures",
    base_url="https://astrogeology.usgs.gov/search",
    probe_url="https://astrogeology.usgs.gov/search/results?q=global+mosaic",
    license="Public domain (USGS/NASA), atribusi per-produk",
    notes="TIDAK ditarik. /search/results memang mengembalikan JSON (1643 entri), tapi tiap "
    "entri hanya memberi slug + halaman HTML yang di-render JS; link file sebenarnya ada di "
    "resource CKAN per-dataset, dan satu mosaik global bisa puluhan sampai ratusan GB "
    "(GeoTIFF, resolusi meter). Perlu downloader khusus + pilihan resolusi, dan tetap di luar "
    "kuota disk sesi ini — sama alasannya dengan usgs_gazetteer.",
))
register(SourceSpec(
    key="solarsystemscope_textures",
    name="Solar System Scope — tekstur planet & Matahari (CC BY 4.0)",
    tier=1,
    category="models_3d/textures",
    base_url="https://www.solarsystemscope.com/textures/",
    probe_url="https://www.solarsystemscope.com/textures/",
    license="CC BY 4.0 (per halaman sumber)",
    notes="TIDAK bisa ditarik: seluruh domain di balik captcha bot-gate. Halaman /textures/ dan "
    "URL unduhan langsung sama-sama membalas HTTP 202 berisi redirect ke "
    "/.well-known/sgcaptcha/ (diverifikasi 2026-08-21, dengan dan tanpa User-Agent browser). "
    "Menembus captcha bukan cara yang benar untuk mengambil data; tekstur planet/bintang "
    "yang setara diambil dari nasa_3d_resources ('Images and Textures') dan nasa_svs_texture_kits.",
))


def sources_by_tier(tier: int) -> list[SourceSpec]:
    return [s for s in SOURCES.values() if s.tier == tier]


def sources_by_category(category: str) -> list[SourceSpec]:
    return [s for s in SOURCES.values() if s.category == category]
