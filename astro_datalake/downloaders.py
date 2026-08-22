"""Per-source downloaders, generated from the link registry.

Every concrete URL now lives in `sources/links.py` as data. This module turns
those `DownloadTarget`s into async fetchers and holds the only two things that
genuinely need code rather than data:

  - Space-Track's login flow (POST credentials, reuse the session cookie), and
  - the skip/report decision for sources that are RETIRED or CREDENTIALED
    without credentials present.

`DOWNLOAD_PLAN` keeps its old shape — {source_key: Fetcher | None} — so
`astro pull` did not need to change. `None` still means "deliberately not
fetchable", and `unfetchable_reason()` explains why for any given key.
"""

from __future__ import annotations

import os
from typing import Awaitable, Callable

import httpx

import logging

from .core.config import settings
from .core.http import get, post
from .sources import spacetrack
from .sources.links import (
    LINKS,
    DownloadTarget,
    LinkStatus,
    SourceLinks,
)


LOGGER = logging.getLogger("astro_datalake.downloaders")


class TruncatedResultError(RuntimeError):
    """A TAP result came back sitting exactly on its row limit."""

Fetcher = Callable[[httpx.AsyncClient], Awaitable[list[tuple[str, bytes]]]]


async def fetch_target(
    client: httpx.AsyncClient,
    target: DownloadTarget,
    *,
    cookies: httpx.Cookies | None = None,
) -> tuple[str, bytes]:
    """Fetch exactly one target. Honours method, params, form body and headers."""
    kwargs: dict = {"timeout": target.timeout}
    if target.headers:
        kwargs["headers"] = dict(target.headers)
    if cookies is not None:
        kwargs["cookies"] = cookies

    if target.method == "POST":
        if target.params:
            kwargs["params"] = dict(target.params)
        response = await post(client, target.url, data=dict(target.data), **kwargs)
    else:
        if target.params:
            kwargs["params"] = dict(target.params)
        response = await get(client, target.url, **kwargs)
    content = response.content
    _reject_truncated(target, content)
    return target.filename, content


def _reject_truncated(target: DownloadTarget, content: bytes) -> None:
    """Refuse a TAP result that is sitting exactly on MAXREC.

    TAP servers silently clip at their own default and hand back a perfectly
    well-formed CSV — SIMBAD's default is 50000 rows, and a `V < 10` join that
    genuinely matches 362,857 rows returns exactly 50,000 of them with no
    warning anywhere in the response. Caching that would ship a half catalogue
    that looks complete, so every TAP target sends MAXREC explicitly and a
    result that lands on the limit is an error, not data.
    """
    if target.maxrec is None:
        return
    rows = max(content.count(b"\n") - 1, 0)  # minus the CSV header
    if rows >= target.maxrec:
        raise TruncatedResultError(
            f"{target.filename}: {rows} rows == MAXREC ({target.maxrec}); the result was "
            "clipped. Raise maxrec on this target or split the query — do not cache a "
            "partial catalogue."
        )


def _plain_fetcher(links: SourceLinks) -> Fetcher:
    async def fetch(client: httpx.AsyncClient) -> list[tuple[str, bytes]]:
        results = []
        for target in links.targets:
            results.append(await fetch_target(client, target))
        return results

    return fetch


def _spacetrack_fetcher(links: SourceLinks) -> Fetcher:
    """Pull Space-Track's targets over one throttled, policy-checked session.

    The URLs still come from `sources/links.py` like every other source; what
    this adds is the part of https://www.space-track.org/documentation#/api
    that is a rule rather than a URL — see `sources/spacetrack.py`:

      * one login, one logout, session cookie verified;
      * client-side throttling below the documented 30/minute and 300/hour;
      * the per-class retrieval-frequency table, checked against an on-disk
        ledger, so a class pulled too recently is skipped with a reason
        instead of re-requested. Exceeding those rates is the documented way
        to get an account suspended.
    """

    async def fetch(client: httpx.AsyncClient) -> list[tuple[str, bytes]]:
        user, password = settings.spacetrack_user, settings.spacetrack_password
        if not user or not password:
            raise RuntimeError(
                f"Space-Track needs {spacetrack.ENV_IDENTITY} and "
                f"{spacetrack.ENV_PASSWORD} to be set."
            )

        ledger = spacetrack.RetrievalLedger(
            settings.raw_dir / "spacetrack" / "retrieval-ledger.json"
        )
        due: list[DownloadTarget] = []
        for target in links.targets:
            class_name = spacetrack.class_name_from_url(target.url)
            allowed, reason = ledger.check(class_name)
            if allowed:
                due.append(target)
            else:
                LOGGER.info("Space-Track: skipping per documented retrieval rate — %s", reason)
        if not due:
            return []

        session = spacetrack.SpaceTrackClient(
            user,
            password,
            client=client,
            user_agent=settings.user_agent,
        )
        results: list[tuple[str, bytes]] = []
        try:
            await session.login()
            for target in due:
                LOGGER.info("Space-Track GET %s", target.resolved_url)
                response = await session.request_url(target.resolved_url, timeout=target.timeout)
                content = response.content
                _reject_truncated(target, content)
                results.append((target.filename, content))
                ledger.record(
                    spacetrack.class_name_from_url(target.url),
                    target.resolved_url,
                    len(content),
                )
        finally:
            await session.logout()
        return results

    return fetch


_SPECIAL_FETCHERS: dict[str, Callable[[SourceLinks], Fetcher]] = {
    "spacetrack": _spacetrack_fetcher,
}


def _build_fetcher(key: str, links: SourceLinks) -> Fetcher | None:
    if links.status is LinkStatus.RETIRED:
        return None
    if links.status is LinkStatus.CREDENTIALED:
        builder = _SPECIAL_FETCHERS.get(key)
        if builder is None:
            return None
        if not all(_credential_present(name) for name in links.credential_env):
            return None
        return builder(links)
    if not links.targets:
        return None
    builder = _SPECIAL_FETCHERS.get(key)
    return builder(links) if builder else _plain_fetcher(links)


def _credential_present(env_name: str) -> bool:
    mapping = {
        "ASTRO_DL_SPACETRACK_USER": settings.spacetrack_user,
        "ASTRO_DL_SPACETRACK_PASS": settings.spacetrack_password,
    }
    if env_name in mapping:
        return bool(mapping[env_name])
    return bool(os.environ.get(env_name))


def unfetchable_reason(key: str) -> str | None:
    """Why `DOWNLOAD_PLAN[key]` is None, phrased for the CLI. None if fetchable."""
    links = LINKS.get(key)
    if links is None:
        return "no entry in sources/links.py"
    if links.status is LinkStatus.RETIRED:
        replacement = f" — use {links.replaced_by} instead" if links.replaced_by else ""
        return f"endpoint retired{replacement}"
    if links.status is LinkStatus.CREDENTIALED:
        missing = [n for n in links.credential_env if not _credential_present(n)]
        if missing:
            return f"needs credentials: {', '.join(missing)}"
    if not links.targets:
        return "no download targets defined"
    return None


DOWNLOAD_PLAN: dict[str, Fetcher | None] = {
    key: _build_fetcher(key, links) for key, links in LINKS.items()
}
