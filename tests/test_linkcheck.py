"""Tests for the link checker's content sniffing and verdict logic."""

from __future__ import annotations

import httpx
import pytest
import respx

from astro_datalake import linkcheck
from astro_datalake.sources.links import DownloadTarget


# --- expected_kind_for -----------------------------------------------------
@pytest.mark.parametrize(
    "url,kind",
    [
        ("https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=json", "json"),
        ("https://www.minorplanetcenter.net/iau/MPCORB/MPCORB.DAT.gz", "gzip"),
        ("https://exoplanetarchive.ipac.caltech.edu/TAP/sync?query=x&format=csv", "csv"),
        ("https://ssd.jpl.nasa.gov/sats/elem/", "html"),
        ("https://www.pas.rochester.edu/~emamajek/WGSN/IAU-CSN.txt", "text"),
        ("https://www.space-track.org/basicspacedata/query/class/gp/format/tle", "tle"),
        ("https://ssd-api.jpl.nasa.gov/sentry.api", "json"),
    ],
)
def test_expected_kind_for(url, kind):
    assert linkcheck.expected_kind_for(url) == kind


# --- sniff_content ---------------------------------------------------------
def test_json_prefix_accepted_when_truncated():
    ok, detail = linkcheck.sniff_content("json", b'[{"a": 1}, {"b"', complete=False)
    assert ok is True
    assert "truncated" in detail


def test_truncated_json_is_not_parsed_as_complete():
    ok, _ = linkcheck.sniff_content("json", b'[{"a": 1}, {"b"', complete=True)
    assert ok is False


def test_semicolon_csv_is_valid_csv():
    """OpenNGC ships ';'-delimited CSV — a comma-only check called it broken."""
    ok, detail = linkcheck.sniff_content("csv", b"Name;Type;RA;Dec\nNGC0001;G;00:07;27:42", True)
    assert ok is True
    assert "semicolon" in detail


def test_commented_preamble_before_the_header_is_skipped():
    """Villanova's Kepler EB catalog opens with '##' comment lines."""
    body = b"## Kepler Eclipsing Binary Catalog\n## v3\nKIC,period,bjd0\n1026032,8.46,54.2\n"
    ok, detail = linkcheck.sniff_content("csv", body, True)
    assert ok is True
    assert "3 columns" in detail


def test_html_where_csv_expected_is_a_failure():
    ok, detail = linkcheck.sniff_content("csv", b"<html><body>Service unavailable", True)
    assert ok is False
    assert "HTML" in detail


def test_gzip_magic_is_checked():
    assert linkcheck.sniff_content("gzip", b"\x1f\x8b\x08\x00", False)[0] is True
    assert linkcheck.sniff_content("gzip", b"<html>", False)[0] is False


def test_tle_lines_are_recognised():
    body = (
        b"ISS (ZARYA)\n"
        b"1 25544U 98067A   26233.53315667  .00016717  00000-0  10270-3 0  9004\n"
        b"2 25544  51.6331 336.6713 0007673  59.1234 301.0123 15.49551867    12\n"
    )
    assert linkcheck.sniff_content("tle", body, True)[0] is True
    assert linkcheck.sniff_content("tle", b"not an elset at all", True)[0] is False


def test_empty_body_never_passes():
    for kind in ("json", "csv", "html", "text", "gzip", "tle"):
        assert linkcheck.sniff_content(kind, b"", True)[0] is False


# --- live-ish checks via respx --------------------------------------------
@respx.mock
async def test_offsite_redirect_is_a_dead_link():
    """The nssdc case: HTTP 200, but the body came from somewhere else."""
    respx.get("https://nssdc.gsfc.nasa.gov/planetary/factsheet/").mock(
        return_value=httpx.Response(307, headers={"location": "https://www.nasa.gov/nssdc/"})
    )
    respx.get("https://www.nasa.gov/nssdc/").mock(
        return_value=httpx.Response(200, html="<html>NSSDC status</html>")
    )
    async with httpx.AsyncClient(follow_redirects=True) as client:
        result = await linkcheck.check_link(
            client,
            "nssdc",
            DownloadTarget(filename="f.html", url="https://nssdc.gsfc.nasa.gov/planetary/factsheet/"),
        )
    assert result.redirected_offsite is True
    assert result.works is False
    assert "nasa.gov/nssdc" in result.detail


@respx.mock
async def test_www_prefix_alone_is_not_a_redirect_failure():
    respx.get("https://celestrak.org/pub/satcat.csv").mock(
        return_value=httpx.Response(301, headers={"location": "https://www.celestrak.org/pub/satcat.csv"})
    )
    respx.get("https://www.celestrak.org/pub/satcat.csv").mock(
        return_value=httpx.Response(200, text="OBJECT_NAME,NORAD_CAT_ID\nISS,25544\n")
    )
    async with httpx.AsyncClient(follow_redirects=True) as client:
        result = await linkcheck.check_link(
            client, "celestrak_satcat", DownloadTarget(filename="satcat.csv", url="https://celestrak.org/pub/satcat.csv")
        )
    assert result.redirected_offsite is False
    assert result.works is True


@respx.mock
async def test_auth_wall_counts_as_a_live_endpoint():
    url = "https://www.space-track.org/basicspacedata/query/class/gp/format/json"
    respx.get(url).mock(return_value=httpx.Response(401, text="unauthorized"))
    async with httpx.AsyncClient(follow_redirects=True) as client:
        result = await linkcheck.check_link(client, "spacetrack", DownloadTarget(filename="f", url=url))
    assert result.auth_required is True
    assert result.works is True


@respx.mock
async def test_transient_500_is_retried_before_being_condemned():
    """VizieR answers 500 under load for queries that work seconds later."""
    url = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync?query=x&format=csv"
    respx.get(url__startswith="https://tapvizier.cds.unistra.fr").mock(
        side_effect=[
            httpx.Response(500, text="overloaded"),
            httpx.Response(200, text="recno,ID\n1,x\n"),
        ]
    )
    async with httpx.AsyncClient(follow_redirects=True) as client:
        result = await linkcheck.check_link(client, "msc_catalog", DownloadTarget(filename="f", url=url))
    assert result.works is True
    assert "recovered after 1 retry" in result.detail


# --- cheap twins of expensive targets --------------------------------------
def test_adql_targets_are_checked_with_a_top_5():
    """Verifying a link must not mean downloading the whole catalogue."""
    target = DownloadTarget(
        filename="wds.csv",
        url="https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync",
        params={"request": "doQuery", "lang": "adql", "format": "csv",
                "MAXREC": "2000000", "query": 'select * from "B/wds/wds"'},
    )
    check_url = linkcheck._check_url_for(target)
    assert "select+top+5+" in check_url
    assert "MAXREC=5" in check_url
    # The real download URL is untouched.
    assert "top 5" not in target.resolved_url


def test_an_already_capped_query_is_not_double_capped():
    target = DownloadTarget(
        filename="x.csv",
        url="https://example.test/tap",
        params={"query": "select top 10 * from t", "format": "csv"},
    )
    assert "top+5" not in linkcheck._check_url_for(target)


def test_sbdb_targets_get_a_row_limit():
    target = DownloadTarget(
        filename="MBA.json",
        url="https://ssd-api.jpl.nasa.gov/sbdb_query.api",
        params={"fields": "full_name", "sb-class": "MBA"},
    )
    assert "limit=5" in linkcheck._check_url_for(target)


def test_a_target_without_params_is_checked_as_is():
    target = DownloadTarget(filename="satcat.csv", url="https://celestrak.org/pub/satcat.csv")
    assert linkcheck._check_url_for(target) == target.url


@respx.mock
async def test_the_cheap_twin_is_what_actually_gets_requested():
    base = "https://example.test/tap"
    target = DownloadTarget(
        filename="huge.csv", url=base, params={"query": "select * from huge", "format": "csv"}
    )
    cheap = respx.get(url__startswith=base).mock(
        return_value=httpx.Response(200, text="a,b\n1,2\n")
    )
    async with httpx.AsyncClient(follow_redirects=True) as client:
        result = await linkcheck.check_link(client, "big", target)
    assert cheap.called
    assert "top+5" in str(cheap.calls[0].request.url)
    assert result.works is True
    # The report still names the real download URL, not the twin.
    assert result.url == target.resolved_url
    assert "top 5" not in result.url


# --- registry-driven expectations ------------------------------------------
def test_media_type_from_the_registry_wins_over_url_guessing():
    """The registry knows the format; the URL heuristics are only a fallback."""
    assert linkcheck.expected_kind_for("https://x.test/opaque", "application/json") == "json"
    assert linkcheck.expected_kind_for("https://x.test/opaque", "text/csv") == "csv"
    # Unknown media type falls back to the URL.
    assert linkcheck.expected_kind_for("https://x.test/a.csv", "application/octet-stream") == "csv"


def test_every_registered_source_has_something_to_check():
    from astro_datalake.sources.registry import SOURCES

    for key in SOURCES:
        assert linkcheck._requests_for(key), f"{key} has no checkable target"


# --- verdicts --------------------------------------------------------------
def _report(**kwargs) -> linkcheck.SourceReport:
    defaults = dict(
        key="k", name="n", tier=1, category="c", requires_credentials=False, has_plan=True
    )
    defaults.update(kwargs)
    return linkcheck.SourceReport(**defaults)


def test_verdict_ready_when_every_link_works():
    report = _report()
    report.links = [linkcheck.LinkResult("k", "GET", "u", "u", ok=True, content_ok=True)]
    assert linkcheck._verdict_for(report)[0] == linkcheck.VERDICT_READY


def test_verdict_broken_when_the_only_link_is_dead():
    report = _report()
    report.links = [linkcheck.LinkResult("k", "GET", "u", "u", ok=False, http_status=404)]
    assert linkcheck._verdict_for(report)[0] == linkcheck.VERDICT_BROKEN


def test_verdict_needs_credentials_when_guarded_and_unconfigured():
    report = _report(requires_credentials=True, has_plan=False)
    report.links = [
        linkcheck.LinkResult("k", "GET", "u", "u", ok=False, http_status=401, auth_required=True)
    ]
    verdict, reason = linkcheck._verdict_for(report)
    assert verdict == linkcheck.VERDICT_NEEDS_CREDENTIALS
    assert "login wall" in reason


def test_verdict_no_plan_for_a_live_link_without_a_downloader():
    report = _report(has_plan=False)
    report.links = [linkcheck.LinkResult("k", "GET", "u", "u", ok=True, content_ok=True)]
    assert linkcheck._verdict_for(report)[0] == linkcheck.VERDICT_NO_PLAN


# --- server-side outages vs. broken URLs ----------------------------------
def test_server_side_signatures_are_recognised():
    # CDS reports its own metadata outage as a 400, so the message decides.
    assert linkcheck.looks_server_side(
        "HTTP 400 — Incorrect ADQL query: 1 unresolved identifiers! "
        "- Unable to check the ADQL query!"
    )
    assert linkcheck.looks_server_side(
        "HTTP 503 — TAP service too busy! No connection available for the moment."
    )
    # Any 5xx is the server's fault by definition, whatever it says.
    assert linkcheck.looks_server_side("HTTP 500 — something", 500)
    assert not linkcheck.looks_server_side("HTTP 404 — Not Found", 404)


def test_a_server_side_outage_is_suspect_not_broken():
    """A URL CDS answered correctly minutes ago isn't 'broken' when CDS wobbles."""
    report = _report()
    report.links = [
        linkcheck.LinkResult(
            "k", "GET", "u", "u", ok=False, http_status=400,
            server_side_failure=True,
            detail="HTTP 400 — Unable to check the ADQL query!",
        )
    ]
    verdict, reason = linkcheck._verdict_for(report)
    assert verdict == linkcheck.VERDICT_SUSPECT
    assert "retry later" in reason


def test_a_genuine_404_is_still_broken():
    report = _report()
    report.links = [
        linkcheck.LinkResult("k", "GET", "u", "u", ok=False, http_status=404, detail="HTTP 404")
    ]
    assert linkcheck._verdict_for(report)[0] == linkcheck.VERDICT_BROKEN


# --- method and redirect handling ------------------------------------------
@respx.mock
async def test_a_post_target_is_checked_with_post():
    """The USGS Gazetteer is a POST-only form; GETting it returns 500."""
    url = "https://planetarynames.wr.usgs.gov/SearchResults"
    respx.get(url).mock(return_value=httpx.Response(500, text="method not allowed"))
    posted = respx.post(url).mock(
        return_value=httpx.Response(200, html="<html><table>results</table></html>")
    )
    target = DownloadTarget(
        filename="nomenclature.html",
        url=url,
        method="POST",
        data={"Target": "", "Feature Type": ""},
        media_type="text/html",
    )
    async with httpx.AsyncClient(follow_redirects=True) as client:
        result = await linkcheck.check_link(client, "usgs_gazetteer", target)
    assert posted.called
    assert result.works is True


@respx.mock
async def test_a_permalink_redirecting_to_the_real_file_is_fine():
    """ucs.org/media/11492 -> the actual .xlsx is a normal permalink."""
    permalink = "https://www.ucs.org/media/11492"
    real_file = "https://www.ucs.org/sites/default/files/UCS-Satellite-Database.xlsx"
    respx.get(permalink).mock(
        return_value=httpx.Response(302, headers={"location": real_file})
    )
    respx.get(real_file).mock(return_value=httpx.Response(200, content=b"PK\x03\x04binary"))
    target = DownloadTarget(
        filename="UCS-Satellite-Database.xlsx", url=permalink, media_type="application/zip"
    )
    async with httpx.AsyncClient(follow_redirects=True) as client:
        result = await linkcheck.check_link(client, "ucs_satellite_db", target)
    assert result.works is True
    assert result.redirected_offsite is False
    assert "redirected to" in result.detail


@respx.mock
async def test_a_path_redirect_that_also_fails_content_is_still_caught():
    """The landing-page pattern: path thrown away *and* not the promised data."""
    asked = "https://example.test/data/catalog.csv"
    landing = "https://example.test/status"
    respx.get(asked).mock(return_value=httpx.Response(307, headers={"location": landing}))
    respx.get(landing).mock(return_value=httpx.Response(200, html="<html>moved</html>"))
    target = DownloadTarget(filename="catalog.csv", url=asked, media_type="text/csv")
    async with httpx.AsyncClient(follow_redirects=True) as client:
        result = await linkcheck.check_link(client, "x", target)
    assert result.works is False
    assert "different path" in result.detail


def test_a_retired_source_is_reported_from_the_registry():
    """`nssdc` is marked retired in links.py; the verdict must say so."""
    report = _report(key="nssdc_planetary_factsheet", has_plan=False)
    report.links = [linkcheck.LinkResult("k", "GET", "u", "u", ok=True, content_ok=True)]
    verdict, reason = linkcheck._verdict_for(report)
    assert verdict == linkcheck.VERDICT_BROKEN
    assert "retired" in reason


# --- sampling chunked targets ----------------------------------------------
def _chunk(i: int) -> DownloadTarget:
    return DownloadTarget(
        filename=f"chunk-{i}.csv",
        url="https://gea.esac.esa.int/tap-server/tap/sync",
        params={"QUERY": f"select * from g where random_index between {i} and {i + 10}",
                "FORMAT": "csv"},
    )


def test_a_long_run_of_identical_chunks_is_sampled():
    targets = [_chunk(i) for i in range(182)]
    chosen, total = linkcheck.sample_targets(targets)
    assert total == 182
    assert len(chosen) == linkcheck.CHUNK_SAMPLE_SIZE
    # Both ends are exercised, not just the front of the list.
    assert chosen[0] is targets[0]
    assert chosen[-1] is targets[-1]


def test_distinct_requests_are_never_sampled():
    """jpl_horizons' bodies and sbdb's orbit classes can break one at a time."""
    targets = [
        DownloadTarget(filename=f"{n}.json", url=f"https://ssd.jpl.nasa.gov/api/{n}")
        for n in ("sun", "mercury", "venus", "earth", "mars", "jupiter",
                  "saturn", "uranus", "neptune", "pluto")
    ]
    chosen, total = linkcheck.sample_targets(targets)
    assert len(chosen) == total == 10


def test_differing_param_names_defeat_chunk_detection():
    targets = [_chunk(i) for i in range(30)]
    targets[5] = DownloadTarget(
        filename="odd.csv", url=targets[0].url, params={"QUERY": "x", "EXTRA": "1"}
    )
    assert linkcheck.are_generated_chunks(targets) is False
    chosen, total = linkcheck.sample_targets(targets)
    assert len(chosen) == total


def test_full_disables_sampling():
    targets = [_chunk(i) for i in range(182)]
    chosen, total = linkcheck.sample_targets(targets, full=True)
    assert len(chosen) == total == 182


def test_the_real_gaia_source_is_the_only_one_sampled():
    from astro_datalake.sources.registry import SOURCES

    sampled = {
        key
        for key in SOURCES
        if len(linkcheck.sample_targets(linkcheck._requests_for(key))[0])
        < linkcheck.sample_targets(linkcheck._requests_for(key))[1]
    }
    assert sampled == {"gaia_dr3_tap"}


def test_a_sampled_report_says_so():
    report = _report(key="gaia_dr3_tap")
    report.links = [linkcheck.LinkResult("k", "GET", "u", "u", ok=True, content_ok=True)]
    report.total_targets = 182
    assert report.sampled is True
