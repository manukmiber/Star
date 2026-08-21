"""Headless tests for the TUI.

Textual's Pilot drives the real app in an off-screen terminal, so these
exercise the same code path a user gets — including the narrow layout that
Termux on a phone lands in.
"""

from __future__ import annotations

import pytest
from textual.widgets import DataTable, Input, Select, Static, TabbedContent

from astro_datalake.tui.app import NARROW_WIDTH, AstroApp
from astro_datalake.tui.state import AppState, human_size


# --- state model (no terminal needed) --------------------------------------
def test_state_loads_every_registered_source():
    from astro_datalake.sources.registry import SOURCES

    state = AppState()
    state.load()
    assert set(state.rows) == set(SOURCES)
    assert state.totals()["sources"] == len(SOURCES)


def test_filter_by_tier_and_text():
    state = AppState()
    state.load()
    assert all(row.spec.tier == 2 for row in state.filtered(tier=2))
    assert [row.key for row in state.filtered(query="spacetrack")] == ["spacetrack"]
    assert all(row.has_downloader for row in state.filtered(only_ready=True))


def test_selection_round_trip():
    state = AppState()
    state.load()
    state.rows["cneos_sentry"].selected = True
    assert state.selected_keys == ["cneos_sentry"]
    state.clear_selection()
    assert state.selected_keys == []


@pytest.mark.parametrize(
    "size,expected", [(0, "0B"), (900, "900B"), (2048, "2.0KB"), (5 * 1024**3, "5.0GB")]
)
def test_human_size(size, expected):
    assert human_size(size) == expected


# --- driving the app -------------------------------------------------------
async def test_app_starts_with_a_populated_table():
    app = AstroApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        table = app.query_one("#sources-table", DataTable)
        assert table.row_count == len(app.state.rows)
        assert app.focused.id == "sources-table"


async def test_space_selects_the_highlighted_source():
    app = AstroApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        assert len(app.state.selected_keys) == 1
        await pilot.press("space")
        await pilot.pause()
        assert app.state.selected_keys == []


async def test_select_ready_then_clear():
    app = AstroApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()
        assert len(app.state.selected_keys) == app.state.totals()["ready"]
        await pilot.press("c")
        await pilot.pause()
        assert app.state.selected_keys == []


async def test_filtering_narrows_the_table():
    app = AstroApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        table = app.query_one("#sources-table", DataTable)
        app.query_one("#filter", Input).value = "exoplanet"
        await pilot.pause()
        assert 0 < table.row_count < len(app.state.rows)

        app.query_one("#filter", Input).value = ""
        app.query_one("#tier-filter", Select).value = 3
        await pilot.pause()
        assert all(row.spec.tier == 3 for row in app.visible_rows())


async def test_detail_pane_follows_the_cursor():
    app = AstroApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#detail", Static)
        first = str(detail.content)
        await pilot.press("down", "down", "down")
        await pilot.pause()
        assert str(detail.content) != first


async def test_spacetrack_panel_states_the_documented_limits():
    app = AstroApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.query_one(TabbedContent).active = "tab-spacetrack"
        await pilot.pause()
        text = str(app.query_one("#spacetrack-body", Static).content)
        assert "30 permintaan" in text  # <30/minute
        assert "300" in text  # <300/hour
        assert "space-track.org/documentation" in text


async def test_narrow_terminal_switches_to_the_phone_layout():
    app = AstroApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert not app.screen.has_class("-narrow")

        await pilot.resize_terminal(NARROW_WIDTH - 34, 30)  # a phone in Termux
        await pilot.pause()
        assert app.screen.has_class("-narrow")

        await pilot.resize_terminal(120, 40)
        await pilot.pause()
        assert not app.screen.has_class("-narrow")


async def test_pull_of_a_source_without_a_downloader_fetches_nothing():
    app = AstroApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.query_one("#filter", Input).value = "nssdc"  # dead source, no downloader
        await pilot.pause()
        before = app.state.totals()
        await pilot.press("p")
        await pilot.pause()
        assert app.state.totals() == before  # nothing downloaded, nothing crashed
        assert not app.running


async def test_every_tab_renders():
    app = AstroApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        tabs = app.query_one(TabbedContent)
        for tab in ("tab-links", "tab-spacetrack", "tab-log", "tab-sources"):
            tabs.active = tab
            await pilot.pause()
            assert tabs.active == tab
