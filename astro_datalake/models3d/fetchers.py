"""Stream fetchers for the models_3d sources.

Signature: `async def fetch(client, dest: Path) -> StreamReport`, where `dest`
is data/raw/<key>/<YYYY-MM-DD>/. Each fetcher writes files (plus .sha256
sidecars) itself and returns what it did; `astro pull` only reports.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from typing import Awaitable, Callable, Iterable
from urllib.parse import urljoin, urlparse

import httpx

from ..core.cache import sha256_of_file, sidecar_path
from ..core.http import get
from ..core.naming import slugify
from . import sbn
from .stream import (
    StreamReport,
    TooLarge,
    filename_from_url,
    human_bytes,
    stream_download,
    write_manifest,
)

StreamFetcher = Callable[[httpx.AsyncClient, Path], Awaitable[StreamReport]]

# Anything a mesh/texture pipeline can actually open. Kept explicit so a page
# scrape can't drag in PDFs, videos or the whole NASA web template.
MESH_EXTENSIONS = {
    ".obj", ".stl", ".glb", ".gltf", ".fbx", ".dae", ".3ds", ".blend", ".lwo",
    ".wrl", ".x3d", ".ply", ".usdz", ".bds", ".dsk", ".tab", ".icq", ".7z",
}
TEXTURE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".webp"}


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name in {"href", "src", "data-src", "content"} and value:
                self.links.append(value)


def extract_links(html: str, base_url: str) -> list[str]:
    parser = _LinkParser()
    parser.feed(html)
    return [urljoin(base_url, link) for link in parser.links]


def asset_links(html: str, base_url: str, extensions: Iterable[str]) -> list[str]:
    wanted = {e.lower() for e in extensions}
    out = []
    for link in extract_links(html, base_url):
        path = urlparse(link).path.lower()
        suffix = Path(path).suffix
        if suffix in wanted and link not in out:
            out.append(link)
    return out


async def _fetch_file(
    client: httpx.AsyncClient,
    url: str,
    dest: Path,
    report: StreamReport,
    *,
    max_bytes: int | None = None,
    expect_binary: bool = True,
    fallbacks: list[str] | None = None,
    extra: dict | None = None,
) -> None:
    """Download one asset, updating `report` with the outcome either way.

    `fallbacks` are alternative URLs for the same file, tried in order when the
    first one 404s or answers with an HTML shell. Catalogs here link plenty of
    files against a base that no longer serves them while the file itself is
    still online elsewhere; the manifest records which URL actually served it.
    """
    candidates = [url, *(fallbacks or [])]
    failures: list[str] = []
    written = 0
    was_cached = False
    served_by = None

    for candidate in candidates:
        try:
            written, was_cached = await stream_download(client, candidate, dest, max_bytes=max_bytes)
        except TooLarge as exc:
            report.skipped.append(str(exc))
            return
        except (httpx.HTTPError, OSError) as exc:
            failures.append(f"{candidate}: {type(exc).__name__}: {exc}")
            continue

        if expect_binary and _looks_like_html(dest):
            dest.unlink(missing_ok=True)
            sidecar_path(dest).unlink(missing_ok=True)
            failures.append(f"{candidate}: server membalas HTML, bukan file biner (soft-404)")
            continue

        served_by = candidate
        break

    if served_by is None:
        report.errors.append(failures[0] if failures else f"{url}: tidak ada kandidat URL")
        return

    if served_by != url:
        report.skipped.append(f"{url}: tidak melayani file, dipakai fallback {served_by}")

    if was_cached:
        report.cached += 1
    else:
        report.downloaded += 1
        report.bytes_written += written
    assert report.root is not None
    entry = {"path": str(dest.relative_to(report.root)), "size": dest.stat().st_size,
             "sha256": sha256_of_file(dest), "source_url": served_by}
    if served_by != url:
        entry["url_in_catalog"] = url
    if extra:
        entry.update(extra)
    report.files.append(entry)


def _looks_like_html(path: Path) -> bool:
    """HTML where a mesh was asked for means the site soft-404'd.

    sbn.psi.edu answers a missing mesh with its single-page-app shell and a 200,
    so the status code alone can't tell a hit from a miss — the bytes can.
    """
    if path.suffix.lower() in {".html", ".htm", ".json", ".js", ".txt"}:
        return False
    with path.open("rb") as fh:
        head = fh.read(512).lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def _new_report(key: str, dest: Path) -> StreamReport:
    dest.mkdir(parents=True, exist_ok=True)
    return StreamReport(key=key, root=dest)


def _finish(report: StreamReport, dest: Path, source_url: str) -> StreamReport:
    write_manifest(dest, report, source_key=report.key, source_url=source_url)
    return report


# ---------------------------------------------------------------------------
# git-cloned asset repos (NASA 3D Resources)
# ---------------------------------------------------------------------------
def git_repo(key: str, repo_url: str, *, keep_git: bool = False) -> StreamFetcher:
    """Shallow-clone an asset repo into the raw dir and manifest every file.

    The clone is the raw artifact, so no per-file .sha256 sidecars are written
    (they would show up as untracked files in the checkout); the manifest holds
    the checksums instead, and `astro verify` reads it. `.git` is dropped after
    the commit id is recorded — it doubles the on-disk size and the working
    tree is what the build reads.
    """

    async def fetch(client: httpx.AsyncClient, dest: Path) -> StreamReport:
        report = _new_report(key, dest)
        name = repo_url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
        target = dest / name
        commit = None

        if not target.exists():
            dest.mkdir(parents=True, exist_ok=True)
            proc = await asyncio.to_thread(
                subprocess.run,
                ["git", "clone", "--depth", "1", repo_url, str(target)],
                capture_output=True, text=True, timeout=3600,
            )
            if proc.returncode != 0:
                report.errors.append(f"git clone gagal: {proc.stderr.strip()[:400]}")
                return _finish(report, dest, repo_url)

        git_dir = target / ".git"
        if git_dir.exists():
            rev = await asyncio.to_thread(
                subprocess.run, ["git", "-C", str(target), "rev-parse", "HEAD"],
                capture_output=True, text=True,
            )
            if rev.returncode == 0:
                commit = rev.stdout.strip()
            if not keep_git:
                shutil.rmtree(git_dir)

        for path in sorted(target.rglob("*")):
            if path.is_file():
                report.files.append({
                    "path": str(path.relative_to(dest)),
                    "size": path.stat().st_size,
                    "sha256": await asyncio.to_thread(sha256_of_file, path),
                    "source_url": repo_url,
                })
        report.downloaded = len(report.files)
        report.bytes_written = sum(f["size"] for f in report.files)
        report.extra["git_commit"] = commit
        report.extra["git_remote"] = repo_url
        return _finish(report, dest, repo_url)

    return fetch


# ---------------------------------------------------------------------------
# PDS SBN shape models
# ---------------------------------------------------------------------------
SBN_BASE = "https://sbn.psi.edu/pds/shape-models/"
# Relative links in app.Data.js ('shape-models/files/...') are written against
# /pds/, not against the page's own directory — resolving them against the page
# URL yields /pds/shape-models/shape-models/..., which the site answers with a
# 200 + HTML shell (verified 2026-08-21), not the mesh.
SBN_LINK_BASE = "https://sbn.psi.edu/pds/"


def sbn_shape_models(key: str = "pds_sbn_shape_models") -> StreamFetcher:
    async def fetch(client: httpx.AsyncClient, dest: Path) -> StreamReport:
        report = _new_report(key, dest)
        data_js = (await get(client, f"{SBN_BASE}js/app.Data.js", timeout=60)).text
        datasets_js = (await get(client, f"{SBN_BASE}js/app.Datasets.js", timeout=60)).text
        (dest / "_source").mkdir(parents=True, exist_ok=True)
        (dest / "_source" / "app.Data.js").write_text(data_js)
        (dest / "_source" / "app.Datasets.js").write_text(datasets_js)

        objects = sbn.parse_catalog(data_js, datasets_js)
        (dest / "catalog.json").write_text(json.dumps(objects, indent=2, ensure_ascii=False) + "\n")
        report.extra["object_count"] = len(objects)
        dir_hints = sbn.dataset_dir_hints(objects)

        for entry in objects:
            obj_slug = slugify(entry["name"]) or "unnamed"
            folder = dest / entry["type"] / obj_slug
            files = sbn.catalog_file_urls(entry, SBN_LINK_BASE, dir_hints)
            if not files:
                report.skipped.append(f"{entry['name']}: tidak ada file di katalog sumber")
                continue
            for spec in files:
                candidates = ([spec["url"]] if spec.get("url") else []) + spec["fallback_urls"]
                if not candidates:
                    report.skipped.append(
                        f"{entry['name']} ({spec['role']}): link rusak di sumber "
                        f"({spec.get('broken_upstream')}), tidak ada kandidat lain"
                    )
                    continue
                extra = {"object": entry["name"], "object_type": entry["type"],
                         "role": spec["role"], "format": spec["format"],
                         "dataset": spec.get("dataset_name")}
                if spec.get("broken_upstream"):
                    extra["broken_upstream"] = spec["broken_upstream"]
                await _fetch_file(
                    client, candidates[0], folder / filename_from_url(candidates[0]), report,
                    fallbacks=candidates[1:], extra=extra,
                )
        return _finish(report, dest, SBN_BASE)

    return fetch


# ---------------------------------------------------------------------------
# science.nasa.gov 3D Resources
# ---------------------------------------------------------------------------
NASA_SCIENCE_LIST = "https://science.nasa.gov/wp-json/smd/v1/content-list"
NASA_SCIENCE_ORG = 6504  # the "3D Resources" science-org term id used by the listing page


def nasa_science_3d(key: str = "nasa_science_3d", per_page: int = 50) -> StreamFetcher:
    async def fetch(client: httpx.AsyncClient, dest: Path) -> StreamReport:
        report = _new_report(key, dest)
        items: list[dict] = []
        page = 1
        while True:
            response = await get(client, NASA_SCIENCE_LIST, timeout=90, params={
                "science_org": NASA_SCIENCE_ORG, "number_of_items": per_page,
                "current_page": page, "post_types": "any", "orderby": "title",
                "order": "ASC", "response_format": "json",
            })
            payload = response.json().get("type", {})
            batch = payload.get("content") or []
            items.extend(batch)
            meta = payload.get("pagination_meta") or {}
            if page >= int(meta.get("total") or 1) or not batch:
                break
            page += 1

        (dest / "catalog.json").write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n")
        report.extra["item_count"] = len(items)

        for item in items:
            permalink = item.get("permalink")
            if not permalink:
                continue
            slug = slugify(item.get("title") or permalink.rstrip("/").rsplit("/", 1)[-1])
            folder = dest / "items" / slug
            folder.mkdir(parents=True, exist_ok=True)
            try:
                html = (await get(client, permalink, timeout=90)).text
            except httpx.HTTPError as exc:
                report.errors.append(f"{permalink}: {type(exc).__name__}: {exc}")
                continue
            (folder / "page.html").write_text(html)
            (folder / "item.json").write_text(json.dumps(item, indent=2, ensure_ascii=False) + "\n")

            links = [
                link for link in asset_links(html, permalink, MESH_EXTENSIONS)
                if "assets.science.nasa.gov" in link or "nasa.gov/wp-content" in link
            ]
            if not links:
                report.skipped.append(f"{slug}: halaman tidak memuat file model")
                continue
            for link in links:
                await _fetch_file(
                    client, link, folder / filename_from_url(link.split("?")[0]), report,
                    extra={"object": item.get("title"), "page": permalink},
                )
        return _finish(report, dest, "https://science.nasa.gov/3d-resources/")

    return fetch


# ---------------------------------------------------------------------------
# Single large archive (DAMIT)
# ---------------------------------------------------------------------------
def archive_file(key: str, url: str, fallback_name: str, *, max_bytes: int | None = None) -> StreamFetcher:
    async def fetch(client: httpx.AsyncClient, dest: Path) -> StreamReport:
        report = _new_report(key, dest)
        name = fallback_name
        try:  # the "latest" alias redirects to a dated filename worth keeping
            head = await client.head(url, follow_redirects=True, timeout=60)
            final = str(head.url)
            if Path(urlparse(final).path).suffix:
                name = filename_from_url(final)
        except httpx.HTTPError:
            pass
        await _fetch_file(client, url, dest / name, report, max_bytes=max_bytes)
        return _finish(report, dest, url)

    return fetch


# ---------------------------------------------------------------------------
# Texture pages (SVS API pages, Earth Observatory collections)
# ---------------------------------------------------------------------------
def svs_pages(key: str, page_ids: list[int], *, max_bytes: int) -> StreamFetcher:
    async def fetch(client: httpx.AsyncClient, dest: Path) -> StreamReport:
        report = _new_report(key, dest)
        for page_id in page_ids:
            api = f"https://svs.gsfc.nasa.gov/api/{page_id}/"
            try:
                payload = (await get(client, api, timeout=60)).json()
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                report.errors.append(f"{api}: {type(exc).__name__}: {exc}")
                continue
            title = payload.get("title") or str(page_id)
            folder = dest / f"{page_id}_{slugify(title)}"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "page.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

            urls: list[str] = []
            for group in payload.get("media_groups") or []:
                for item in group.get("items") or []:
                    instance = item.get("instance") or {}
                    url = instance.get("url")
                    if url and Path(urlparse(url).path).suffix.lower() in TEXTURE_EXTENSIONS:
                        if url not in urls:
                            urls.append(url)
            report.extra.setdefault("pages", {})[str(page_id)] = {"title": title, "files": len(urls)}
            for url in urls:
                await _fetch_file(
                    client, url, folder / filename_from_url(url), report,
                    max_bytes=max_bytes, extra={"page_title": title, "page": f"https://svs.gsfc.nasa.gov/{page_id}/"},
                )
        return _finish(report, dest, "https://svs.gsfc.nasa.gov/")

    return fetch


def page_textures(key: str, pages: dict[str, str], *, max_bytes: int,
                  host_filter: str | None = None, path_filter: str | None = None) -> StreamFetcher:
    """pages: {folder_slug: page_url} — crawl each page for texture-sized images.

    `host_filter`/`path_filter` keep the crawl to the page's own subject matter:
    a NASA article page also links site chrome and unrelated teaser images.
    """

    async def fetch(client: httpx.AsyncClient, dest: Path) -> StreamReport:
        report = _new_report(key, dest)
        for slug, page_url in pages.items():
            folder = dest / slug
            folder.mkdir(parents=True, exist_ok=True)
            try:
                html = (await get(client, page_url, timeout=90)).text
            except httpx.HTTPError as exc:
                report.errors.append(f"{page_url}: {type(exc).__name__}: {exc}")
                continue
            (folder / "page.html").write_text(html)
            links = asset_links(html, page_url, TEXTURE_EXTENSIONS)
            if host_filter:
                links = [link for link in links if host_filter in urlparse(link).netloc]
            if path_filter:
                links = [link for link in links if path_filter in urlparse(link).path.lower()]
            report.extra.setdefault("pages", {})[slug] = {"url": page_url, "files": len(links)}
            for link in links:
                await _fetch_file(
                    client, link.split("?")[0], folder / filename_from_url(link.split("?")[0]),
                    report, max_bytes=max_bytes, extra={"page": page_url},
                )
        return _finish(report, dest, next(iter(pages.values()), ""))

    return fetch


# ---------------------------------------------------------------------------
# USGS Astrogeology global mosaics (planet/moon surface textures)
# ---------------------------------------------------------------------------
USGS_SEARCH = "https://astrogeology.usgs.gov/search/results"
USGS_MAP = "https://astrogeology.usgs.gov/search/map/"
# The Astropedia product pages are JS-rendered, but the HTML they serve already
# contains the direct links to the rendered products on planetarymaps.usgs.gov —
# that host is what actually serves the GeoTIFF/JPEG, not the CKAN resource ids.
USGS_FILE_HOST = "planetarymaps.usgs.gov"


def usgs_mosaics(key: str, queries: list[str], *, max_bytes: int, total_budget: int,
                 want: list[str], extensions: set[str] | None = None) -> StreamFetcher:
    """Global surface mosaics, chosen by body name and kept inside a byte budget.

    `queries` are searched via the portal's JSON endpoint; `want` are substrings
    of the product slug (usually body names) that a hit must contain, so the
    crawl stays on global maps of bodies this data lake has no texture for
    rather than sweeping 1600 regional products. Products are taken smallest
    first: a 900 MB GeoTIFF and its 25 MB browse image show the same surface,
    and the budget buys more bodies that way.
    """
    wanted_ext = extensions or {".tif", ".jpg", ".png"}

    async def fetch(client: httpx.AsyncClient, dest: Path) -> StreamReport:
        report = _new_report(key, dest)
        slugs: list[str] = []
        for query in queries:
            try:
                payload = (await get(client, USGS_SEARCH, params={"q": query}, timeout=90)).json()
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                report.errors.append(f"{USGS_SEARCH}?q={query}: {type(exc).__name__}: {exc}")
                continue
            for result in payload.get("results") or []:
                slug = result.get("name") or ""
                if slug and slug not in slugs and any(w in slug.lower() for w in want):
                    slugs.append(slug)
        report.extra["slugs_considered"] = slugs

        found: list[dict] = []
        for slug in slugs:
            try:
                html = (await get(client, USGS_MAP + slug, timeout=90)).text
            except httpx.HTTPError as exc:
                report.errors.append(f"{USGS_MAP}{slug}: {type(exc).__name__}: {exc}")
                continue
            for link in asset_links(html, USGS_MAP + slug, wanted_ext):
                if USGS_FILE_HOST not in urlparse(link).netloc:
                    continue
                try:
                    head = await client.head(link, follow_redirects=True, timeout=60)
                    size = int(head.headers.get("content-length") or 0)
                except (httpx.HTTPError, ValueError):
                    size = 0
                found.append({"slug": slug, "url": link, "size": size})

        spent = 0
        for item in sorted(found, key=lambda i: i["size"]):
            if item["size"] > max_bytes:
                report.skipped.append(
                    f"{item['url']}: {human_bytes(item['size'])} > batas per-file "
                    f"{human_bytes(max_bytes)}"
                )
                continue
            if spent + item["size"] > total_budget:
                report.skipped.append(
                    f"{item['url']}: tidak muat di sisa budget "
                    f"{human_bytes(total_budget - spent)}"
                )
                continue
            before = report.downloaded
            await _fetch_file(
                client, item["url"], dest / item["slug"] / filename_from_url(item["url"]),
                report, max_bytes=max_bytes,
                extra={"product": item["slug"], "page": USGS_MAP + item["slug"]},
            )
            if report.downloaded > before:
                spent += item["size"]
        report.extra["budget_bytes"] = total_budget
        return _finish(report, dest, "https://astrogeology.usgs.gov/search")

    return fetch
