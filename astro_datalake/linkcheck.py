"""`astro links`: check every download link, and report download readiness.

This is deliberately stricter than Fase 1's `probe.py`, which trusted the
HTTP status code and was fooled by `nssdc_planetary_factsheet` — a URL that
answers 200 while 307-redirecting to a generic landing page with none of the
promised data (see sources/registry.py). Here a link only counts as working
when all of the following hold:

1. it answers < 400,
2. it doesn't land on a different host than the one we asked for
   (a silent redirect to a "this moved" page is a dead link),
3. the first bytes of the body actually look like the format the downloader
   expects to parse (JSON parses, CSV has a delimited header row, gzip has
   its magic number, HTML has markup, TLE has 69-character element lines).

Only a small prefix of each body is read, so verifying every link costs
kilobytes, not gigabytes.

The targets come from `sources/links.py` — the same data `downloaders.py`,
`astro manifest` and the Cloudflare frontend consume — so what gets verified
here is exactly what everything else will fetch.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .core.config import settings
from .downloaders import DOWNLOAD_PLAN, unfetchable_reason
from .sources.links import LINKS, DownloadTarget, LinkStatus
from .sources.registry import SOURCES

#: Bytes of body read before we stop and judge the content.
SAMPLE_BYTES = 32 * 1024

# Verdicts, worst-first for reporting purposes.
VERDICT_READY = "ready"
VERDICT_NEEDS_CREDENTIALS = "needs-credentials"
#: An endpoint that answers 401/403 is alive and correctly guarded, not broken.
AUTH_STATUSES = (401, 403)

#: Error text that proves the *server* is unwell rather than our URL wrong.
#: CDS's TAPVizieR intermittently loses its table-metadata service and then
#: rejects every query — including ones it answered correctly minutes before
#: — with "Unable to check the ADQL query!". Reporting that as a broken link
#: would send someone hunting for a table rename that never happened.
SERVER_SIDE_FAILURE_SIGNATURES = (
    "unable to check the adql query",
    "service unavailable",
    "temporarily unavailable",
    "too busy",
    "try later",
    "try again later",
    "no connection available",
)


def looks_server_side(detail: str, http_status: int | None = None) -> bool:
    """Is this failure the server's fault rather than the URL's?

    Any 5xx says so by definition. Below that we go by the message, because
    CDS reports its own metadata outage as a 400.
    """
    if http_status is not None and http_status >= 500:
        return True
    lowered = detail.lower()
    return any(signature in lowered for signature in SERVER_SIDE_FAILURE_SIGNATURES)
VERDICT_NO_PLAN = "no-plan"
VERDICT_SUSPECT = "suspect"
VERDICT_BROKEN = "broken"

VERDICT_ORDER = [VERDICT_BROKEN, VERDICT_SUSPECT, VERDICT_NEEDS_CREDENTIALS, VERDICT_NO_PLAN, VERDICT_READY]


@dataclass
class LinkResult:
    """The outcome of checking one URL."""

    key: str
    method: str
    url: str
    checked_url: str
    ok: bool = False
    http_status: int | None = None
    final_url: str | None = None
    redirected_offsite: bool = False
    content_type: str | None = None
    content_length: int | None = None
    elapsed_seconds: float | None = None
    expected_kind: str = "unknown"
    content_ok: bool | None = None
    auth_required: bool = False
    server_side_failure: bool = False
    detail: str = ""

    @property
    def works(self) -> bool:
        """Alive and serving what we expect — an auth wall counts as alive."""
        if self.auth_required:
            return True
        return self.ok and not self.redirected_offsite and self.content_ok is not False


@dataclass
class SourceReport:
    """Per-source rollup: is this source actually ready to download?"""

    key: str
    name: str
    tier: int
    category: str
    requires_credentials: bool
    has_plan: bool
    links: list[LinkResult] = field(default_factory=list)
    verdict: str = VERDICT_NO_PLAN
    reason: str = ""

    @property
    def working_links(self) -> int:
        return sum(1 for link in self.links if link.works)


# ---------------------------------------------------------------------------
# Content sniffing
# ---------------------------------------------------------------------------
#: media_type from the link registry -> the sniffer's format name.
_MEDIA_TYPE_KINDS = {
    "application/json": "json",
    "text/csv": "csv",
    "text/plain": "text",
    "text/html": "html",
    "application/xml": "xml",
    "text/xml": "xml",
    "application/gzip": "gzip",
    "application/zip": "gzip",
    "application/x-gzip": "gzip",
}


def expected_kind_for(url: str, media_type: str | None = None) -> str:
    """What a URL should return, from the registry's media_type or the URL.

    The registry is authoritative when it says something specific; the URL
    heuristics below only cover targets that left media_type at its
    catch-all default.
    """
    if media_type and media_type in _MEDIA_TYPE_KINDS:
        return _MEDIA_TYPE_KINDS[media_type]

    parsed = urlparse(url)
    path = parsed.path.lower()
    query = parse_qs(parsed.query)
    fmt = (query.get("format") or query.get("FORMAT") or [""])[0].lower()

    if path.endswith(".gz") or path.endswith(".zip"):
        return "gzip"
    for segment in reversed(path.strip("/").split("/")):
        if segment in {"json", "csv", "xml", "tle", "3le", "kvn", "html"}:
            return {"3le": "tle", "kvn": "text"}.get(segment, segment)
    if fmt:
        return {"3le": "tle", "kvn": "text"}.get(fmt, fmt)
    if path.endswith(".json") or ".api" in path:
        return "json"
    if path.endswith(".csv"):
        return "csv"
    if path.endswith(".txt") or path.endswith(".dat"):
        return "text"
    if path.endswith((".html", ".htm", "/")):
        return "html"
    return "unknown"


_TLE_LINE = re.compile(rb"^[12] [ 0-9A-Z]{5}")

#: VOTable error payloads (VizieR, ESA, IPAC) carry the real reason here.
_VOTABLE_ERROR = re.compile(
    rb'<INFO[^>]*name="QUERY_STATUS"[^>]*value="ERROR"[^>]*>(.*?)</INFO>', re.DOTALL | re.IGNORECASE
)


def server_error_message(sample: bytes) -> str:
    """Pull a human-readable reason out of an error body, if there is one.

    "HTTP 400" tells you nothing; "Incorrect ADQL query: 1 unresolved
    identifiers" tells you whether the query is wrong or the server's
    metadata service is having a bad day.
    """
    match = _VOTABLE_ERROR.search(sample)
    if match:
        text = re.sub(rb"\s+", b" ", match.group(1)).strip()
        return text.decode("utf-8", "replace")[:300]
    stripped = sample.strip()
    if stripped[:1] in (b"{", b"["):
        try:
            payload = json.loads(stripped)
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            for field in ("message", "error", "detail", "moreInfo"):
                if payload.get(field):
                    return str(payload[field])[:300]
    if stripped and not stripped[:1] == b"<":
        return stripped[:200].decode("utf-8", "replace")
    return ""


def sniff_content(kind: str, sample: bytes, complete: bool) -> tuple[bool | None, str]:
    """Does `sample` look like `kind`? Returns (ok, human-readable detail)."""
    if not sample:
        return False, "empty body"

    head = sample.lstrip()[:1]
    text_head = sample[:400].decode("utf-8", "replace")

    if kind == "gzip":
        if sample[:2] == b"\x1f\x8b":
            return True, "gzip magic ok"
        if sample[:2] == b"PK":
            return True, "zip magic ok"
        return False, f"not gzip/zip, starts with {sample[:8]!r}"

    if kind == "json":
        if head not in (b"{", b"["):
            return False, f"not JSON, starts with {text_head[:60]!r}"
        if complete:
            try:
                json.loads(sample)
            except ValueError as exc:
                return False, f"JSON did not parse: {exc}"
            return True, "JSON parsed"
        return True, "JSON prefix ok (truncated sample)"

    if kind == "csv":
        if b"<html" in sample[:400].lower():
            return False, "got an HTML page where CSV was expected"
        # Real catalogues are not all comma-delimited (OpenNGC uses ';') and
        # several ship a '#'-commented preamble before the header row
        # (Villanova's Kepler EB catalog does).
        header = ""
        for raw_line in sample.split(b"\n")[:60]:
            line = raw_line.decode("utf-8", "replace").strip()
            if line and not line.startswith("#"):
                header = line
                break
        if not header:
            return False, "no header row found before end of sample"
        delimiter, count = max(
            ((d, header.count(d)) for d in (",", ";", "\t", "|")), key=lambda pair: pair[1]
        )
        if count < 1:
            return False, f"no delimiter in header row: {header[:60]!r}"
        label = {",": "comma", ";": "semicolon", "\t": "tab", "|": "pipe"}[delimiter]
        return True, f"{label}-delimited header with {count + 1} columns"

    if kind == "xml":
        if head == b"<":
            return True, "XML prefix ok"
        return False, f"not XML, starts with {text_head[:60]!r}"

    if kind == "tle":
        lines = [ln for ln in sample.split(b"\n") if ln.strip()]
        if any(_TLE_LINE.match(ln) for ln in lines[:6]):
            return True, "TLE element lines present"
        return False, f"no TLE lines in body: {text_head[:60]!r}"

    if kind == "html":
        lowered = sample[:2000].lower()
        if b"<html" in lowered or b"<!doctype" in lowered or b"<table" in lowered:
            return True, "HTML markup present"
        return False, f"no HTML markup: {text_head[:60]!r}"

    if kind == "text":
        if b"\x00" in sample[:1024]:
            return False, "binary content where text was expected"
        return True, f"{len(sample)} bytes of text"

    return None, "no content expectation for this URL"


def _canonical_host(host: str) -> str:
    """Normalise a host for comparison: only a leading `www.` is ignored.

    Deliberately *not* reduced to the registrable domain. The
    nssdc_planetary_factsheet case redirects nssdc.gsfc.nasa.gov ->
    www.nasa.gov, which a registrable-domain comparison ("nasa.gov" both
    sides) would wave through — and that redirect is exactly the failure we
    need to catch.
    """
    host = host.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _redirect_lost_the_path(requested: str, final: str) -> bool:
    """True when a redirect dropped the path we asked for.

    Landing-page redirects keep the host but throw away the path
    (/planetary/factsheet/ -> /nssdc/). A redirect that only adds a
    trailing slash, a subpath, or a query string is fine.
    """
    requested_path = urlparse(requested).path.rstrip("/")
    final_path = urlparse(final).path.rstrip("/")
    if not requested_path or requested_path == final_path:
        return False
    return not final_path.startswith(requested_path)


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------
async def check_link(
    client: httpx.AsyncClient,
    key: str,
    target: DownloadTarget,
    timeout: float = 45.0,
    retries: int = 2,
) -> LinkResult:
    """Check one link, retrying transient 5xx/transport failures once.

    TAP servers (VizieR especially) answer 500 under load for queries that
    work fine seconds later; one retry keeps the report about real breakage.
    """
    result = await _check_link_once(client, key, target, timeout)
    first_detail = ""
    for attempt in range(retries):
        transient = (
            (result.http_status is None and not result.ok)
            or (result.http_status is not None and result.http_status >= 500)
            or result.server_side_failure
        )
        if not transient:
            break
        await asyncio.sleep(3 * (attempt + 1))
        first_detail = first_detail or result.detail
        retry_result = await _check_link_once(client, key, target, timeout)
        attempts = attempt + 1
        plural = "retry" if attempts == 1 else "retries"
        if retry_result.works:
            retry_result.detail = (
                f"{retry_result.detail} (recovered after {attempts} {plural}; "
                f"first try: {first_detail})"
            )
        else:
            retry_result.detail = (
                f"{retry_result.detail} (still failing after {attempts} {plural}; "
                f"first try: {first_detail})"
            )
        result = retry_result
    return result


async def _check_link_once(
    client: httpx.AsyncClient, key: str, target: DownloadTarget, timeout: float = 45.0
) -> LinkResult:
    url = _check_url_for(target)
    result = LinkResult(
        key=key,
        method=target.method,
        url=target.resolved_url,
        checked_url=url,
        expected_kind=expected_kind_for(url, target.media_type),
    )
    started = asyncio.get_event_loop().time()
    headers = {"Range": f"bytes=0-{SAMPLE_BYTES - 1}"}
    headers.update(target.headers)
    # Use the target's real method. GETting a POST-only search form (the USGS
    # Gazetteer) gets a 500 that says nothing about the link. The one method
    # we never replay is Space-Track's login POST — that is credentialed and
    # is checked through its query endpoints answering 401 instead.
    stream_kwargs: dict = {"timeout": timeout, "headers": headers}
    if target.method == "POST" and target.data:
        stream_kwargs["data"] = dict(target.data)
    try:
        async with client.stream(target.method, url, **stream_kwargs) as response:
            result.http_status = response.status_code
            result.ok = response.status_code < 400
            result.final_url = str(response.url)
            result.content_type = response.headers.get("content-type")
            declared_length = response.headers.get("content-range") or response.headers.get(
                "content-length"
            )
            if declared_length:
                total = declared_length.split("/")[-1]
                result.content_length = int(total) if total.isdigit() else None

            sample = bytearray()
            async for chunk in response.aiter_bytes():
                sample.extend(chunk)
                if len(sample) >= SAMPLE_BYTES:
                    break
            complete = (
                response.status_code == 206
                or (result.content_length is not None and len(sample) >= result.content_length)
            ) and len(sample) < SAMPLE_BYTES

        result.elapsed_seconds = round(asyncio.get_event_loop().time() - started, 2)
        final_url = result.final_url or url
        requested_host = _canonical_host(urlparse(url).netloc)
        final_host = _canonical_host(urlparse(final_url).netloc)
        offsite = requested_host != final_host
        lost_path = _redirect_lost_the_path(url, final_url)
        result.redirected_offsite = offsite

        if result.http_status in AUTH_STATUSES:
            result.auth_required = True
            result.detail = f"HTTP {result.http_status} — endpoint alive, login required"
            return result
        if not result.ok:
            reason = server_error_message(bytes(sample))
            result.detail = f"HTTP {result.http_status}" + (f" — {reason}" if reason else "")
            result.server_side_failure = looks_server_side(result.detail, result.http_status)
            return result
        if offsite:
            result.detail = f"redirects off-site: {final_url}"
            return result

        result.content_ok, result.detail = sniff_content(
            result.expected_kind, bytes(sample), complete
        )
        if lost_path:
            # A permalink resolving to the real file (ucs.org/media/11492 ->
            # UCS-Satellite-Database.xlsx) is normal; a landing-page redirect
            # that also fails the content check is not.
            if result.content_ok is False:
                result.redirected_offsite = True
                result.detail = f"redirects to a different path: {final_url} — {result.detail}"
            else:
                result.detail = f"{result.detail} (redirected to {final_url})"
    except Exception as exc:  # noqa: BLE001 - any failure is a link-check finding
        result.elapsed_seconds = round(asyncio.get_event_loop().time() - started, 2)
        result.ok = False
        result.detail = f"{type(exc).__name__}: {exc}"
        result.server_side_failure = isinstance(exc, (httpx.TimeoutException, httpx.ConnectError))
    return result


#: Row caps injected when checking a target, so verifying a link never pulls
#: the whole catalogue behind it. Keyed by the query parameter the API uses.
_CHECK_CAPS = {"MAXREC": "5", "maxrec": "5", "limit": "5"}


def _check_url_for(target: DownloadTarget) -> str:
    """A deliberately tiny twin of `target`, for link-checking only."""
    params = dict(target.params)
    if not params:
        return target.url

    for key in ("query", "QUERY"):
        if key in params:
            # ADQL: a `top 5` costs the server almost nothing and proves the
            # table resolves, which is the thing that actually breaks.
            value = params[key]
            lowered = value.lstrip().lower()
            if lowered.startswith("select") and " top " not in lowered[:40]:
                params[key] = value.replace("select", "select top 5", 1)
    for cap, value in _CHECK_CAPS.items():
        if cap in params:
            params[cap] = value
    if "sb-class" in params:
        params["limit"] = "5"

    sep = "&" if "?" in target.url else "?"
    return f"{target.url}{sep}{urlencode(params)}"


def _requests_for(key: str) -> list[DownloadTarget]:
    links = LINKS.get(key)
    if links is not None and links.targets:
        return list(links.targets)
    if links is not None and links.landing_page:
        # Retired/credentialed sources with no target still have somewhere
        # worth pinging, so the report can say "alive but gated" rather than
        # staying silent about them.
        return [DownloadTarget(filename="landing", url=links.landing_page)]
    spec = SOURCES[key]
    return [DownloadTarget(filename="probe", url=spec.probe_url, method=spec.probe_method)]


def _verdict_for(report: SourceReport) -> tuple[str, str]:
    broken = [link for link in report.links if not link.works]
    links = LINKS.get(report.key)

    if links is not None and links.status is LinkStatus.RETIRED:
        replacement = f" — use {links.replaced_by} instead" if links.replaced_by else ""
        return VERDICT_BROKEN, f"endpoint retired{replacement}"

    if report.requires_credentials or (
        links is not None and links.status is LinkStatus.CREDENTIALED
    ):
        reachable = any(link.ok or link.auth_required for link in report.links)
        if not reachable:
            return VERDICT_BROKEN, "endpoint unreachable"
        guarded = sum(1 for link in report.links if link.auth_required)
        note = f"{guarded} endpoint(s) behind the login wall, as expected" if guarded else ""
        if report.has_plan:
            return VERDICT_READY, f"credentials present, endpoint reachable; {note}".rstrip("; ")
        return (
            VERDICT_NEEDS_CREDENTIALS,
            f"endpoint reachable; set credentials to enable the download. {note}".strip(),
        )
    if not report.has_plan:
        if broken and all(link.server_side_failure for link in broken):
            return VERDICT_SUSPECT, f"server-side outage: {broken[0].detail}"
        if broken:
            return VERDICT_BROKEN, broken[0].detail
        reason = unfetchable_reason(report.key) or "no downloader"
        return VERDICT_NO_PLAN, f"endpoint reachable but not fetchable: {reason}"
    if not broken:
        return VERDICT_READY, f"{len(report.links)} link(s) verified"
    if all(link.server_side_failure for link in broken):
        return VERDICT_SUSPECT, (
            f"{len(broken)}/{len(report.links)} link(s) hit a server-side outage "
            f"(URL looks right, retry later): {broken[0].detail}"
        )
    if all(not link.ok for link in broken):
        return VERDICT_BROKEN, f"{len(broken)}/{len(report.links)} link(s) failed: {broken[0].detail}"
    return VERDICT_SUSPECT, f"{len(broken)}/{len(report.links)} link(s) suspect: {broken[0].detail}"


async def check_sources(
    keys: list[str] | None = None,
    *,
    concurrency: int = 4,
    progress: object = None,
) -> list[SourceReport]:
    """Check every declared download link for `keys` (default: all sources)."""
    keys = keys or sorted(SOURCES)
    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(
        headers={"User-Agent": settings.user_agent}, follow_redirects=True
    ) as client:

        async def check_source(key: str) -> SourceReport:
            spec = SOURCES[key]
            report = SourceReport(
                key=key,
                name=spec.name,
                tier=spec.tier,
                category=spec.category,
                requires_credentials=spec.requires_credentials,
                has_plan=DOWNLOAD_PLAN.get(key) is not None,
            )
            async with semaphore:
                for request in _requests_for(key):
                    report.links.append(await check_link(client, key, request))
            report.verdict, report.reason = _verdict_for(report)
            if progress is not None and callable(progress):
                progress(report)
            return report

        return list(await asyncio.gather(*(check_source(key) for key in keys)))


def report_path() -> "Path":
    from pathlib import Path

    return settings.catalog_dir / "link-check.json"


def write_report(reports: list[SourceReport]) -> "Path":
    """Persist the run to data/_catalog/link-check.json and return the path.

    Merges into any existing report rather than replacing it, so checking a
    single source (`astro links wds_catalog`) doesn't wipe out what we know
    about the other 45.
    """
    out_path = report_path()
    merged: dict[str, dict] = {}
    if out_path.exists():
        try:
            previous = json.loads(out_path.read_text())
            for entry in previous.get("sources", []):
                if entry.get("key"):
                    merged[entry["key"]] = entry
        except (json.JSONDecodeError, OSError):
            merged = {}

    checked_at = datetime.now(timezone.utc).isoformat()
    for report in reports:
        entry = asdict(report)
        entry["checked_at"] = checked_at
        merged[report.key] = entry

    payload = {
        "checked_at": checked_at,
        "checked_now": sorted(report.key for report in reports),
        "summary": summarize(reports),
        "sources": [merged[key] for key in sorted(merged)],
    }
    settings.catalog_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n")
    return out_path


def summarize(reports: list[SourceReport]) -> dict[str, int]:
    counts = {verdict: 0 for verdict in VERDICT_ORDER}
    for report in reports:
        counts[report.verdict] = counts.get(report.verdict, 0) + 1
    counts["links_checked"] = sum(len(report.links) for report in reports)
    counts["links_working"] = sum(report.working_links for report in reports)
    return counts
