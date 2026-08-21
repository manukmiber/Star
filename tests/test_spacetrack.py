"""Tests for the Space-Track client against the documented API shapes."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from astro_datalake.sources import spacetrack as st


# --- URL construction ------------------------------------------------------
def test_gp_current_matches_documented_query():
    """The docs prescribe /decay_date/null-val/epoch/%3Enow-10/ for live objects."""
    url = st.gp_current().url()
    assert url.startswith("https://www.space-track.org/basicspacedata/query/class/gp/")
    assert "/decay_date/null-val/" in url
    assert "/epoch/%3Enow-10/" in url  # '>' must be percent-encoded
    assert url.endswith("/format/json")


def test_comma_list_is_one_request_not_many():
    """Docs: combine objects into a comma-delimited list, don't loop per object."""
    url = st.gp_for_objects([25544, 43873, 44506]).url()
    assert "/norad_cat_id/25544,43873,44506/" in url  # commas survive encoding


def test_operators_survive_encoding_but_slashes_do_not():
    assert st.encode_value(">now-10") == "%3Enow-10"
    assert st.encode_value("<100000") == "%3C100000"
    assert st.encode_value("100000--339999") == "100000--339999"
    assert st.encode_value("~~starlink") == "~~starlink"
    assert st.encode_value("norad_cat_id asc") == "norad_cat_id%20asc"
    assert st.encode_value("a/b") == "a%2Fb"  # a slash would break the path


def test_modeldef_url_has_no_query_parts():
    url = st.Query(class_name="gp", action="modeldef").url()
    assert url == "https://www.space-track.org/basicspacedata/modeldef/class/gp"


def test_limit_and_offset_render_as_one_segment():
    spec = st.Query(class_name="satcat", limit=100, offset=200)
    assert "/limit/100,200/" in spec.url()


def test_unknown_controller_and_format_are_rejected():
    with pytest.raises(ValueError):
        st.Query(class_name="gp", controller="nope")
    with pytest.raises(ValueError):
        st.Query(class_name="gp", response_format="parquet")


def test_every_preset_builds_a_valid_url():
    for name, (_description, factory) in st.PRESETS.items():
        url = factory().url()
        assert url.startswith("https://www.space-track.org/basicspacedata/query/class/")
        assert f"/class/{name}/" in url or name in url


# --- Retrieval-frequency ledger -------------------------------------------
def test_ledger_blocks_a_second_gp_pull_within_the_hour(tmp_path):
    ledger = st.RetrievalLedger(tmp_path / "ledger.json")
    assert ledger.check("gp")[0] is True

    ledger.record("gp", "https://example.invalid", 10)
    allowed, reason = ledger.check("gp")
    assert allowed is False
    assert "once every hour" in reason


def test_ledger_allows_gp_again_after_an_hour(tmp_path):
    path = tmp_path / "ledger.json"
    stale = datetime.now(timezone.utc) - timedelta(hours=2)
    path.write_text(json.dumps({"gp": {"retrieved_at": stale.isoformat(), "bytes": 1}}))
    assert st.RetrievalLedger(path).check("gp")[0] is True


def test_gp_history_is_once_per_lifetime(tmp_path):
    ledger = st.RetrievalLedger(tmp_path / "ledger.json")
    ledger.record("gp_history", "https://example.invalid", 10)
    allowed, reason = ledger.check("gp_history")
    assert allowed is False
    assert "1/lifetime" in reason


def test_satcat_waits_until_1700_utc(tmp_path):
    ledger = st.RetrievalLedger(tmp_path / "ledger.json")
    morning = datetime(2026, 8, 21, 9, 0, tzinfo=timezone.utc)
    allowed, reason = ledger.check("satcat", now=morning)
    assert allowed is False
    assert "1700 UTC" in reason

    evening = datetime(2026, 8, 21, 18, 0, tzinfo=timezone.utc)
    assert ledger.check("satcat", now=evening)[0] is True


def test_ledger_survives_a_corrupt_file(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text("{not json")
    assert st.RetrievalLedger(path).check("gp")[0] is True


# --- Throttle --------------------------------------------------------------
def test_throttle_stays_under_the_documented_ceilings():
    throttle = st.SpaceTrackThrottle()
    assert throttle.per_minute < 30
    assert throttle.per_hour < 300


def test_throttle_makes_the_31st_request_in_a_minute_wait():
    throttle = st.SpaceTrackThrottle(per_minute=25, per_hour=275, min_interval_seconds=2.0)
    now = 1000.0
    throttle._events.extend(now - offset for offset in range(25, 0, -1))
    throttle._last = now - 1
    assert throttle._wait_needed(now) > 0


async def test_throttle_enforces_the_minimum_gap():
    throttle = st.SpaceTrackThrottle(min_interval_seconds=0.05)
    await throttle.acquire()
    await throttle.acquire()
    assert throttle.used_last_minute == 2


# --- Session handling ------------------------------------------------------
@respx.mock
async def test_login_success_then_query():
    respx.post(st.LOGIN_URL).mock(
        return_value=httpx.Response(200, json="", headers={"set-cookie": "chocolatechip=abc"})
    )
    route = respx.get(url__startswith="https://www.space-track.org/basicspacedata/query").mock(
        return_value=httpx.Response(200, json=[{"NORAD_CAT_ID": "25544"}])
    )
    respx.get(st.LOGOUT_URL).mock(return_value=httpx.Response(200))

    throttle = st.SpaceTrackThrottle(min_interval_seconds=0.0)
    async with st.SpaceTrackClient("user", "pass", throttle=throttle) as client:
        rows = await client.query_json(st.gp_current())

    assert rows == [{"NORAD_CAT_ID": "25544"}]
    assert route.called


@respx.mock
async def test_login_failure_is_reported_not_swallowed():
    respx.post(st.LOGIN_URL).mock(return_value=httpx.Response(200, json={"Login": "Failed"}))
    client = st.SpaceTrackClient(
        "user", "wrong", throttle=st.SpaceTrackThrottle(min_interval_seconds=0.0)
    )
    with pytest.raises(st.SpaceTrackAuthError, match="Login"):
        await client.login()
    await client.aclose()


@respx.mock
async def test_login_without_session_cookie_is_an_error():
    respx.post(st.LOGIN_URL).mock(return_value=httpx.Response(200, json=""))
    client = st.SpaceTrackClient(
        "user", "pass", throttle=st.SpaceTrackThrottle(min_interval_seconds=0.0)
    )
    with pytest.raises(st.SpaceTrackAuthError, match="session cookie"):
        await client.login()
    await client.aclose()


@respx.mock
async def test_401_on_query_raises_auth_error():
    respx.post(st.LOGIN_URL).mock(
        return_value=httpx.Response(200, json="", headers={"set-cookie": "chocolatechip=abc"})
    )
    respx.get(url__startswith="https://www.space-track.org/basicspacedata/query").mock(
        return_value=httpx.Response(401, text="unauthorized")
    )
    respx.get(st.LOGOUT_URL).mock(return_value=httpx.Response(200))

    client = st.SpaceTrackClient(
        "user", "pass", throttle=st.SpaceTrackThrottle(min_interval_seconds=0.0)
    )
    with pytest.raises(st.SpaceTrackAuthError):
        await client.query(st.gp_current())
    await client.aclose()


@respx.mock
async def test_429_is_retried_then_succeeds():
    respx.post(st.LOGIN_URL).mock(
        return_value=httpx.Response(200, json="", headers={"set-cookie": "chocolatechip=abc"})
    )
    respx.get(url__startswith="https://www.space-track.org/basicspacedata/query").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json=[]),
        ]
    )
    respx.get(st.LOGOUT_URL).mock(return_value=httpx.Response(200))

    async with st.SpaceTrackClient(
        "user", "pass", throttle=st.SpaceTrackThrottle(min_interval_seconds=0.0)
    ) as client:
        assert await client.query_json(st.gp_current()) == []


@respx.mock
async def test_logout_is_called_on_exit():
    respx.post(st.LOGIN_URL).mock(
        return_value=httpx.Response(200, json="", headers={"set-cookie": "chocolatechip=abc"})
    )
    logout = respx.get(st.LOGOUT_URL).mock(return_value=httpx.Response(200))
    async with st.SpaceTrackClient(
        "user", "pass", throttle=st.SpaceTrackThrottle(min_interval_seconds=0.0)
    ):
        pass
    assert logout.called


def test_missing_credentials_are_rejected_up_front():
    with pytest.raises(st.SpaceTrackAuthError):
        st.SpaceTrackClient("", "")
