"""Async HTTP client with per-domain rate limiting and retry with backoff.

Default policy: max 1 request/second per domain, exponential backoff retry
via tenacity, explicit User-Agent identifying this project and a contact
email (see core.config.settings).
"""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urlparse

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import settings


class DomainRateLimiter:
    """Serializes requests per-domain so we never exceed N req/s to any host."""

    def __init__(self, requests_per_second: float = 1.0):
        self.min_interval = 1.0 / requests_per_second
        self._last_request: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, domain: str) -> asyncio.Lock:
        lock = self._locks.get(domain)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[domain] = lock
        return lock

    async def wait(self, url: str) -> None:
        domain = urlparse(url).netloc
        lock = self._lock_for(domain)
        async with lock:
            now = time.monotonic()
            last = self._last_request.get(domain, 0.0)
            elapsed = now - last
            if elapsed < self.min_interval:
                await asyncio.sleep(self.min_interval - elapsed)
            self._last_request[domain] = time.monotonic()


rate_limiter = DomainRateLimiter(settings.requests_per_second_per_domain)


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": settings.user_agent},
        timeout=settings.request_timeout_seconds,
        follow_redirects=True,
    )


def _retrying(func):
    return retry(
        reraise=True,
        stop=stop_after_attempt(settings.max_retries),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    )(func)


@_retrying
async def get(
    client: httpx.AsyncClient, url: str, *, raise_for_status: bool = True, **kwargs
) -> httpx.Response:
    await rate_limiter.wait(url)
    response = await client.get(url, **kwargs)
    if raise_for_status:
        response.raise_for_status()
    return response


@_retrying
async def head(
    client: httpx.AsyncClient, url: str, *, raise_for_status: bool = True, **kwargs
) -> httpx.Response:
    await rate_limiter.wait(url)
    response = await client.head(url, **kwargs)
    if raise_for_status:
        response.raise_for_status()
    return response


@_retrying
async def post(
    client: httpx.AsyncClient, url: str, *, raise_for_status: bool = True, **kwargs
) -> httpx.Response:
    await rate_limiter.wait(url)
    response = await client.post(url, **kwargs)
    if raise_for_status:
        response.raise_for_status()
    return response
