"""Space-Track.org REST API client.

Implements https://www.space-track.org/documentation#/api as documented
(fetched and re-read 2026-08-21), including the parts of the guidelines
that are rules rather than suggestions:

* **Auth** — cookie session obtained by POSTing ``identity``/``password`` to
  ``/ajaxauth/login``; ``/ajaxauth/logout`` on the way out. Space-Track
  answers a successful login with a JSON-encoded empty string and a failed
  one with a JSON object (e.g. ``{"Login":"Failed"}``).

* **URL shape** — ``/{controller}/{action}/class/{class}/{predicate}/{value}/
  .../orderby/.../limit/.../format/...``. Controllers: ``basicspacedata``,
  ``expandedspacedata``, ``fileshare``, ``combinedopsdata``, ``publicfiles``.
  Actions: ``query`` and ``modeldef``.

* **Operators** — ``>`` ``<`` ``<>`` (percent-encoded), ``,`` for an OR list,
  ``--`` for an inclusive range, ``~~`` for "contains", ``^`` for
  "starts with", ``null-val`` for NULL, ``now-N`` for relative days
  (fractions allowed). Values are percent-encoded but those operator
  characters are deliberately left intact.

* **Throttling** — "Limit API queries to less than 30 requests per 1
  minute(s) and 300 requests per 1 hour(s)". Enforced client-side by
  :class:`SpaceTrackThrottle` (sliding windows), so we stop ourselves before
  Space-Track has to.

* **Per-class retrieval frequency** — the documentation's data-retrieval
  table (GP once/hour, SATCAT once/day after 1700 UTC, BOXSCORE once/day,
  DECAY once/day, TIP once/hour, CDM every 8 hours, GP_HISTORY once per
  lifetime, ...) is encoded in :data:`RETRIEVAL_POLICY` and enforced against
  an on-disk ledger, because violating it is the documented way to get an
  account suspended.

Nothing here fabricates data: every response is written to
``data/raw/spacetrack/`` exactly as received.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

import httpx

BASE_URL = "https://www.space-track.org"
LOGIN_URL = f"{BASE_URL}/ajaxauth/login"
LOGOUT_URL = f"{BASE_URL}/ajaxauth/logout"

CONTROLLERS = (
    "basicspacedata",
    "expandedspacedata",
    "fileshare",
    "combinedopsdata",
    "publicfiles",
)
ACTIONS = ("query", "modeldef")
FORMATS = ("json", "xml", "html", "csv", "tle", "3le", "kvn", "stream")

ENV_IDENTITY = "ASTRO_DL_SPACETRACK_USER"
ENV_PASSWORD = "ASTRO_DL_SPACETRACK_PASS"

#: Characters that carry meaning in a Space-Track predicate value and must
#: survive percent-encoding untouched.
_VALUE_SAFE = ",-~^*"


class SpaceTrackError(RuntimeError):
    """Any Space-Track-specific failure (auth, throttle, bad query)."""


class SpaceTrackAuthError(SpaceTrackError):
    """Login rejected, or the session expired mid-run."""


class SpaceTrackPolicyError(SpaceTrackError):
    """The request would violate the documented retrieval frequency."""


# ---------------------------------------------------------------------------
# Documented per-class retrieval frequency (API Use Guidelines table)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RetrievalRule:
    """One row of the documentation's data-retrieval-rate table."""

    min_interval_seconds: float
    description: str
    #: Docs say "once per day *after 1700 UTC*" for a few classes.
    not_before_utc_hour: int | None = None
    #: "1 / lifetime" classes: download once, then keep it on your own disk.
    once_per_lifetime: bool = False


_HOUR = 3600.0
_DAY = 24 * _HOUR

RETRIEVAL_POLICY: dict[str, RetrievalRule] = {
    "gp": RetrievalRule(_HOUR, "GP (aka TLEs): once every hour"),
    "gp_history": RetrievalRule(
        _DAY,
        "GP_HISTORY: 1/lifetime — store what you download, do not re-download",
        once_per_lifetime=True,
    ),
    "satcat": RetrievalRule(_DAY, "SATCAT: once per day after 1700 UTC", not_before_utc_hour=17),
    "satcat_debut": RetrievalRule(
        _DAY, "SATCAT_DEBUT: once per day after 1700 UTC", not_before_utc_hour=17
    ),
    "satcat_change": RetrievalRule(_DAY, "SATCAT_CHANGE: once per day"),
    "boxscore": RetrievalRule(_DAY, "BOXSCORE: once per day after 1700 UTC", not_before_utc_hour=17),
    "decay": RetrievalRule(_DAY, "DECAY: once per day"),
    "tip": RetrievalRule(_HOUR, "TIP: once per hour"),
    "cdm_public": RetrievalRule(8 * _HOUR, "CDM: once every 8 hours"),
    "launch_site": RetrievalRule(_DAY, "Reference data: no more than daily"),
    "announcement": RetrievalRule(_DAY, "Reference data: no more than daily"),
    "car": RetrievalRule(_DAY, "Reference data: no more than daily"),
}

#: Fallback for classes with no explicit row in the table.
DEFAULT_RULE = RetrievalRule(_HOUR, "Unlisted class: self-imposed 1/hour floor")


# ---------------------------------------------------------------------------
# Query building
# ---------------------------------------------------------------------------
def encode_value(value: Any) -> str:
    """Percent-encode a predicate value, keeping Space-Track operators intact.

    ``>`` / ``<`` / spaces / ``/`` are encoded (the docs' own examples use
    ``%3E`` and ``%3C``); ``,`` ``--`` ``~~`` ``^`` ``*`` are not, because
    Space-Track parses them as operators.
    """
    from urllib.parse import quote

    return quote(str(value), safe=_VALUE_SAFE)


@dataclass
class Query:
    """One Space-Track REST request, rendered to a URL by :meth:`url`."""

    class_name: str
    controller: str = "basicspacedata"
    action: str = "query"
    #: Ordered predicate filters, e.g. ``{"decay_date": "null-val"}``.
    predicates: dict[str, Any] = field(default_factory=dict)
    orderby: str | None = None
    limit: int | None = None
    offset: int | None = None
    #: Restrict returned columns (``/predicates/a,b,c/``).
    columns: Iterable[str] | None = None
    response_format: str = "json"
    distinct: bool = False
    metadata: bool = False
    #: ``/emptyresult/show/`` — return 200 + empty body instead of an error.
    show_empty_result: bool = True

    def __post_init__(self) -> None:
        if self.controller not in CONTROLLERS:
            raise ValueError(f"Unknown controller {self.controller!r}; expected one of {CONTROLLERS}")
        if self.action not in ACTIONS:
            raise ValueError(f"Unknown action {self.action!r}; expected one of {ACTIONS}")
        if self.response_format not in FORMATS:
            raise ValueError(
                f"Unknown format {self.response_format!r}; expected one of {FORMATS}"
            )
        if self.limit is not None and self.limit <= 0:
            raise ValueError("limit must be positive")

    def path(self) -> str:
        parts = [self.controller, self.action, "class", self.class_name.lower()]
        if self.action == "modeldef":
            return "/" + "/".join(parts)

        for predicate, value in self.predicates.items():
            parts += [predicate, encode_value(value)]
        if self.columns:
            parts += ["predicates", encode_value(",".join(self.columns))]
        if self.orderby:
            parts += ["orderby", encode_value(self.orderby)]
        if self.limit is not None:
            limit_value = f"{self.limit},{self.offset}" if self.offset else str(self.limit)
            parts += ["limit", limit_value]
        if self.distinct:
            parts += ["distinct", "true"]
        if self.metadata:
            parts += ["metadata", "true"]
        if self.show_empty_result:
            parts += ["emptyresult", "show"]
        parts += ["format", self.response_format]
        return "/" + "/".join(parts)

    def url(self, base_url: str = BASE_URL) -> str:
        return base_url.rstrip("/") + self.path()

    def suggested_filename(self) -> str:
        stem = f"{self.class_name.lower()}"
        if self.action == "modeldef":
            stem += "-modeldef"
        extension = {"3le": "txt", "tle": "txt", "kvn": "txt", "stream": "json"}.get(
            self.response_format, self.response_format
        )
        return f"{stem}.{extension}"


# ---------------------------------------------------------------------------
# Canonical queries straight out of the documentation
# ---------------------------------------------------------------------------
def gp_current(response_format: str = "json") -> Query:
    """Current propagable ephemerides for on-orbit objects.

    The docs' recommended GP query: *"Add ``/decay_date/null-val/epoch/
    %3Enow-10/`` to the URL to ensure that you only retrieve propagable
    ephemerides for on-orbit objects."*
    """
    return Query(
        class_name="gp",
        predicates={"decay_date": "null-val", "epoch": ">now-10"},
        orderby="norad_cat_id",
        response_format=response_format,
    )


def gp_for_objects(norad_ids: Iterable[int | str], response_format: str = "json") -> Query:
    """Newest elset for specific objects, as one comma-delimited request.

    The docs are explicit that this is the right shape: *"Do not send
    hundreds of individual /class/gp/ queries ... combining queries for
    multiple objects using a comma-delimited list."*
    """
    ids = ",".join(str(i) for i in norad_ids)
    if not ids:
        raise ValueError("norad_ids is empty")
    return Query(
        class_name="gp",
        predicates={"norad_cat_id": ids},
        orderby="norad_cat_id",
        response_format=response_format,
    )


def satcat_current(response_format: str = "json") -> Query:
    """Full satellite catalogue, on-orbit and decayed."""
    return Query(
        class_name="satcat",
        orderby="norad_cat_id",
        response_format=response_format,
    )


def satcat_debut_since_yesterday() -> Query:
    """Objects added to the catalogue since yesterday (docs' daily pattern)."""
    return Query(
        class_name="satcat_debut",
        predicates={"DEBUT": ">now-1"},
        orderby="norad_cat_id",
    )


def decay_recent() -> Query:
    """Current decay messages only — the docs' ``/MSG_EPOCH/%3Enow-1/`` pattern."""
    return Query(
        class_name="decay",
        predicates={"MSG_EPOCH": ">now-1"},
        orderby="norad_cat_id",
    )


def boxscore() -> Query:
    """Per-country object counts."""
    return Query(class_name="boxscore", response_format="json")


def launch_sites() -> Query:
    return Query(class_name="launch_site", response_format="json")


def tip_recent() -> Query:
    """Tracking and Impact Prediction messages since the last hourly check."""
    return Query(
        class_name="tip",
        predicates={"INSERT_EPOCH": ">now-0.042"},
        orderby="norad_cat_id",
    )


def cdm_public() -> Query:
    """Public conjunction data messages."""
    return Query(class_name="cdm_public", orderby="TCA", response_format="json")


#: Named, ready-to-run queries surfaced in the CLI and TUI.
PRESETS: dict[str, tuple[str, Any]] = {
    "gp": ("Current GP/TLE for on-orbit objects (decay_date null, epoch > now-10)", gp_current),
    "satcat": ("Full SATCAT (all objects, incl. decayed)", satcat_current),
    "satcat_debut": ("Objects added to SATCAT since yesterday", satcat_debut_since_yesterday),
    "decay": ("Decay messages from the last day", decay_recent),
    "boxscore": ("Box score: object counts per country", boxscore),
    "launch_site": ("Launch site reference table", launch_sites),
    "tip": ("Tracking & Impact Prediction messages (last hour)", tip_recent),
    "cdm_public": ("Public conjunction data messages", cdm_public),
}


# ---------------------------------------------------------------------------
# Throttling
# ---------------------------------------------------------------------------
class SpaceTrackThrottle:
    """Client-side enforcement of "<30 requests/minute and <300/hour"."""

    def __init__(
        self,
        per_minute: int = 25,
        per_hour: int = 275,
        min_interval_seconds: float = 2.0,
    ):
        # Deliberately under the documented ceilings (30/min, 300/hour) so a
        # clock skew between us and Space-Track can't push us over.
        self.per_minute = per_minute
        self.per_hour = per_hour
        self.min_interval_seconds = min_interval_seconds
        self._events: deque[float] = deque()
        self._lock = asyncio.Lock()
        self._last: float = 0.0

    def _prune(self, now: float) -> None:
        while self._events and now - self._events[0] > 3600:
            self._events.popleft()

    def _wait_needed(self, now: float) -> float:
        self._prune(now)
        waits = [self.min_interval_seconds - (now - self._last)] if self._last else [0.0]
        minute_events = [t for t in self._events if now - t <= 60]
        if len(minute_events) >= self.per_minute:
            waits.append(60 - (now - minute_events[-self.per_minute]))
        if len(self._events) >= self.per_hour:
            waits.append(3600 - (now - self._events[-self.per_hour]))
        return max([w for w in waits] + [0.0])

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                wait = self._wait_needed(now)
                if wait <= 0:
                    break
                await asyncio.sleep(wait)
            now = time.monotonic()
            self._events.append(now)
            self._last = now

    @property
    def used_last_minute(self) -> int:
        now = time.monotonic()
        return sum(1 for t in self._events if now - t <= 60)

    @property
    def used_last_hour(self) -> int:
        now = time.monotonic()
        self._prune(now)
        return len(self._events)


# ---------------------------------------------------------------------------
# Retrieval-frequency ledger
# ---------------------------------------------------------------------------
class RetrievalLedger:
    """Remembers when each class was last pulled, so the docs' rates hold.

    Stored as JSON next to the raw data; losing it only costs us an extra
    (still throttled) request, never data.
    """

    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, dict[str, Any]] = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def last_pull(self, class_name: str) -> datetime | None:
        entry = self._data.get(class_name.lower())
        if not entry or not entry.get("retrieved_at"):
            return None
        try:
            return datetime.fromisoformat(entry["retrieved_at"])
        except ValueError:
            return None

    def record(self, class_name: str, url: str, bytes_written: int) -> None:
        self._data[class_name.lower()] = {
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "url": url,
            "bytes": bytes_written,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2, sort_keys=True) + "\n")

    def check(self, class_name: str, *, now: datetime | None = None) -> tuple[bool, str]:
        """Return ``(allowed, reason)`` for pulling ``class_name`` right now."""
        rule = RETRIEVAL_POLICY.get(class_name.lower(), DEFAULT_RULE)
        now = now or datetime.now(timezone.utc)
        last = self.last_pull(class_name)

        if last is not None and rule.once_per_lifetime:
            return False, (
                f"{class_name}: documented as 1/lifetime ({rule.description}); already "
                f"retrieved {last.isoformat()} — reuse the stored copy"
            )
        if last is not None:
            elapsed = (now - last).total_seconds()
            if elapsed < rule.min_interval_seconds:
                remaining = rule.min_interval_seconds - elapsed
                return False, (
                    f"{class_name}: {rule.description}; last pull was "
                    f"{elapsed / 60:.0f} min ago, wait {remaining / 60:.0f} more min"
                )
        if rule.not_before_utc_hour is not None and now.hour < rule.not_before_utc_hour:
            return False, (
                f"{class_name}: {rule.description}; it is {now:%H:%M} UTC, data is "
                f"published after {rule.not_before_utc_hour:02d}00 UTC"
            )
        return True, f"{class_name}: allowed ({rule.description})"


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
def class_name_from_url(url: str) -> str:
    """Pull the API class out of a Space-Track query URL.

    `.../basicspacedata/query/class/gp/orderby/.../format/json` -> `gp`.
    Lets the retrieval-rate ledger work off the URLs in sources/links.py
    without those URLs having to be rebuilt as Query objects.
    """
    parts = [segment for segment in urlparse(url).path.split("/") if segment]
    if "class" in parts:
        index = parts.index("class")
        if index + 1 < len(parts):
            return parts[index + 1].lower()
    return "unknown"


def credentials_from_env() -> tuple[str, str] | None:
    identity = os.environ.get(ENV_IDENTITY)
    password = os.environ.get(ENV_PASSWORD)
    if identity and password:
        return identity, password
    return None


class SpaceTrackClient:
    """Async Space-Track client: one login, many throttled queries, one logout."""

    def __init__(
        self,
        identity: str,
        password: str,
        *,
        client: httpx.AsyncClient | None = None,
        throttle: SpaceTrackThrottle | None = None,
        base_url: str = BASE_URL,
        timeout: float = 300.0,
        user_agent: str | None = None,
    ):
        if not identity or not password:
            raise SpaceTrackAuthError(
                f"Space-Track needs credentials: set {ENV_IDENTITY} and {ENV_PASSWORD}"
            )
        self.identity = identity
        self.password = password
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.throttle = throttle or SpaceTrackThrottle()
        headers = {"User-Agent": user_agent} if user_agent else {}
        self._client = client or httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers=headers
        )
        self._owns_client = client is None
        self._logged_in = False

    # -- session ---------------------------------------------------------
    async def login(self) -> None:
        if self._logged_in:
            return
        await self.throttle.acquire()
        response = await self._client.post(
            LOGIN_URL,
            data={"identity": self.identity, "password": self.password},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise SpaceTrackAuthError(
                f"Space-Track login returned HTTP {response.status_code}: "
                f"{response.text[:200]!r}"
            )
        # Success is a JSON-encoded empty string; failure is a JSON object
        # such as {"Login":"Failed"}.
        try:
            body = response.json()
        except ValueError:
            body = response.text.strip()
        if body:
            raise SpaceTrackAuthError(f"Space-Track login failed: {body!r}")
        if "chocolatechip" not in self._client.cookies:
            raise SpaceTrackAuthError(
                "Space-Track login returned success but set no session cookie"
            )
        self._logged_in = True

    async def logout(self) -> None:
        if not self._logged_in:
            return
        try:
            await self.throttle.acquire()
            await self._client.get(LOGOUT_URL, timeout=30.0)
        except httpx.HTTPError:
            pass  # logging out is courtesy; a failure here must not mask real errors
        finally:
            self._logged_in = False

    async def aclose(self) -> None:
        await self.logout()
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "SpaceTrackClient":
        await self.login()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # -- requests --------------------------------------------------------
    async def _request(self, url: str, *, attempts: int = 4) -> httpx.Response:
        last_error: str = ""
        for attempt in range(1, attempts + 1):
            await self.throttle.acquire()
            try:
                response = await self._client.get(url, timeout=self.timeout)
            except httpx.TransportError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt == attempts:
                    raise SpaceTrackError(f"Space-Track request failed: {last_error}") from exc
                await asyncio.sleep(min(2**attempt, 30))
                continue

            if response.status_code == 401:
                raise SpaceTrackAuthError(
                    "Space-Track rejected the session (HTTP 401) — credentials wrong "
                    "or the session expired"
                )
            if response.status_code == 429 or response.status_code == 503:
                retry_after = float(response.headers.get("Retry-After", 60) or 60)
                last_error = f"HTTP {response.status_code} (throttled)"
                if attempt == attempts:
                    break
                await asyncio.sleep(min(retry_after, 300))
                continue
            if response.status_code >= 400:
                raise SpaceTrackError(
                    f"Space-Track returned HTTP {response.status_code} for {url}: "
                    f"{response.text[:300]!r}"
                )
            return response
        raise SpaceTrackError(f"Space-Track request gave up after {attempts} attempts: {last_error}")

    async def query(self, spec: Query) -> httpx.Response:
        await self.login()
        return await self._request(spec.url(self.base_url))

    async def request_url(self, url: str, *, timeout: float | None = None) -> httpx.Response:
        """Fetch an already-built Space-Track URL through the same session.

        Used for the URLs that live in sources/links.py, so they still get
        the login, the throttle and the error handling without being
        round-tripped through Query.
        """
        await self.login()
        if timeout is not None:
            previous, self.timeout = self.timeout, timeout
            try:
                return await self._request(url)
            finally:
                self.timeout = previous
        return await self._request(url)

    async def query_json(self, spec: Query) -> Any:
        if spec.response_format != "json":
            raise ValueError("query_json requires response_format='json'")
        response = await self.query(spec)
        if not response.content.strip():
            return []
        return response.json()

    async def modeldef(self, class_name: str, controller: str = "basicspacedata") -> Any:
        """Fetch a class's predicate definitions (``/modeldef/class/<class>``)."""
        spec = Query(class_name=class_name, controller=controller, action="modeldef")
        response = await self.query(spec)
        payload = response.json()
        return payload.get("data", payload) if isinstance(payload, dict) else payload


async def fetch_queries(
    queries: Mapping[str, Query],
    *,
    identity: str | None = None,
    password: str | None = None,
    user_agent: str | None = None,
) -> list[tuple[str, bytes]]:
    """Run several queries on one login, returning ``(filename, bytes)`` pairs."""
    if identity is None or password is None:
        creds = credentials_from_env()
        if creds is None:
            raise SpaceTrackAuthError(
                f"Space-Track credentials missing: set {ENV_IDENTITY} and {ENV_PASSWORD}"
            )
        identity, password = creds

    results: list[tuple[str, bytes]] = []
    async with SpaceTrackClient(identity, password, user_agent=user_agent) as client:
        for filename, spec in queries.items():
            response = await client.query(spec)
            results.append((filename, response.content))
    return results
