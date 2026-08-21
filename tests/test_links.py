"""The download-link registry is the project's contract with its sources.

These tests do not touch the network — they check that the registry is
complete, internally consistent, and that nothing secret escapes into
published output.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest

from astro_datalake.core.config import settings
from astro_datalake.downloaders import DOWNLOAD_PLAN, unfetchable_reason
from astro_datalake.manifest import build_manifest, manifest_is_current
from astro_datalake.sources.links import LINKS, LinkStatus
from astro_datalake.sources.registry import SOURCES


def test_every_source_has_links() -> None:
    assert set(LINKS) == set(SOURCES)


@pytest.mark.parametrize("key", sorted(LINKS))
def test_fetchable_sources_have_targets(key: str) -> None:
    links = LINKS[key]
    if links.status is LinkStatus.RETIRED:
        assert not links.targets, f"{key} is retired but still lists targets"
        assert links.replaced_by, f"{key} is retired without naming a replacement"
    else:
        assert links.targets, f"{key} has no download target"


@pytest.mark.parametrize("key", sorted(LINKS))
def test_targets_are_well_formed(key: str) -> None:
    seen: set[str] = set()
    for target in LINKS[key].targets:
        parsed = urlparse(target.url)
        assert parsed.scheme == "https", f"{key}/{target.filename} is not https"
        assert parsed.netloc, f"{key}/{target.filename} has no host"
        assert target.method in ("GET", "POST")
        assert target.timeout > 0
        assert target.filename not in seen, f"{key} repeats filename {target.filename}"
        seen.add(target.filename)
        assert "/" not in target.filename and ".." not in target.filename


def test_credentialed_sources_declare_their_env_vars() -> None:
    for key, links in LINKS.items():
        if links.status is LinkStatus.CREDENTIALED:
            assert links.credential_env, f"{key} needs credentials but names no env var"


def test_resolved_url_carries_params() -> None:
    target = LINKS["celestrak_gp_active"].targets[0]
    query = parse_qs(urlparse(target.resolved_url).query)
    assert query["GROUP"] == ["active"]
    assert query["FORMAT"] == ["json"]


def test_browser_fetchable_flag_tracks_post_and_auth() -> None:
    assert LINKS["hyg_database"].targets[0].browser_fetchable is True
    # POST body cannot survive a plain link.
    assert LINKS["usgs_gazetteer"].targets[0].browser_fetchable is False
    # Neither can an Authorization header.
    assert LINKS["le_systeme_solaire"].targets[0].browser_fetchable is False


def test_gaia_tier3_chunks_tile_the_random_index_range() -> None:
    """Chunk boundaries must be contiguous, or the subset silently loses rows."""
    from astro_datalake.sources.links import GAIA_CHUNK_WIDTH, GAIA_RANDOM_INDEX_MAX

    bounds = []
    for target in LINKS["gaia_dr3_tap"].targets:
        query = parse_qs(urlparse(target.resolved_url).query)["QUERY"][0]
        lower = int(query.split("random_index >= ")[1].split(" ")[0])
        upper = int(query.split("random_index < ")[1].split(" ")[0])
        bounds.append((lower, upper))
    bounds.sort()
    assert bounds[0][0] == 0
    for (_, previous_end), (next_start, _) in zip(bounds, bounds[1:]):
        assert previous_end == next_start, "gap or overlap between Gaia chunks"
    assert bounds[-1][1] >= GAIA_RANDOM_INDEX_MAX
    assert all(upper - lower == GAIA_CHUNK_WIDTH for lower, upper in bounds)


def test_download_plan_covers_every_fetchable_source() -> None:
    for key, links in LINKS.items():
        planned = DOWNLOAD_PLAN.get(key) is not None
        if links.status in (LinkStatus.DIRECT, LinkStatus.QUERY):
            assert planned, f"{key} is {links.status.value} but has no fetcher"
        else:
            # Retired, or credentialed with no credentials in this environment.
            assert not planned or links.status is LinkStatus.CREDENTIALED


def test_unfetchable_sources_explain_themselves() -> None:
    for key, fetcher in DOWNLOAD_PLAN.items():
        if fetcher is None:
            assert unfetchable_reason(key), f"{key} is skipped with no reason given"
        else:
            assert unfetchable_reason(key) is None


# -- secret handling ------------------------------------------------------
def test_secret_header_values_never_reach_published_output() -> None:
    key = settings.solar_system_api_key
    assert key, "expected a solar-system API key to be configured"

    target = LINKS["le_systeme_solaire"].targets[0]
    assert key in target.headers["Authorization"], "the fetcher must still send the key"
    assert key not in target.curl_command()
    assert key not in json.dumps(build_manifest())


def test_manifest_publishes_header_names_not_values() -> None:
    manifest = build_manifest()
    source = next(s for s in manifest["sources"] if s["key"] == "le_systeme_solaire")
    assert source["targets"][0]["required_headers"] == ["Authorization"]
    assert "headers" not in source["targets"][0]


# -- manifest -------------------------------------------------------------
def test_manifest_counts_match_the_registry() -> None:
    manifest = build_manifest()
    assert manifest["counts"]["sources"] == len(SOURCES)
    assert manifest["counts"]["targets"] == sum(
        len(links.targets) for links in LINKS.values()
    )
    assert manifest["counts"]["fetchable_sources"] == sum(
        1 for v in DOWNLOAD_PLAN.values() if v is not None
    )


def test_committed_manifest_is_not_stale() -> None:
    """public/manifest.json ships to Cloudflare as-is — it must match the code.

    The Cloudflare build only runs `uv sync` and `npx wrangler deploy`, with no
    generation step, so a stale committed manifest would deploy wrong links.
    """
    assert manifest_is_current(), (
        "public/manifest.json is out of date — run `astro manifest`"
    )
