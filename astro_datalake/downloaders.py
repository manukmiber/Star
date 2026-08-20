"""Fase 2: real per-source downloaders.

Each entry in DOWNLOAD_PLAN maps a registry source `key` to an async
"fetcher" that returns a list of (filename, raw_bytes) pairs to be cached
under data/raw/<key>/ (see core.cache). A source with no plan here is
either deliberately deferred (see notes in sources/registry.py — e.g.
sources needing credentials, or ones where no clean bulk-download endpoint
exists) or is a Tier 2/3 source not pulled yet.

Query shapes (TAP "select * from X", SBDB fields, Horizons params) were
worked out interactively against the live APIs during Fase 1/2, not
guessed — see CHANGELOG.md.
"""

from __future__ import annotations

from typing import Awaitable, Callable

import httpx

from .core.http import get

Fetcher = Callable[[httpx.AsyncClient], Awaitable[list[tuple[str, bytes]]]]

EXOPLANET_ARCHIVE_TAP = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
VIZIER_TAP = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"
SBDB_QUERY = "https://ssd-api.jpl.nasa.gov/sbdb_query.api"
HORIZONS_API = "https://ssd.jpl.nasa.gov/api/horizons.api"
CNEOS_CAD = "https://ssd-api.jpl.nasa.gov/cad.api"
CNEOS_SENTRY = "https://ssd-api.jpl.nasa.gov/sentry.api"


def static_file(url: str, filename: str, timeout: float = 90.0) -> Fetcher:
    async def fetch(client: httpx.AsyncClient) -> list[tuple[str, bytes]]:
        response = await get(client, url, timeout=timeout)
        return [(filename, response.content)]

    return fetch


def tap_full_table(base_url: str, table: str, filename: str = "data.csv", timeout: float = 180.0) -> Fetcher:
    async def fetch(client: httpx.AsyncClient) -> list[tuple[str, bytes]]:
        response = await get(
            client, base_url, params={"query": f"select * from {table}", "format": "csv"}, timeout=timeout
        )
        return [(filename, response.content)]

    return fetch


def vizier_table(table: str, filename: str, timeout: float = 180.0) -> Fetcher:
    async def fetch(client: httpx.AsyncClient) -> list[tuple[str, bytes]]:
        response = await get(
            client,
            VIZIER_TAP,
            params={
                "request": "doQuery",
                "lang": "adql",
                "format": "csv",
                "query": f'select * from "{table}"',
            },
            timeout=timeout,
        )
        return [(filename, response.content)]

    return fetch


def multi_vizier_tables(tables: dict[str, str], timeout: float = 180.0) -> Fetcher:
    """tables: {filename: table_name}, fetched sequentially (still rate-limited)."""

    async def fetch(client: httpx.AsyncClient) -> list[tuple[str, bytes]]:
        results = []
        for filename, table in tables.items():
            single = vizier_table(table, filename, timeout=timeout)
            results.extend(await single(client))
        return results

    return fetch


def sbdb_classes(classes: list[str], fields: str, timeout: float = 120.0) -> Fetcher:
    async def fetch(client: httpx.AsyncClient) -> list[tuple[str, bytes]]:
        results = []
        for sb_class in classes:
            response = await get(
                client, SBDB_QUERY, params={"fields": fields, "sb-class": sb_class}, timeout=timeout
            )
            results.append((f"{sb_class}.json", response.content))
        return results

    return fetch


def horizons_bodies(bodies: dict[str, str], timeout: float = 60.0) -> Fetcher:
    """bodies: {filename_stem: horizons_command_id}."""

    async def fetch(client: httpx.AsyncClient) -> list[tuple[str, bytes]]:
        results = []
        for name, command in bodies.items():
            response = await get(
                client,
                HORIZONS_API,
                params={
                    "format": "json",
                    "COMMAND": f"'{command}'",
                    "OBJ_DATA": "'YES'",
                    "MAKE_EPHEM": "'NO'",
                },
                timeout=timeout,
            )
            results.append((f"{name}.json", response.content))
        return results

    return fetch


_EXOPLANET_ARCHIVE_TABLES = [
    "pscomppars", "ps", "k2pandc", "toi", "cumulative", "stellarhosts",
]

_SB9_TABLES = {
    "main.csv": "B/sb9/main",
    "orbits.csv": "B/sb9/orbits",
    "alias.csv": "B/sb9/alias",
}

_HORIZONS_MAJOR_BODIES = {
    "sun": "10",
    "mercury": "199",
    "venus": "299",
    "earth": "399",
    "mars": "499",
    "jupiter": "599",
    "saturn": "699",
    "uranus": "799",
    "neptune": "899",
    "pluto": "999",
}

DOWNLOAD_PLAN: dict[str, Fetcher] = {}

for _group in [
    "active", "stations", "starlink", "gps-ops", "galileo", "weather",
    "science", "geo", "cubesat", "military", "last-30-days",
]:
    _key = f"celestrak_gp_{_group.replace('-', '_')}"
    DOWNLOAD_PLAN[_key] = static_file(
        f"https://celestrak.org/NORAD/elements/gp.php?GROUP={_group}&FORMAT=json",
        "gp.json",
    )

DOWNLOAD_PLAN["celestrak_satcat"] = static_file(
    "https://celestrak.org/pub/satcat.csv", "satcat.csv"
)
DOWNLOAD_PLAN["jpl_sat_phys_par"] = static_file(
    "https://ssd.jpl.nasa.gov/sats/phys_par/", "phys_par.html"
)
DOWNLOAD_PLAN["jpl_sat_elem"] = static_file(
    "https://ssd.jpl.nasa.gov/sats/elem/", "elem.html"
)
DOWNLOAD_PLAN["jpl_sat_discovery"] = static_file(
    "https://ssd.jpl.nasa.gov/sats/discovery.html", "discovery.html"
)
DOWNLOAD_PLAN["nssdc_planetary_factsheet"] = None  # dead: redirects to a generic NASA
# landing page, not fact-sheet data — see registry.py notes. Physical parameters come
# from jpl_horizons instead.
DOWNLOAD_PLAN["jpl_horizons"] = horizons_bodies(_HORIZONS_MAJOR_BODIES)
DOWNLOAD_PLAN["sbdb_query_neo"] = sbdb_classes(
    ["IEO", "ATE", "APO", "AMO"],
    fields="full_name,spkid,pdes,name,a,e,i,om,w,ma,epoch,H,diameter,albedo,class,neo,pha",
)
DOWNLOAD_PLAN["cneos_cad"] = static_file(
    f"{CNEOS_CAD}?date-min=1900-01-01&date-max=2200-01-01&dist-max=0.2&fullname=true",
    "cad.json",
    timeout=180.0,
)
DOWNLOAD_PLAN["cneos_sentry"] = static_file(CNEOS_SENTRY, "sentry.json")

for _table in _EXOPLANET_ARCHIVE_TABLES:
    DOWNLOAD_PLAN[f"exoplanet_archive_{_table}"] = tap_full_table(
        EXOPLANET_ARCHIVE_TAP, _table, f"{_table}.csv"
    )

DOWNLOAD_PLAN["open_exoplanet_catalogue"] = None  # deliberately skipped, see registry notes
DOWNLOAD_PLAN["exoplanet_eu"] = static_file(
    "https://exoplanet.eu/catalog/csv/", "catalog.csv", timeout=120.0
)

DOWNLOAD_PLAN["hyg_database"] = static_file(
    "https://raw.githubusercontent.com/astronexus/HYG-Database/main/hyg/CURRENT/hygdata_v41.csv",
    "hygdata_v41.csv",
)
DOWNLOAD_PLAN["simbad_tap"] = None  # deferred to Fase 3 crosswalk, see registry notes
DOWNLOAD_PLAN["vizier_tap"] = None  # generic access point, not a dataset of its own
DOWNLOAD_PLAN["iau_star_names"] = static_file(
    "https://www.pas.rochester.edu/~emamajek/WGSN/IAU-CSN.txt", "IAU-CSN.txt"
)

DOWNLOAD_PLAN["wds_catalog"] = vizier_table("B/wds/wds", "wds.csv")
DOWNLOAD_PLAN["sb9_catalog"] = multi_vizier_tables(_SB9_TABLES)
DOWNLOAD_PLAN["kepler_eb_catalog"] = static_file(
    "https://keplerebs.villanova.edu/?format=csv", "kebc.csv"
)
DOWNLOAD_PLAN["msc_catalog"] = vizier_table("J/ApJS/235/6/catalog", "catalog.csv")
DOWNLOAD_PLAN["gaia_dr3_nss"] = None  # Tier 2, deferred

DOWNLOAD_PLAN["mpc_mpcorb"] = static_file(
    "https://www.minorplanetcenter.net/iau/MPCORB/MPCORB.DAT.gz", "MPCORB.DAT.gz", timeout=300.0
)  # Tier 2, not run until confirmed
DOWNLOAD_PLAN["mpc_comet_els"] = static_file(
    "https://www.minorplanetcenter.net/iau/MPCORB/CometEls.txt", "CometEls.txt"
)  # Tier 2, not run until confirmed

DOWNLOAD_PLAN["ucs_satellite_db"] = None  # requires_credentials, see registry notes
DOWNLOAD_PLAN["spacetrack"] = None  # requires_credentials
DOWNLOAD_PLAN["usgs_gazetteer"] = None  # Tier 2; nomenclature is per-body GIS shapefiles
# (asc-planetarynames-data.s3, ~100+ files), not a flat table — needs a dedicated
# shapefile-aware downloader, deferred rather than rushed.
DOWNLOAD_PLAN["sbdb_query_full"] = sbdb_classes(
    ["MBA", "IMB", "OMB", "MCA", "TJN", "CEN", "TNO", "AST", "HTC", "JFC", "ETc"],
    fields="full_name,spkid,pdes,name,a,e,i,om,w,ma,epoch,H,diameter,albedo,class,neo,pha",
    timeout=300.0,
)
DOWNLOAD_PLAN["gaia_dr3_tap"] = None  # Tier 3, ESA TAP returning 503 at probe time anyway

DOWNLOAD_PLAN["openngc"] = static_file(
    "https://raw.githubusercontent.com/mattiaverga/OpenNGC/master/database_files/NGC.csv",
    "NGC.csv",
)
DOWNLOAD_PLAN["messier_catalog"] = static_file(
    "https://raw.githubusercontent.com/mattiaverga/OpenNGC/master/database_files/NGC.csv",
    "NGC.csv",
)
