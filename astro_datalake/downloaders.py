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

from .core.config import settings
from .core.http import get, post
from .sources.links import (
    LINKS,
    SPACETRACK_LOGIN,
    DownloadTarget,
    LinkStatus,
    SourceLinks,
)

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
    return target.filename, response.content


def _plain_fetcher(links: SourceLinks) -> Fetcher:
    async def fetch(client: httpx.AsyncClient) -> list[tuple[str, bytes]]:
        results = []
        for target in links.targets:
            results.append(await fetch_target(client, target))
        return results

    return fetch


def _spacetrack_fetcher(links: SourceLinks) -> Fetcher:
    """Log in once, then pull each query URL with the resulting session cookie."""

    async def fetch(client: httpx.AsyncClient) -> list[tuple[str, bytes]]:
        user, password = settings.spacetrack_user, settings.spacetrack_password
        if not user or not password:
            raise RuntimeError(
                "Space-Track needs ASTRO_DL_SPACETRACK_USER and "
                "ASTRO_DL_SPACETRACK_PASS to be set."
            )
        login = await post(
            client,
            SPACETRACK_LOGIN,
            data={"identity": user, "password": password},
            timeout=60.0,
        )
        cookies = login.cookies
        if not cookies:
            raise RuntimeError(
                "Space-Track login returned no session cookie — check the credentials."
            )
        results = []
        for target in links.targets:
            results.append(await fetch_target(client, target, cookies=cookies))
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
