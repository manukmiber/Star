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

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx

from urllib.parse import urlencode

from .core.config import settings
from .core.http import get, post
from .sources import spacetrack as st

LOGGER = logging.getLogger("astro_datalake.downloaders")

Fetcher = Callable[[httpx.AsyncClient], Awaitable[list[tuple[str, bytes]]]]


@dataclass(frozen=True)
class DeclaredRequest:
    """One HTTP request a downloader will make.

    `check_url` is an equivalent but deliberately small request (a TAP
    `top 5`, an SBDB `limit=5`) used by `astro links` so verifying a link
    doesn't mean pulling the entire catalogue behind it. It defaults to
    `url` when the real request is already cheap.
    """

    method: str
    url: str
    check_url: str | None = None

    @property
    def probe_url(self) -> str:
        return self.check_url or self.url


def _declare(fetch: Fetcher, *requests: DeclaredRequest) -> Fetcher:
    """Record the exact requests a fetcher will issue.

    `astro links` reads this back so link-checking exercises the real
    download targets instead of a separately-maintained URL list that can
    drift away from what the downloader actually does.
    """
    fetch.request_urls = list(requests)  # type: ignore[attr-defined]
    return fetch


def declared_requests(key: str) -> list[DeclaredRequest]:
    """Requests `key`'s downloader will issue; empty if it has no plan."""
    fetcher = DOWNLOAD_PLAN.get(key)
    return list(getattr(fetcher, "request_urls", []) or [])

EXOPLANET_ARCHIVE_TAP = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
VIZIER_TAP = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"
SBDB_QUERY = "https://ssd-api.jpl.nasa.gov/sbdb_query.api"
HORIZONS_API = "https://ssd.jpl.nasa.gov/api/horizons.api"
CNEOS_CAD = "https://ssd-api.jpl.nasa.gov/cad.api"
CNEOS_SENTRY = "https://ssd-api.jpl.nasa.gov/sentry.api"
GAIA_TAP = "https://gea.esac.esa.int/tap-server/tap"


def static_file(url: str, filename: str, timeout: float = 90.0) -> Fetcher:
    async def fetch(client: httpx.AsyncClient) -> list[tuple[str, bytes]]:
        response = await get(client, url, timeout=timeout)
        return [(filename, response.content)]

    return _declare(fetch, DeclaredRequest("GET", url))


def tap_full_table(base_url: str, table: str, filename: str = "data.csv", timeout: float = 180.0) -> Fetcher:
    params = {"query": f"select * from {table}", "format": "csv"}

    async def fetch(client: httpx.AsyncClient) -> list[tuple[str, bytes]]:
        response = await get(client, base_url, params=params, timeout=timeout)
        return [(filename, response.content)]

    check_params = dict(params, query=f"select top 5 * from {table}")
    return _declare(
        fetch,
        DeclaredRequest(
            "GET", f"{base_url}?{urlencode(params)}", f"{base_url}?{urlencode(check_params)}"
        ),
    )


def vizier_table(table: str, filename: str, timeout: float = 180.0) -> Fetcher:
    params = {
        "request": "doQuery",
        "lang": "adql",
        "format": "csv",
        "query": f'select * from "{table}"',
    }

    async def fetch(client: httpx.AsyncClient) -> list[tuple[str, bytes]]:
        response = await get(client, VIZIER_TAP, params=params, timeout=timeout)
        return [(filename, response.content)]

    check_params = dict(params, query=f'select top 5 * from "{table}"')
    return _declare(
        fetch,
        DeclaredRequest(
            "GET", f"{VIZIER_TAP}?{urlencode(params)}", f"{VIZIER_TAP}?{urlencode(check_params)}"
        ),
    )


def multi_vizier_tables(tables: dict[str, str], timeout: float = 180.0) -> Fetcher:
    """tables: {filename: table_name}, fetched sequentially (still rate-limited)."""

    singles = {
        filename: vizier_table(table, filename, timeout=timeout)
        for filename, table in tables.items()
    }

    async def fetch(client: httpx.AsyncClient) -> list[tuple[str, bytes]]:
        results = []
        for single in singles.values():
            results.extend(await single(client))
        return results

    return _declare(fetch, *[r for f in singles.values() for r in f.request_urls])


async def _tap_async_job(
    client: httpx.AsyncClient,
    base_url: str,
    query: str,
    *,
    response_format: str = "csv",
    poll_seconds: float = 10.0,
    max_wait_seconds: float = 3600.0,
) -> bytes:
    """Run a TAP query as a UWS async job and return the result body.

    Sync TAP endpoints truncate at the server's MAXREC (2000 rows on ESA's
    Gaia TAP), so anything catalogue-sized has to go through /async: POST the
    job, poll /phase until COMPLETED, then GET /results/result.
    """
    submit = await post(
        client,
        f"{base_url.rstrip('/')}/async",
        data={
            "REQUEST": "doQuery",
            "LANG": "ADQL",
            "FORMAT": response_format,
            "PHASE": "RUN",
            "QUERY": query,
        },
        timeout=120.0,
        follow_redirects=False,
        raise_for_status=False,
    )
    job_url = submit.headers.get("location")
    if not job_url:
        raise RuntimeError(
            f"TAP async job was not created (HTTP {submit.status_code}): {submit.text[:300]!r}"
        )

    waited = 0.0
    while waited < max_wait_seconds:
        phase_response = await get(client, f"{job_url}/phase", timeout=60.0)
        phase = phase_response.text.strip()
        LOGGER.info("TAP async job %s: %s (%.0fs)", job_url, phase, waited)
        if phase == "COMPLETED":
            result = await get(client, f"{job_url}/results/result", timeout=1800.0)
            return result.content
        if phase in {"ERROR", "ABORTED"}:
            error = await get(client, f"{job_url}", timeout=60.0, raise_for_status=False)
            raise RuntimeError(f"TAP async job {phase}: {error.text[:500]!r}")
        await asyncio.sleep(poll_seconds)
        waited += poll_seconds
    raise TimeoutError(f"TAP async job still running after {max_wait_seconds:.0f}s: {job_url}")


def tap_async_table(
    base_url: str,
    query: str,
    filename: str,
    *,
    response_format: str = "csv",
    check_query: str | None = None,
) -> Fetcher:
    """Fetcher for a TAP query too large for the sync endpoint."""

    async def fetch(client: httpx.AsyncClient) -> list[tuple[str, bytes]]:
        content = await _tap_async_job(client, base_url, query, response_format=response_format)
        return [(filename, content)]

    sync_url = base_url.rstrip("/") + "/sync"
    probe_query = check_query or query
    return _declare(
        fetch,
        DeclaredRequest(
            "POST",
            f"{base_url.rstrip('/')}/async",
            f"{sync_url}?"
            + urlencode(
                {
                    "REQUEST": "doQuery",
                    "LANG": "ADQL",
                    "FORMAT": response_format,
                    "QUERY": probe_query,
                }
            ),
        ),
    )


def sbdb_classes(classes: list[str], fields: str, timeout: float = 120.0) -> Fetcher:
    async def fetch(client: httpx.AsyncClient) -> list[tuple[str, bytes]]:
        results = []
        for sb_class in classes:
            response = await get(
                client, SBDB_QUERY, params={"fields": fields, "sb-class": sb_class}, timeout=timeout
            )
            results.append((f"{sb_class}.json", response.content))
        return results

    return _declare(
        fetch,
        *[
            DeclaredRequest(
                "GET",
                f"{SBDB_QUERY}?{urlencode({'fields': fields, 'sb-class': c})}",
                f"{SBDB_QUERY}?{urlencode({'fields': fields, 'sb-class': c, 'limit': 5})}",
            )
            for c in classes
        ],
    )


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

    return _declare(
        fetch,
        *[
            DeclaredRequest(
                "GET",
                f"{HORIZONS_API}?"
                + urlencode(
                    {
                        "format": "json",
                        "COMMAND": f"'{command}'",
                        "OBJ_DATA": "'YES'",
                        "MAKE_EPHEM": "'NO'",
                    }
                ),
            )
            for command in bodies.values()
        ],
    )


def _spacetrack_check_url(spec: st.Query) -> str:
    """A `limit/1` twin of a Space-Track query, for link-checking only."""
    from dataclasses import replace

    return replace(spec, limit=1).url()


def spacetrack_queries(
    queries: dict[str, st.Query] | None = None,
    *,
    enforce_policy: bool = True,
    timeout: float = 300.0,
) -> Fetcher:
    """Pull one or more Space-Track classes over a single logged-in session.

    Follows https://www.space-track.org/documentation#/api: cookie login via
    /ajaxauth/login, REST query URLs built by sources.spacetrack.Query,
    client-side throttling below the documented 30/min + 300/hour ceilings,
    and the per-class retrieval-frequency table enforced through an on-disk
    ledger (skip, don't hammer). Logout happens on the way out.
    """
    queries = queries or {"gp.json": st.gp_current()}

    async def fetch(client: httpx.AsyncClient) -> list[tuple[str, bytes]]:
        creds = st.credentials_from_env()
        if creds is None:
            raise RuntimeError(
                f"Space-Track credentials missing: set {st.ENV_IDENTITY} and "
                f"{st.ENV_PASSWORD} (free account at https://www.space-track.org/auth/createAccount)"
            )
        identity, password = creds
        ledger = st.RetrievalLedger(settings.raw_dir / "spacetrack" / "retrieval-ledger.json")

        due: dict[str, st.Query] = {}
        for filename, spec in queries.items():
            allowed, reason = ledger.check(spec.class_name)
            if allowed or not enforce_policy:
                due[filename] = spec
            else:
                LOGGER.info("Space-Track: skipping per documented retrieval rate — %s", reason)
        if not due:
            return []

        results: list[tuple[str, bytes]] = []
        spacetrack = st.SpaceTrackClient(
            identity,
            password,
            client=client,
            timeout=timeout,
            user_agent=settings.user_agent,
        )
        try:
            await spacetrack.login()
            for filename, spec in due.items():
                url = spec.url()
                LOGGER.info("Space-Track GET %s", url)
                response = await spacetrack.query(spec)
                results.append((filename, response.content))
                ledger.record(spec.class_name, url, len(response.content))
        finally:
            await spacetrack.logout()
        return results

    return _declare(
        fetch,
        DeclaredRequest("POST", st.LOGIN_URL),
        *[
            DeclaredRequest("GET", spec.url(), _spacetrack_check_url(spec))
            for spec in queries.values()
        ],
    )


#: Classes pulled by `astro pull spacetrack`. GP is the current-elset class
#: the docs point at for on-orbit objects; SATCAT adds the catalogue metadata
#: (incl. decayed objects) that CelesTrak's satcat.csv only partly covers.
SPACETRACK_DEFAULT_QUERIES: dict[str, st.Query] = {
    "gp.json": st.gp_current(),
    "satcat.json": st.satcat_current(),
    "boxscore.json": st.boxscore(),
    "launch_site.json": st.launch_sites(),
}


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

#: The OEC publishes every system as one gzipped XML in the oec_gzip mirror,
#: which sidesteps the thousands-of-files problem the per-system repo has.
DOWNLOAD_PLAN["open_exoplanet_catalogue"] = static_file(
    "https://github.com/OpenExoplanetCatalogue/oec_gzip/raw/master/systems.xml.gz",
    "systems.xml.gz",
    timeout=180.0,
)
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
#: Gaia DR3 non-single stars, ~800k rows — sync TAP would truncate at MAXREC.
DOWNLOAD_PLAN["gaia_dr3_nss"] = tap_async_table(
    GAIA_TAP,
    "select * from gaiadr3.nss_two_body_orbit",
    "nss_two_body_orbit.csv",
    check_query="select top 5 * from gaiadr3.nss_two_body_orbit",
)

DOWNLOAD_PLAN["mpc_mpcorb"] = static_file(
    "https://www.minorplanetcenter.net/iau/MPCORB/MPCORB.DAT.gz", "MPCORB.DAT.gz", timeout=300.0
)  # Tier 2, not run until confirmed
DOWNLOAD_PLAN["mpc_comet_els"] = static_file(
    "https://www.minorplanetcenter.net/iau/MPCORB/CometEls.txt", "CometEls.txt"
)  # Tier 2, not run until confirmed

DOWNLOAD_PLAN["ucs_satellite_db"] = None  # requires_credentials, see registry notes
_spacetrack_fetcher = spacetrack_queries(SPACETRACK_DEFAULT_QUERIES)
#: Declared even without credentials so `astro links` can still report on the
#: Space-Track endpoints (it checks reachability, not authenticated content).
SPACETRACK_REQUESTS: list[DeclaredRequest] = list(_spacetrack_fetcher.request_urls)
if st.credentials_from_env() is not None:
    DOWNLOAD_PLAN["spacetrack"] = _spacetrack_fetcher
else:
    DOWNLOAD_PLAN["spacetrack"] = None  # requires_credentials, see registry notes
DOWNLOAD_PLAN["usgs_gazetteer"] = None  # Tier 2; nomenclature is per-body GIS shapefiles
# (asc-planetarynames-data.s3, ~100+ files), not a flat table — needs a dedicated
# shapefile-aware downloader, deferred rather than rushed.
DOWNLOAD_PLAN["sbdb_query_full"] = sbdb_classes(
    ["MBA", "IMB", "OMB", "MCA", "TJN", "CEN", "TNO", "AST", "HTC", "JFC", "ETc"],
    fields="full_name,spkid,pdes,name,a,e,i,om,w,ma,epoch,H,diameter,albedo,class,neo,pha",
    timeout=300.0,
)
#: Tier 3. The brief's default subset — nearby (parallax > 10 mas) or bright
#: (G < 12) — rather than all 1.8B rows. Never runs without `--tier 3`.
DOWNLOAD_PLAN["gaia_dr3_tap"] = tap_async_table(
    GAIA_TAP,
    "select source_id, ra, dec, parallax, parallax_error, pmra, pmdec, "
    "radial_velocity, phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag, "
    "teff_gspphot, logg_gspphot, mh_gspphot, distance_gspphot "
    "from gaiadr3.gaia_source where parallax > 10 or phot_g_mean_mag < 12",
    "gaia_source_subset.csv",
    check_query=(
        "select top 5 source_id, ra, dec, parallax, phot_g_mean_mag "
        "from gaiadr3.gaia_source where parallax > 10 or phot_g_mean_mag < 12"
    ),
)

DOWNLOAD_PLAN["openngc"] = static_file(
    "https://raw.githubusercontent.com/mattiaverga/OpenNGC/master/database_files/NGC.csv",
    "NGC.csv",
)
DOWNLOAD_PLAN["messier_catalog"] = static_file(
    "https://raw.githubusercontent.com/mattiaverga/OpenNGC/master/database_files/NGC.csv",
    "NGC.csv",
)
