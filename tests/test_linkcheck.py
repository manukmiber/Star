"""Tests for the link checker's content sniffing and verdict logic."""

from __future__ import annotations

import httpx
import pytest
import respx

from astro_datalake import linkcheck
from astro_datalake.downloaders import DeclaredRequest


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
            DeclaredRequest("GET", "https://nssdc.gsfc.nasa.gov/planetary/factsheet/"),
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
            client, "celestrak_satcat", DeclaredRequest("GET", "https://celestrak.org/pub/satcat.csv")
        )
    assert result.redirected_offsite is False
    assert result.works is True


@respx.mock
async def test_auth_wall_counts_as_a_live_endpoint():
    url = "https://www.space-track.org/basicspacedata/query/class/gp/format/json"
    respx.get(url).mock(return_value=httpx.Response(401, text="unauthorized"))
    async with httpx.AsyncClient(follow_redirects=True) as client:
        result = await linkcheck.check_link(client, "spacetrack", DeclaredRequest("GET", url))
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
        result = await linkcheck.check_link(client, "msc_catalog", DeclaredRequest("GET", url))
    assert result.works is True
    assert "after retry" in result.detail


@respx.mock
async def test_check_url_twin_is_used_instead_of_the_full_download():
    real = "https://example.test/huge.csv"
    cheap = "https://example.test/huge.csv?limit=5"
    route = respx.get(cheap).mock(return_value=httpx.Response(200, text="a,b\n1,2\n"))
    respx.get(real).mock(return_value=httpx.Response(500))
    async with httpx.AsyncClient(follow_redirects=True) as client:
        result = await linkcheck.check_link(
            client, "big", DeclaredRequest("GET", real, cheap)
        )
    assert route.called
    assert result.works is True
    assert result.url == real  # the report still names the real download URL


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
