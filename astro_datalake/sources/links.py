"""Complete download-link registry: every source key -> concrete fetchable targets.

This module is *data only*. It holds no HTTP logic, so the exact same
definitions can be consumed by:

  - `astro_datalake.downloaders` (turns each target into an async fetcher),
  - `astro_datalake.manifest` (renders public/manifest.json),
  - `worker/index.js` + `public/` (the Cloudflare Worker and static site read
    the generated `public/manifest.json`, which is built from here).

Every key in `sources.registry.SOURCES` has an entry here. A source is in
exactly one `LinkStatus`:

  DIRECT       — a plain GET URL a browser/curl can fetch as-is.
  QUERY        — a GET/POST with parameters (TAP/ADQL, SBDB, form POST).
                 Still fully resolvable; `resolved_url` renders the GET form.
  CREDENTIALED — endpoint is real and documented, but needs an account.
  RETIRED      — endpoint is gone; `replaced_by` names what covers it now.

All URLs below were verified live on 2026-08-21 (see CHANGELOG.md) — none
are guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping
from urllib.parse import urlencode

from ..core.config import settings


class LinkStatus(str, Enum):
    DIRECT = "direct"
    QUERY = "query"
    CREDENTIALED = "credentialed"
    RETIRED = "retired"


@dataclass(frozen=True)
class DownloadTarget:
    """One concrete file to fetch for a source."""

    filename: str
    url: str
    method: str = "GET"
    params: Mapping[str, str] = field(default_factory=dict)
    data: Mapping[str, str] = field(default_factory=dict)
    headers: Mapping[str, str] = field(default_factory=dict)
    timeout: float = 90.0
    media_type: str = "application/octet-stream"
    approx_bytes: int | None = None
    note: str = ""
    # Row cap sent to a TAP server. Set on every TAP target: servers clip at
    # their own default and return a well-formed CSV with no warning, so the
    # downloader needs a number to compare the row count against.
    maxrec: int | None = None
    # Shown in place of a secret header value in published output (manifest,
    # website, curl snippets). Never the value itself.
    secret_placeholder: str = "$ASTRO_DL_TOKEN"

    @property
    def resolved_url(self) -> str:
        """Full URL including querystring — what you'd paste into a browser."""
        if not self.params:
            return self.url
        sep = "&" if "?" in self.url else "?"
        return f"{self.url}{sep}{urlencode(self.params)}"

    @property
    def browser_fetchable(self) -> bool:
        """True when a plain click/curl with no body or auth header works."""
        return self.method == "GET" and not self.data and not self.headers

    def curl_command(self) -> str:
        """A copy-pasteable curl for this target (used by the static site)."""
        parts = ["curl", "-L", "--compressed"]
        for key, value in self.headers.items():
            shown = self.secret_placeholder if _is_secret_header(key) else value
            parts += ["-H", _shell_quote(f"{key}: {shown}")]
        if self.method == "POST":
            parts += ["-X", "POST"]
            for key, value in self.data.items():
                parts += ["--data-urlencode", _shell_quote(f"{key}={value}")]
        parts += ["-o", _shell_quote(self.filename), _shell_quote(self.resolved_url)]
        return " ".join(parts)


def _is_secret_header(name: str) -> bool:
    return name.lower() in {"authorization", "cookie", "x-api-key"}


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


@dataclass(frozen=True)
class SourceLinks:
    """All targets for one registry source, plus how reachable it is."""

    status: LinkStatus
    targets: tuple[DownloadTarget, ...] = ()
    landing_page: str | None = None
    credential_env: tuple[str, ...] = ()
    replaced_by: str | None = None
    note: str = ""

    @property
    def fetchable(self) -> bool:
        return self.status in (LinkStatus.DIRECT, LinkStatus.QUERY)


# ---------------------------------------------------------------------------
# Shared endpoints
# ---------------------------------------------------------------------------
EXOPLANET_ARCHIVE_TAP = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
VIZIER_TAP = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"
VIZIER_ASU = "https://vizier.cds.unistra.fr/viz-bin/asu-tsv"
SIMBAD_TAP = "https://simbad.cds.unistra.fr/simbad/sim-tap/sync"
GAIA_TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
SBDB_QUERY = "https://ssd-api.jpl.nasa.gov/sbdb_query.api"
HORIZONS_API = "https://ssd.jpl.nasa.gov/api/horizons.api"
CNEOS_CAD = "https://ssd-api.jpl.nasa.gov/cad.api"
CNEOS_SENTRY = "https://ssd-api.jpl.nasa.gov/sentry.api"
CELESTRAK_GP = "https://celestrak.org/NORAD/elements/gp.php"
USGS_SEARCH = "https://planetarynames.wr.usgs.gov/SearchResults"
SPACETRACK_LOGIN = "https://www.space-track.org/ajaxauth/login"
SPACETRACK_QUERY = "https://www.space-track.org/basicspacedata/query"
SOLAR_SYSTEM_API = "https://api.le-systeme-solaire.net/rest/bodies/"

SBDB_FIELDS = (
    "full_name,spkid,pdes,name,a,e,i,om,w,ma,epoch,H,diameter,albedo,class,neo,pha"
)

GAIA_SUBSET_COLUMNS = (
    "source_id,ra,dec,parallax,parallax_error,pmra,pmdec,"
    "phot_g_mean_mag,bp_rp,radial_velocity,teff_gspphot"
)
# Tier 3 default subset from the brief: nearby (parallax > 10 mas) OR bright (G < 12).
GAIA_SUBSET_WHERE = "(parallax > 10 or phot_g_mean_mag < 12)"
# gaia_source has ~1.81e9 rows; `random_index` is a uniformly shuffled 0..N-1
# column, which makes it the cheapest way to slice the table into sync-sized
# chunks.
#
# Width matters for correctness, not just speed. Measured 2026-08-21: a 50M-wide
# slice matches 99,309 subset rows but the sync endpoint returns only 90,113 of
# them — repeatably, with no warning. The VOTable header still says
# QUERY_STATUS="OK" because that INFO is written before rows stream, and setting
# MAXREC explicitly does not change the number, so this is a cutoff on large
# results rather than a row cap. A 5M-wide slice returns exactly its full count.
# 10M is used here: ~20k rows / ~3 MB per chunk, roughly a fifth of the size
# where truncation was observed, so there is real margin if the cutoff moves
# with server load.
GAIA_CHUNK_WIDTH = 10_000_000
GAIA_RANDOM_INDEX_MAX = 1_811_709_771


# Default row cap for TAP queries. Chosen well above any table we ask for and
# well below anything that would be a runaway dump; the point is not the number
# but that MAXREC is *stated*, so a clipped result is detectable.
DEFAULT_TAP_MAXREC = 2_000_000


def _tap_target(
    base_url: str,
    query: str,
    filename: str,
    *,
    timeout: float = 300.0,
    approx_bytes: int | None = None,
    note: str = "",
    esa_style: bool = False,
    maxrec: int = DEFAULT_TAP_MAXREC,
) -> DownloadTarget:
    """A TAP sync query. ESA spells the parameters in uppercase, CDS/IPAC lower."""
    if esa_style:
        params = {
            "REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv",
            "MAXREC": str(maxrec), "QUERY": query,
        }
    else:
        params = {
            "request": "doQuery", "lang": "adql", "format": "csv",
            "MAXREC": str(maxrec), "query": query,
        }
    return DownloadTarget(
        filename=filename,
        url=base_url,
        params=params,
        timeout=timeout,
        media_type="text/csv",
        approx_bytes=approx_bytes,
        note=note,
        maxrec=maxrec,
    )


def _ipac_tap_target(table: str, timeout: float = 300.0) -> DownloadTarget:
    """NASA Exoplanet Archive TAP: no `request`/`lang` params, just query+format."""
    return DownloadTarget(
        filename=f"{table}.csv",
        url=EXOPLANET_ARCHIVE_TAP,
        params={
            "query": f"select * from {table}",
            "format": "csv",
            "MAXREC": str(DEFAULT_TAP_MAXREC),
        },
        timeout=timeout,
        media_type="text/csv",
        maxrec=DEFAULT_TAP_MAXREC,
    )


def _vizier_target(table: str, filename: str, timeout: float = 300.0) -> DownloadTarget:
    return _tap_target(VIZIER_TAP, f'select * from "{table}"', filename, timeout=timeout)


LINKS: dict[str, SourceLinks] = {}


# ---------------------------------------------------------------------------
# [A] Solar system — planets & major bodies
# ---------------------------------------------------------------------------
LINKS["nssdc_planetary_factsheet"] = SourceLinks(
    status=LinkStatus.RETIRED,
    landing_page="https://www.nasa.gov/nssdc/",
    replaced_by="le_systeme_solaire + jpl_horizons",
    note=(
        "Every /planetary/factsheet/ path (index and per-planet pages alike) "
        "307-redirects to the generic https://www.nasa.gov/nssdc/ landing page — "
        "re-verified 2026-08-21, byte-identical 245 kB response for marsfact.html and "
        "planet_table_ratio.html. No live NASA-hosted copy of the comparison tables "
        "was found. The same physical parameters now come from le_systeme_solaire "
        "(bulk JSON) and jpl_horizons (OBJ_DATA), both of which are authoritative."
    ),
)

LINKS["le_systeme_solaire"] = SourceLinks(
    status=LinkStatus.QUERY,
    landing_page="https://api.le-systeme-solaire.net/",
    targets=(
        DownloadTarget(
            filename="bodies.json",
            url=SOLAR_SYSTEM_API,
            headers={"Authorization": f"Bearer {settings.solar_system_api_key}"},
            secret_placeholder="Bearer $ASTRO_DL_SOLARSYSTEM_API_KEY",
            timeout=90.0,
            media_type="application/json",
            approx_bytes=500_000,
            note=(
                "554 bodies in one response: 8 planets, 4 dwarf planets, 479 moons, "
                "55 asteroids, 7 comets, the Sun. Carries mass, volume, density, "
                "gravity, escape velocity, mean/equatorial/polar radius, flattening, "
                "sidereal orbit and rotation, axial tilt, mean temperature, orbital "
                "elements and discovery circumstances."
            ),
        ),
    ),
    note=(
        "Needs an API key sent as `Authorization: Bearer <key>`; a free key is issued "
        "at https://api.le-systeme-solaire.net/generatekey.html. A working key is "
        "checked in as the default in core/config.py (see ASTRO_DL_SOLARSYSTEM_API_KEY "
        "to override), so this source is fetchable out of the box."
    ),
)

LINKS["jpl_horizons"] = SourceLinks(
    status=LinkStatus.QUERY,
    landing_page="https://ssd.jpl.nasa.gov/horizons/app.html",
    targets=tuple(
        DownloadTarget(
            filename=f"{name}.json",
            url=HORIZONS_API,
            params={
                "format": "json",
                "COMMAND": f"'{command}'",
                "OBJ_DATA": "'YES'",
                "MAKE_EPHEM": "'NO'",
            },
            timeout=60.0,
            media_type="application/json",
        )
        for name, command in {
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
        }.items()
    ),
)

LINKS["usgs_gazetteer"] = SourceLinks(
    status=LinkStatus.QUERY,
    landing_page="https://planetarynames.wr.usgs.gov/",
    targets=(
        DownloadTarget(
            filename="nomenclature.html",
            url=USGS_SEARCH,
            method="POST",
            data={
                "Target": "",
                "Feature Type": "",
                "Continent": "",
                "Ethnicity": "",
                "Reference": "",
                "System": "",
            },
            timeout=180.0,
            media_type="text/html",
            approx_bytes=42_600_000,
            note=(
                "An empty POST to /SearchResults returns the entire gazetteer in one "
                "HTML table — 16,353 approved features across every body (Moon 9,201, "
                "Mars 2,096, Venus 2,046, Mercury 606, Titan 305, ...), with feature ID, "
                "name, target, diameter, centre/bounding lat-lon, coordinate system, "
                "continent, ethnicity, feature type + code, quad, approval status and "
                "date. Parsed with build/html_tables.py, same as the JPL satellite pages."
            ),
        ),
    ),
    note=(
        "Earlier notes claimed this source was only available as ~100 per-body GIS "
        "shapefiles. That was wrong: the search form itself bulk-exports. The shapefiles "
        "at https://planetarynames.wr.usgs.gov/GIS_Downloads remain the option if "
        "geometry (not just centre coordinates) is ever needed."
    ),
)

# ---------------------------------------------------------------------------
# [B] Natural satellites
# ---------------------------------------------------------------------------
LINKS["jpl_sat_phys_par"] = SourceLinks(
    status=LinkStatus.DIRECT,
    landing_page="https://ssd.jpl.nasa.gov/sats/phys_par/",
    targets=(
        DownloadTarget(
            filename="phys_par.html",
            url="https://ssd.jpl.nasa.gov/sats/phys_par/",
            media_type="text/html",
        ),
    ),
)
LINKS["jpl_sat_elem"] = SourceLinks(
    status=LinkStatus.DIRECT,
    landing_page="https://ssd.jpl.nasa.gov/sats/elem/",
    targets=(
        DownloadTarget(
            filename="elem.html",
            url="https://ssd.jpl.nasa.gov/sats/elem/",
            media_type="text/html",
        ),
    ),
)
LINKS["jpl_sat_discovery"] = SourceLinks(
    status=LinkStatus.DIRECT,
    landing_page="https://ssd.jpl.nasa.gov/sats/discovery.html",
    targets=(
        DownloadTarget(
            filename="discovery.html",
            url="https://ssd.jpl.nasa.gov/sats/discovery.html",
            media_type="text/html",
        ),
    ),
)

# ---------------------------------------------------------------------------
# [C] Asteroids, comets, TNOs
# ---------------------------------------------------------------------------
LINKS["sbdb_query_neo"] = SourceLinks(
    status=LinkStatus.QUERY,
    landing_page="https://ssd-api.jpl.nasa.gov/doc/sbdb_query.html",
    targets=tuple(
        DownloadTarget(
            filename=f"{sb_class}.json",
            url=SBDB_QUERY,
            params={"fields": SBDB_FIELDS, "sb-class": sb_class},
            timeout=180.0,
            media_type="application/json",
        )
        for sb_class in ("IEO", "ATE", "APO", "AMO")
    ),
)
LINKS["sbdb_query_full"] = SourceLinks(
    status=LinkStatus.QUERY,
    landing_page="https://ssd-api.jpl.nasa.gov/doc/sbdb_query.html",
    targets=tuple(
        DownloadTarget(
            filename=f"{sb_class}.json",
            url=SBDB_QUERY,
            params={"fields": SBDB_FIELDS, "sb-class": sb_class},
            timeout=600.0,
            media_type="application/json",
        )
        for sb_class in (
            "MBA", "IMB", "OMB", "MCA", "TJN", "CEN", "TNO", "AST", "HTC", "JFC", "ETc",
        )
    ),
    note="MBA alone is ~1.38M rows; Tier 2, so `astro pull --all --tier 2` gates it.",
)
LINKS["mpc_mpcorb"] = SourceLinks(
    status=LinkStatus.DIRECT,
    landing_page="https://www.minorplanetcenter.net/data",
    targets=(
        DownloadTarget(
            filename="MPCORB.DAT.gz",
            url="https://www.minorplanetcenter.net/iau/MPCORB/MPCORB.DAT.gz",
            timeout=900.0,
            media_type="application/gzip",
            approx_bytes=200_000_000,
        ),
    ),
)
LINKS["mpc_comet_els"] = SourceLinks(
    status=LinkStatus.DIRECT,
    landing_page="https://www.minorplanetcenter.net/data",
    targets=(
        DownloadTarget(
            filename="CometEls.txt",
            url="https://www.minorplanetcenter.net/iau/MPCORB/CometEls.txt",
            timeout=180.0,
            media_type="text/plain",
            approx_bytes=162_000,
        ),
    ),
)
LINKS["cneos_cad"] = SourceLinks(
    status=LinkStatus.QUERY,
    landing_page="https://ssd-api.jpl.nasa.gov/doc/cad.html",
    targets=(
        DownloadTarget(
            filename="cad.json",
            url=CNEOS_CAD,
            params={
                "date-min": "1900-01-01",
                "date-max": "2200-01-01",
                "dist-max": "0.2",
                "fullname": "true",
            },
            timeout=300.0,
            media_type="application/json",
        ),
    ),
)
LINKS["cneos_sentry"] = SourceLinks(
    status=LinkStatus.DIRECT,
    landing_page="https://ssd-api.jpl.nasa.gov/doc/sentry.html",
    targets=(
        DownloadTarget(
            filename="sentry.json",
            url=CNEOS_SENTRY,
            timeout=120.0,
            media_type="application/json",
        ),
    ),
)

# ---------------------------------------------------------------------------
# [D] Exoplanets
# ---------------------------------------------------------------------------
for _table in ("pscomppars", "ps", "k2pandc", "toi", "cumulative", "stellarhosts"):
    LINKS[f"exoplanet_archive_{_table}"] = SourceLinks(
        status=LinkStatus.QUERY,
        landing_page="https://exoplanetarchive.ipac.caltech.edu/docs/TAP/usingTAP.html",
        targets=(_ipac_tap_target(_table),),
    )

LINKS["open_exoplanet_catalogue"] = SourceLinks(
    status=LinkStatus.DIRECT,
    landing_page="https://github.com/OpenExoplanetCatalogue/open_exoplanet_catalogue",
    targets=(
        DownloadTarget(
            filename="systems.xml.gz",
            url=(
                "https://raw.githubusercontent.com/OpenExoplanetCatalogue/"
                "oec_gzip/master/systems.xml.gz"
            ),
            timeout=180.0,
            media_type="application/gzip",
            approx_bytes=1_054_000,
            note=(
                "The whole catalogue as one gzipped XML, not the thousands of "
                "per-system files in the main repo. Maintained by the OEC project "
                "itself in the companion `oec_gzip` repo and refreshed on every commit."
            ),
        ),
    ),
    note=(
        "Earlier notes said this source was unreachable because api.github.com and "
        "codeload.github.com are blocked here. The oec_gzip mirror sidesteps both: it "
        "is a single file on raw.githubusercontent.com, verified 200/1.05 MB 2026-08-21."
    ),
)

LINKS["exoplanet_eu"] = SourceLinks(
    status=LinkStatus.DIRECT,
    landing_page="https://exoplanet.eu/catalog/",
    targets=(
        DownloadTarget(
            filename="catalog.csv",
            url="https://exoplanet.eu/catalog/csv/",
            timeout=300.0,
            media_type="text/csv",
            note="Server is slow to finish streaming; needs a generous timeout.",
        ),
    ),
)

# ---------------------------------------------------------------------------
# [E] Stars
# ---------------------------------------------------------------------------
LINKS["hyg_database"] = SourceLinks(
    status=LinkStatus.DIRECT,
    landing_page="https://github.com/astronexus/HYG-Database",
    targets=(
        DownloadTarget(
            filename="hygdata_v41.csv",
            url=(
                "https://raw.githubusercontent.com/astronexus/HYG-Database/"
                "main/hyg/CURRENT/hygdata_v41.csv"
            ),
            timeout=180.0,
            media_type="text/csv",
            approx_bytes=35_000_000,
        ),
    ),
)

_SIMBAD_BASIC_COLS = (
    "b.main_id, b.ra, b.dec, b.otype, b.otype_txt, b.sp_type, b.plx_value, b.plx_err, "
    "b.pmra, b.pmdec, b.rvz_radvel, b.morph_type, b.nbref"
)

_SIMBAD_QUERIES: dict[str, str] = {
    f"otype_{_slug}.csv": (
        f"select {_SIMBAD_BASIC_COLS} from basic b "
        f"join otypes o on b.oid = o.oidref where o.otype = '{_otype}'"
    )
    for _slug, _otype in [
        ("brown_dwarfs", "BD*"),
        ("neutron_stars", "N*"),
        ("black_holes", "BH"),
        ("supergiants", "sg*"),
    ]
}
# No SIMBAD otype exists for hypergiants; the MK luminosity class does the work
# instead ("Ia+" / "Ia-0" is the standard notation for a hypergiant).
_SIMBAD_QUERIES["otype_hypergiants.csv"] = (
    f"select {_SIMBAD_BASIC_COLS} from basic b "
    "where b.sp_type like '%Ia+%' or b.sp_type like '%Ia-0%' or b.sp_type like '%0-Ia%'"
)
for _slug, _prefix in [
    ("gaia_dr3", "Gaia DR3 "),
    ("tic", "TIC "),
    ("twomass", "2MASS "),
    ("hd", "HD "),
]:
    _SIMBAD_QUERIES[f"xwalk_hip_{_slug}.csv"] = (
        f"select i1.id as hip_id, i2.id as other_id from ident i1 "
        f"join ident i2 on i1.oidref = i2.oidref "
        f"where i1.id like 'HIP %' and i2.id like '{_prefix}%'"
    )
_SIMBAD_QUERIES["xwalk_hip_main_id.csv"] = (
    "select i.id as hip_id, b.main_id, b.otype, b.sp_type "
    "from ident i join basic b on i.oidref = b.oid where i.id like 'HIP %'"
)

LINKS["simbad_tap"] = SourceLinks(
    status=LinkStatus.QUERY,
    landing_page="https://simbad.cds.unistra.fr/simbad/sim-tap",
    targets=tuple(
        _tap_target(SIMBAD_TAP, _adql, _filename, timeout=600.0)
        for _filename, _adql in _SIMBAD_QUERIES.items()
    ),
    note=(
        "Seven bounded queries, not a dump: five object-type slices that feed "
        "stars/special/ and four HIP<->{main_id,Gaia DR3,TIC,2MASS,HD} identifier "
        "joins that feed _catalog/crosswalk.parquet. Two gotchas verified live — "
        "magnitudes live in `allfluxes`, not `basic`, so a magnitude cut needs the "
        "join (a bare `where V < 10` returns HTTP 400 'Unknown column V'); and "
        "SIMBAD silently truncates at MAXREC=50000, so MAXREC is always sent "
        "explicitly and the downloader rejects a result sitting on the limit."
    ),
)

LINKS["gaia_dr3_tap"] = SourceLinks(
    status=LinkStatus.QUERY,
    landing_page="https://gea.esac.esa.int/archive/",
    targets=tuple(
        _tap_target(
            GAIA_TAP,
            f"select {GAIA_SUBSET_COLUMNS} from gaiadr3.gaia_source "
            f"where random_index >= {_start} and random_index < {_start + GAIA_CHUNK_WIDTH} "
            f"and {GAIA_SUBSET_WHERE}",
            f"subset_{_start // GAIA_CHUNK_WIDTH:04d}.csv",
            timeout=900.0,
            approx_bytes=3_200_000,
            esa_style=True,
        )
        for _start in range(0, GAIA_RANDOM_INDEX_MAX, GAIA_CHUNK_WIDTH)
    ),
    note=(
        "Tier 3. Full gaia_source is 1.81e9 rows; the brief's default subset "
        "(parallax > 10 mas OR G < 12) is 3,602,117 rows — counted live 2026-08-21, "
        "not estimated. Split into 182 `random_index` slices of 10M each. The width "
        "is a correctness constraint: at 50M the sync endpoint silently returned "
        "90,113 of a matching 99,309 rows, while a 5M slice returned its exact count "
        "(see GAIA_CHUNK_WIDTH). Still never runs without an explicit --tier 3 "
        "instruction."
    ),
)

LINKS["vizier_tap"] = SourceLinks(
    status=LinkStatus.QUERY,
    landing_page="https://vizier.cds.unistra.fr/",
    targets=(
        DownloadTarget(
            filename="catalog_metadata.tsv",
            url=VIZIER_ASU,
            params={"-source": "METAcat", "-out.max": "unlimited"},
            timeout=300.0,
            media_type="text/tab-separated-values",
            approx_bytes=4_650_000,
            note=(
                "VizieR's own METAcat table: the index of every catalogue VizieR "
                "serves. Used to resolve catalogue designations before issuing a "
                "per-catalogue TAP query (wds/sb9/msc below are those queries)."
            ),
        ),
    ),
    note=(
        "TAPVizieR is a service access point rather than a dataset, so the target here "
        "is its catalogue index. Note TAP_SCHEMA queries on TAPVizieR return HTTP 500 "
        "(server-side SQL translation bug, re-checked 2026-08-21) — the ASU METAcat "
        "endpoint is the working way to enumerate catalogues."
    ),
)

LINKS["iau_star_names"] = SourceLinks(
    status=LinkStatus.DIRECT,
    landing_page="https://www.iau.org/science/scientific_bodies/working_groups/280/",
    targets=(
        DownloadTarget(
            filename="IAU-CSN.txt",
            url="https://www.pas.rochester.edu/~emamajek/WGSN/IAU-CSN.txt",
            timeout=90.0,
            media_type="text/plain",
        ),
    ),
)

# ---------------------------------------------------------------------------
# [F] Binary & multiple systems
# ---------------------------------------------------------------------------
LINKS["wds_catalog"] = SourceLinks(
    status=LinkStatus.QUERY,
    landing_page="https://vizier.cds.unistra.fr/viz-bin/VizieR?-source=B/wds",
    targets=(_vizier_target("B/wds/wds", "wds.csv", timeout=600.0),),
)
LINKS["sb9_catalog"] = SourceLinks(
    status=LinkStatus.QUERY,
    landing_page="https://vizier.cds.unistra.fr/viz-bin/VizieR?-source=B/sb9",
    targets=(
        _vizier_target("B/sb9/main", "main.csv"),
        _vizier_target("B/sb9/orbits", "orbits.csv"),
        _vizier_target("B/sb9/alias", "alias.csv"),
    ),
)
LINKS["kepler_eb_catalog"] = SourceLinks(
    status=LinkStatus.DIRECT,
    landing_page="https://keplerebs.villanova.edu/",
    targets=(
        DownloadTarget(
            filename="kebc.csv",
            url="https://keplerebs.villanova.edu/?format=csv",
            timeout=180.0,
            media_type="text/csv",
        ),
    ),
)
LINKS["msc_catalog"] = SourceLinks(
    status=LinkStatus.QUERY,
    landing_page="https://vizier.cds.unistra.fr/viz-bin/VizieR?-source=J/ApJS/235/6",
    targets=(
        _vizier_target("J/ApJS/235/6/catalog", "catalog.csv"),
        _vizier_target("J/ApJS/235/6/systems", "systems.csv"),
        _vizier_target("J/ApJS/235/6/orbits", "orbits.csv"),
        _vizier_target("J/ApJS/235/6/notes", "notes.csv"),
    ),
)
LINKS["gaia_dr3_nss"] = SourceLinks(
    status=LinkStatus.QUERY,
    landing_page="https://gea.esac.esa.int/archive/",
    targets=(
        _tap_target(
            GAIA_TAP,
            "select * from gaiadr3.nss_two_body_orbit",
            "nss_two_body_orbit.csv",
            timeout=900.0,
            approx_bytes=400_000_000,
            esa_style=True,
        ),
    ),
    note=(
        "~800k rows, Tier 2. The ESA TAP HTTP 503 recorded during Fase 1 was a "
        "transient outage: re-probed 2026-08-21 and both this and gaia_dr3_tap "
        "answer normally."
    ),
)

# ---------------------------------------------------------------------------
# [G] Artificial satellites
# ---------------------------------------------------------------------------
for _group in (
    "active", "stations", "starlink", "gps-ops", "galileo", "weather",
    "science", "geo", "cubesat", "military", "last-30-days",
):
    LINKS[f"celestrak_gp_{_group.replace('-', '_')}"] = SourceLinks(
        status=LinkStatus.QUERY,
        landing_page="https://celestrak.org/NORAD/elements/",
        targets=(
            DownloadTarget(
                filename="gp.json",
                url=CELESTRAK_GP,
                params={"GROUP": _group, "FORMAT": "json"},
                timeout=120.0,
                media_type="application/json",
            ),
        ),
    )

LINKS["celestrak_satcat"] = SourceLinks(
    status=LinkStatus.DIRECT,
    landing_page="https://celestrak.org/satcat/search.php",
    targets=(
        DownloadTarget(
            filename="satcat.csv",
            url="https://celestrak.org/pub/satcat.csv",
            timeout=300.0,
            media_type="text/csv",
            approx_bytes=9_000_000,
        ),
    ),
)

LINKS["spacetrack"] = SourceLinks(
    status=LinkStatus.CREDENTIALED,
    landing_page="https://www.space-track.org/documentation#/api",
    credential_env=("ASTRO_DL_SPACETRACK_USER", "ASTRO_DL_SPACETRACK_PASS"),
    targets=(
        DownloadTarget(
            filename="gp.json",
            url=f"{SPACETRACK_QUERY}/class/gp/orderby/NORAD_CAT_ID/format/json",
            timeout=900.0,
            media_type="application/json",
            note="Current GP element set for every catalogued object.",
        ),
        DownloadTarget(
            filename="satcat.json",
            url=f"{SPACETRACK_QUERY}/class/satcat/orderby/NORAD_CAT_ID/format/json",
            timeout=900.0,
            media_type="application/json",
            note="Space-Track's own satellite catalogue, incl. decay data.",
        ),
        DownloadTarget(
            filename="decay.json",
            url=f"{SPACETRACK_QUERY}/class/decay/orderby/NORAD_CAT_ID/format/json",
            timeout=900.0,
            media_type="application/json",
        ),
    ),
    note=(
        "Free account required. The downloader POSTs identity/password to "
        f"{SPACETRACK_LOGIN} to get a session cookie, then GETs the query URLs above. "
        "Without both env vars set the source is skipped, never half-attempted."
    ),
)

LINKS["ucs_satellite_db"] = SourceLinks(
    status=LinkStatus.DIRECT,
    landing_page="https://www.ucs.org/resources/satellite-database",
    targets=(
        DownloadTarget(
            filename="UCS-Satellite-Database.xlsx",
            url="https://www.ucs.org/media/11492",
            timeout=180.0,
            media_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            approx_bytes=1_498_000,
            note=(
                "Redirects to the dated file under /sites/default/files/ — following "
                "redirects lands on the current release (1.5 MB xlsx as of 2026-08-21)."
            ),
        ),
    ),
    note=(
        "Previously marked as needing credentials because the landing page only offers "
        "an email opt-in form. The media link is public and unauthenticated — verified "
        "200 with the xlsx content type on 2026-08-21, so no opt-in is actually needed."
    ),
)

# ---------------------------------------------------------------------------
# [H] Deep sky
# ---------------------------------------------------------------------------
_OPENNGC_BASE = "https://raw.githubusercontent.com/mattiaverga/OpenNGC/master/database_files"
LINKS["openngc"] = SourceLinks(
    status=LinkStatus.DIRECT,
    landing_page="https://github.com/mattiaverga/OpenNGC",
    targets=(
        DownloadTarget(
            filename="NGC.csv",
            url=f"{_OPENNGC_BASE}/NGC.csv",
            timeout=180.0,
            media_type="text/csv",
        ),
        DownloadTarget(
            filename="addendum.csv",
            url=f"{_OPENNGC_BASE}/addendum.csv",
            timeout=120.0,
            media_type="text/csv",
            note="Non-NGC/IC objects the project tracks alongside the main catalogue.",
        ),
    ),
)
LINKS["messier_catalog"] = SourceLinks(
    status=LinkStatus.DIRECT,
    landing_page="https://github.com/mattiaverga/OpenNGC",
    targets=(
        DownloadTarget(
            filename="NGC.csv",
            url=f"{_OPENNGC_BASE}/NGC.csv",
            timeout=180.0,
            media_type="text/csv",
            note="Messier objects are the rows with a non-empty `M` column.",
        ),
    ),
)


# ---------------------------------------------------------------------------
# Fase 5 additions (ported into the link registry on merge with main)
# ---------------------------------------------------------------------------
LINKS["atnf_pulsar_catalog"] = SourceLinks(
    status=LinkStatus.QUERY,
    landing_page="https://vizier.cds.unistra.fr/viz-bin/VizieR?-source=B/psr",
    targets=(_vizier_target("B/psr/psr", "psr.csv"),),
)
LINKS["blackcat_bh_transients"] = SourceLinks(
    status=LinkStatus.QUERY,
    landing_page="https://vizier.cds.unistra.fr/viz-bin/VizieR?-source=J/A+A/587/A61",
    targets=(_vizier_target("J/A+A/587/A61/tablea1", "blackcat.csv"),),
)
LINKS["iau_meteor_data_center"] = SourceLinks(
    status=LinkStatus.DIRECT,
    landing_page="https://www.ta3.sk/IAUC22DB/MDC2022/",
    targets=(
        DownloadTarget(
            filename="streamestablisheddata.txt",
            url="https://www.ta3.sk/IAUC22DB/MDC2022/Etc/streamestablisheddata2026.txt",
            timeout=120.0,
            media_type="text/plain",
            note="Established showers only (IAU-numbered and named).",
        ),
        DownloadTarget(
            filename="streamfulldata.txt",
            url="https://www.ta3.sk/IAUC22DB/MDC2022/Etc/streamfulldata2026.txt",
            timeout=120.0,
            media_type="text/plain",
            note="Full working list, including unconfirmed showers.",
        ),
    ),
    note=(
        "Filenames carry the year (…2026.txt) and the MDC rolls them forward, so this "
        "pair needs re-checking each year rather than being assumed stable."
    ),
)
LINKS["sbdb_query_hyperbolic"] = SourceLinks(
    status=LinkStatus.QUERY,
    landing_page="https://ssd-api.jpl.nasa.gov/doc/sbdb_query.html",
    targets=tuple(
        DownloadTarget(
            filename=f"{sb_class}.json",
            url=SBDB_QUERY,
            params={
                "fields": (
                    "full_name,spkid,pdes,name,a,q,e,i,om,w,tp,epoch,H,diameter,"
                    "albedo,class,neo,pha"
                ),
                "sb-class": sb_class,
            },
            timeout=180.0,
            media_type="application/json",
        )
        for sb_class in ("HYP", "PAR", "HYA")
    ),
    note=(
        "Hyperbolic/parabolic classes need `q` and `tp` instead of `ma`: a hyperbolic "
        "orbit has no mean anomaly to speak of, so the standard SBDB field list used "
        "elsewhere would come back mostly null."
    ),
)

# Epoch of the bulk of SBDB's orbit solutions, so the giant-planet longitudes line
# up with the asteroid elements they get compared against (trojan L4/L5 split in
# build/small_bodies.py) with no propagation needed for most objects.
SBDB_REFERENCE_EPOCH_JD = "2461200.5"

LINKS["jpl_horizons_elements"] = SourceLinks(
    status=LinkStatus.QUERY,
    landing_page="https://ssd.jpl.nasa.gov/horizons/app.html",
    targets=tuple(
        DownloadTarget(
            filename=f"{name}.txt",
            url=HORIZONS_API,
            params={
                "format": "text",
                "COMMAND": f"'{command}'",
                "OBJ_DATA": "'NO'",
                "MAKE_EPHEM": "'YES'",
                "EPHEM_TYPE": "'ELEMENTS'",
                "CENTER": "'500@10'",
                "TLIST": SBDB_REFERENCE_EPOCH_JD,
                "OUT_UNITS": "'AU-D'",
            },
            timeout=120.0,
            media_type="text/plain",
        )
        for name, command in {
            "jupiter_barycenter": "5",
            "neptune_barycenter": "8",
        }.items()
    ),
    note="Heliocentric osculating elements at the SBDB reference epoch.",
)


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------
def targets_for(source_key: str) -> tuple[DownloadTarget, ...]:
    links = LINKS.get(source_key)
    return links.targets if links else ()


def links_for(source_key: str) -> SourceLinks | None:
    return LINKS.get(source_key)


def fetchable_keys() -> list[str]:
    return sorted(key for key, links in LINKS.items() if links.fetchable)


def total_target_count() -> int:
    return sum(len(links.targets) for links in LINKS.values())
