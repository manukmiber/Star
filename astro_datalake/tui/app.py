"""The Astro Data Lake TUI.

Four panes over the same machinery the CLI uses:

* **Sumber**   — every registered source, what's on disk, and its link status.
                 Space toggles a selection, `p` pulls it, `l` re-checks links.
* **Link**     — the link checker's findings per URL, refreshed in place.
* **Space-Track** — credential state, the documented retrieval-rate ledger
                 (when each class may next be pulled), and the exact query URL
                 each preset will issue.
* **Log**      — everything the workers did, appended live.

Long jobs run in Textual workers, so the UI keeps repainting while a
several-hundred-megabyte pull is in flight. Nothing here reimplements
downloading: it calls `downloaders.DOWNLOAD_PLAN` and `linkcheck` directly,
so the TUI and the CLI can never drift apart.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    ProgressBar,
    RichLog,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from ..core.cache import is_cached, write_raw
from ..core.config import settings
from ..core.http import make_client
from ..downloaders import DOWNLOAD_PLAN
from ..linkcheck import check_sources
from ..sources import spacetrack as st
from .state import AppState, SourceRow, human_size, spacetrack_status

#: Below this width we're almost certainly on a phone; stack the layout.
NARROW_WIDTH = 80

VERDICT_MARKUP = {
    "ready": "[green]siap[/green]",
    "suspect": "[yellow]curiga[/yellow]",
    "broken": "[red]rusak[/red]",
    "needs-credentials": "[cyan]kredensial[/cyan]",
    "no-plan": "[dim]manual[/dim]",
    "": "[dim]-[/dim]",
}

READINESS_MARKUP = {
    "siap": "[green]siap[/green]",
    "terpull": "[blue]terpull[/blue]",
    "kredensial": "[cyan]kredensial[/cyan]",
    "manual": "[dim]manual[/dim]",
}


class SummaryTile(Static):
    """One labelled number in the top strip."""

    value: reactive[str] = reactive("-")

    def __init__(self, label: str, value: str = "-", **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.add_class("tile")
        self.label = label
        self.value = value

    def render(self) -> str:
        return f"[dim]{self.label}[/dim]\n[bold]{self.value}[/bold]"

    def watch_value(self) -> None:
        self.refresh()


class AstroApp(App):
    """Astro Data Lake control panel."""

    CSS_PATH = "app.tcss"
    TITLE = "Astro Data Lake"
    SUB_TITLE = "pull · build · verify"

    BINDINGS = [
        Binding("space", "toggle_select", "Pilih", show=True),
        Binding("p", "pull_selected", "Pull", show=True),
        Binding("l", "check_links", "Cek link", show=True),
        Binding("a", "select_ready", "Pilih siap", show=True),
        Binding("c", "clear_selection", "Kosongkan", show=False),
        Binding("r", "refresh_state", "Refresh", show=True),
        Binding("s", "pull_spacetrack", "Space-Track", show=False),
        Binding("/", "focus_filter", "Cari", show=True),
        Binding("d", "toggle_dark", "Tema", show=False),
        Binding("q", "quit", "Keluar", show=True),
    ]

    running: reactive[bool] = reactive(False)

    def __init__(self) -> None:
        super().__init__()
        self.state = AppState()
        self.filter_text = ""
        self.tier_filter: int | None = None

    # -- layout ----------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="summary"):
            yield SummaryTile("Sumber", id="tile-sources")
            yield SummaryTile("Punya downloader", id="tile-ready")
            yield SummaryTile("Sudah dipull", id="tile-pulled")
            yield SummaryTile("Ukuran raw", id="tile-bytes")
            yield SummaryTile("Link terdaftar", id="tile-links")
            yield SummaryTile("Dipilih", id="tile-selected")
        yield ProgressBar(id="progress-bar", show_eta=False)

        with TabbedContent(initial="tab-sources"):
            with TabPane("Sumber", id="tab-sources"):
                with Horizontal(id="toolbar"):
                    yield Input(placeholder="cari sumber… (/)", id="filter")
                    yield Select(
                        [("Semua tier", 0), ("Tier 1", 1), ("Tier 2", 2), ("Tier 3", 3)],
                        value=0,
                        allow_blank=False,
                        id="tier-filter",
                    )
                yield DataTable(id="sources-table", cursor_type="row", zebra_stripes=True)
                yield Static(id="detail")
            with TabPane("Link", id="tab-links"):
                yield DataTable(id="links-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Space-Track", id="tab-spacetrack"):
                yield VerticalScroll(Static(id="spacetrack-body"))
            with TabPane("Log", id="tab-log"):
                yield RichLog(id="log", markup=True, wrap=True, highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#sources-table", DataTable)
        table.add_column("", key="sel", width=2)
        table.add_column("Sumber", key="key", width=26)
        table.add_column("T", key="tier", width=3)
        table.add_column("Status", key="status", width=11)
        table.add_column("Link", key="link", width=11)
        table.add_column("Raw", key="size", width=9)
        table.add_column("Kategori", key="category")

        links_table = self.query_one("#links-table", DataTable)
        links_table.add_column("Sumber", width=26)
        links_table.add_column("HTTP", width=5)
        links_table.add_column("Tipe", width=8)
        links_table.add_column("Detik", width=6)
        links_table.add_column("Catatan")

        self.action_refresh_state()
        table.focus()
        self.log_line("[dim]Siap. `l` cek semua link, `space` pilih sumber, `p` pull.[/dim]")

    def on_resize(self, event: events.Resize) -> None:
        # Use the event's size, not self.size: the latter is still the old
        # size while the resize is being dispatched.
        self.screen.set_class(event.size.width < NARROW_WIDTH, "-narrow")

    # -- helpers ---------------------------------------------------------
    def log_line(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.query_one("#log", RichLog).write(f"[dim]{stamp}[/dim] {message}")

    def visible_rows(self) -> list[SourceRow]:
        return self.state.filtered(tier=self.tier_filter, query=self.filter_text)

    def current_row(self) -> SourceRow | None:
        table = self.query_one("#sources-table", DataTable)
        if table.cursor_row < 0:
            return None
        rows = self.visible_rows()
        if table.cursor_row >= len(rows):
            return None
        return rows[table.cursor_row]

    def set_running(self, running: bool, total: int = 0) -> None:
        self.running = running
        bar = self.query_one("#progress-bar", ProgressBar)
        bar.set_class(running, "running")
        if running:
            bar.update(total=total or None, progress=0)

    def advance_progress(self, amount: int = 1) -> None:
        self.query_one("#progress-bar", ProgressBar).advance(amount)

    # -- rendering -------------------------------------------------------
    def refresh_summary(self) -> None:
        totals = self.state.totals()
        self.query_one("#tile-sources", SummaryTile).value = str(totals["sources"])
        self.query_one("#tile-ready", SummaryTile).value = str(totals["ready"])
        self.query_one("#tile-pulled", SummaryTile).value = str(totals["pulled"])
        self.query_one("#tile-bytes", SummaryTile).value = human_size(totals["bytes"])
        self.query_one("#tile-links", SummaryTile).value = str(totals["links"])
        self.query_one("#tile-selected", SummaryTile).value = str(totals["selected"])

    def refresh_table(self) -> None:
        table = self.query_one("#sources-table", DataTable)
        cursor = table.cursor_row
        table.clear()
        for row in self.visible_rows():
            table.add_row(
                "[bold green]✓[/bold green]" if row.selected else " ",
                row.key,
                str(row.spec.tier),
                READINESS_MARKUP.get(row.readiness, row.readiness),
                VERDICT_MARKUP.get(row.link_verdict, row.link_verdict or "-"),
                human_size(row.raw_bytes) if row.raw_bytes else "[dim]-[/dim]",
                row.spec.category,
                key=row.key,
            )
        if table.row_count:
            table.move_cursor(row=min(cursor if cursor >= 0 else 0, table.row_count - 1))
        self.refresh_detail()

    def refresh_detail(self) -> None:
        detail = self.query_one("#detail", Static)
        row = self.current_row()
        if row is None:
            detail.update("[dim]Tidak ada sumber terpilih.[/dim]")
            return

        from ..downloaders import declared_requests

        lines = [
            f"[bold]{row.spec.name}[/bold]",
            f"[dim]key[/dim] {row.key}   [dim]tier[/dim] {row.spec.tier}   "
            f"[dim]kategori[/dim] {row.spec.category}",
            f"[dim]lisensi[/dim] {row.spec.license or 'belum diverifikasi'}",
        ]
        if row.last_pull:
            lines.append(f"[dim]terakhir dipull[/dim] {row.last_pull:%Y-%m-%d %H:%M UTC}")
        if row.link_reason:
            lines.append(
                f"[dim]link[/dim] {VERDICT_MARKUP.get(row.link_verdict, '')} {row.link_reason}"
            )
        requests = declared_requests(row.key)
        if row.key == "spacetrack":
            from ..downloaders import SPACETRACK_REQUESTS

            requests = SPACETRACK_REQUESTS
        if requests:
            lines.append(f"[dim]permintaan HTTP ({len(requests)})[/dim]")
            for request in requests[:4]:
                lines.append(f"  [cyan]{request.method}[/cyan] {request.url}")
            if len(requests) > 4:
                lines.append(f"  [dim]… dan {len(requests) - 4} lagi[/dim]")
        else:
            lines.append("[yellow]Tidak ada downloader[/yellow] — lihat catatan di bawah.")
        if row.spec.notes:
            lines.append(f"[dim]{row.spec.notes}[/dim]")
        detail.update("\n".join(lines))

    def refresh_spacetrack(self) -> None:
        status = spacetrack_status()
        lines = ["[bold]Space-Track.org[/bold]", ""]
        if status["has_credentials"]:
            lines.append(f"[green]Kredensial terpasang[/green] — identity: {status['identity']}")
        else:
            lines += [
                "[yellow]Kredensial belum diset.[/yellow]",
                f"  export {st.ENV_IDENTITY}='email-akun-anda'",
                f"  export {st.ENV_PASSWORD}='password-anda'",
                "  Akun gratis: https://www.space-track.org/auth/createAccount",
            ]
        lines += [
            "",
            "[bold]Batas yang dipatuhi klien ini[/bold] "
            "[dim](space-track.org/documentation#/api)[/dim]",
            "  · < 30 permintaan / menit dan < 300 / jam (dipaksa di sisi klien)",
            "  · jeda minimal 2 detik antar permintaan",
            "  · login sekali per sesi, logout setelah selesai",
            "",
            "[bold]Frekuensi pengambilan per class[/bold] "
            "[dim](sesuai tabel di dokumentasi)[/dim]",
        ]
        for entry in status["classes"]:
            mark = "[green]boleh sekarang[/green]" if entry["allowed"] else "[yellow]tunggu[/yellow]"
            last = (
                entry["last_pull"].strftime("%Y-%m-%d %H:%M UTC")
                if entry["last_pull"]
                else "belum pernah"
            )
            lines += [
                f"  [bold]{entry['class']}[/bold] — {entry['description']}",
                f"    {mark}  [dim]terakhir:[/dim] {last}",
                f"    [dim]{entry['reason']}[/dim]",
                f"    [cyan]GET[/cyan] [dim]{entry['url']}[/dim]",
            ]
        lines += [
            "",
            f"[dim]Ledger: {status['ledger_path']}[/dim]",
            "[dim]Tekan `s` untuk menarik class yang sedang boleh diambil.[/dim]",
        ]
        self.query_one("#spacetrack-body", Static).update("\n".join(lines))

    # -- actions ---------------------------------------------------------
    def action_refresh_state(self) -> None:
        self.state.load()
        self.refresh_table()
        self.refresh_summary()
        self.refresh_spacetrack()

    def action_focus_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def action_toggle_select(self) -> None:
        row = self.current_row()
        if row is None:
            return
        row.selected = not row.selected
        self.refresh_table()
        self.refresh_summary()

    def action_select_ready(self) -> None:
        count = 0
        for row in self.visible_rows():
            if row.has_downloader:
                row.selected = True
                count += 1
        self.refresh_table()
        self.refresh_summary()
        self.notify(f"{count} sumber siap dipilih.")

    def action_clear_selection(self) -> None:
        self.state.clear_selection()
        self.refresh_table()
        self.refresh_summary()

    def action_toggle_dark(self) -> None:
        self.theme = "textual-light" if self.theme == "textual-dark" else "textual-dark"

    def action_check_links(self) -> None:
        if self.running:
            self.notify("Masih ada pekerjaan berjalan.", severity="warning")
            return
        keys = self.state.selected_keys or [row.key for row in self.visible_rows()]
        self.check_links_worker(keys)

    def action_pull_selected(self) -> None:
        if self.running:
            self.notify("Masih ada pekerjaan berjalan.", severity="warning")
            return
        keys = self.state.selected_keys
        if not keys:
            row = self.current_row()
            keys = [row.key] if row else []
        if not keys:
            self.notify("Pilih dulu sumbernya (space).", severity="warning")
            return
        runnable = [k for k in keys if DOWNLOAD_PLAN.get(k) is not None]
        skipped = [k for k in keys if k not in runnable]
        if skipped:
            self.log_line(f"[yellow]Dilewati (tanpa downloader):[/yellow] {', '.join(skipped)}")
        if not runnable:
            self.notify("Tidak ada sumber terpilih yang punya downloader.", severity="warning")
            return
        tiers = {self.state.rows[k].spec.tier for k in runnable}
        if tiers - {1}:
            self.log_line(
                f"[yellow]Perhatian:[/yellow] termasuk tier {sorted(tiers - {1})} — "
                "unduhan besar, pastikan ruang disk cukup."
            )
        self.pull_worker(runnable)

    def action_pull_spacetrack(self) -> None:
        if self.running:
            return
        if st.credentials_from_env() is None:
            self.notify(
                f"Set {st.ENV_IDENTITY} dan {st.ENV_PASSWORD} dulu.", severity="warning"
            )
            self.query_one(TabbedContent).active = "tab-spacetrack"
            return
        self.pull_worker(["spacetrack"])

    # -- events ----------------------------------------------------------
    @on(Input.Changed, "#filter")
    def on_filter_changed(self, event: Input.Changed) -> None:
        self.filter_text = event.value
        self.refresh_table()

    @on(Select.Changed, "#tier-filter")
    def on_tier_changed(self, event: Select.Changed) -> None:
        self.tier_filter = int(event.value) if event.value else None
        self.refresh_table()

    @on(DataTable.RowHighlighted, "#sources-table")
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self.refresh_detail()

    # -- workers ---------------------------------------------------------
    @work(exclusive=True, group="jobs")
    async def check_links_worker(self, keys: list[str]) -> None:
        self.set_running(True, total=len(keys))
        self.log_line(f"[bold]Cek link[/bold] untuk {len(keys)} sumber…")
        links_table = self.query_one("#links-table", DataTable)
        links_table.clear()
        try:
            def on_report(report) -> None:
                # Called from inside this async worker, so touching widgets
                # directly is safe — no thread hop needed.
                self.advance_progress()
                row = self.state.rows.get(report.key)
                if row is not None:
                    row.link_verdict = report.verdict
                    row.link_reason = report.reason
                for link in report.links:
                    links_table.add_row(
                        report.key,
                        str(link.http_status or "-"),
                        link.expected_kind,
                        f"{link.elapsed_seconds:.1f}" if link.elapsed_seconds else "-",
                        ("[green]" if link.works else "[red]") + link.detail,
                    )
                mark = VERDICT_MARKUP.get(report.verdict, report.verdict)
                self.log_line(f"  {report.key}: {mark} — {report.reason}")

            reports = await check_sources(keys, concurrency=4, progress=on_report)
            from ..linkcheck import summarize, write_report

            counts = summarize(reports)
            path = write_report(reports)
            self.state.last_link_check = datetime.now(timezone.utc)
            self.log_line(
                f"[bold]Selesai.[/bold] {counts['links_working']}/{counts['links_checked']} "
                f"link berfungsi · laporan: {path}"
            )
            self.notify(
                f"{counts['ready']} siap, {counts['broken']} rusak, "
                f"{counts['suspect']} curiga.",
                severity="error" if counts["broken"] else "information",
            )
        except Exception as exc:  # noqa: BLE001 - surface any failure in the UI
            self.log_line(f"[red]Cek link gagal:[/red] {type(exc).__name__}: {exc}")
            self.notify(f"Cek link gagal: {exc}", severity="error")
        finally:
            self.set_running(False)
            self.refresh_table()
            self.refresh_summary()

    @work(exclusive=True, group="jobs")
    async def pull_worker(self, keys: list[str]) -> None:
        from datetime import date

        self.set_running(True, total=len(keys))
        self.log_line(f"[bold]Pull[/bold] {len(keys)} sumber: {', '.join(keys)}")
        ok = failed = 0
        try:
            async with make_client() as client:
                for key in keys:
                    self.log_line(f"  [cyan]→ {key}[/cyan]")
                    fetcher = DOWNLOAD_PLAN.get(key)
                    if fetcher is None:
                        self.log_line("    [yellow]dilewati (tanpa downloader)[/yellow]")
                        self.advance_progress()
                        continue
                    try:
                        files = await fetcher(client)
                    except Exception as exc:  # noqa: BLE001 - one failure must not stop the batch
                        failed += 1
                        self.log_line(f"    [red]gagal:[/red] {type(exc).__name__}: {exc}")
                        self.advance_progress()
                        continue

                    today = date.today().isoformat()
                    written = cached = total_bytes = 0
                    for filename, content in files:
                        raw_path = settings.raw_dir / key / today / filename
                        total_bytes += len(content)
                        if is_cached(raw_path):
                            cached += 1
                            continue
                        write_raw(raw_path, content)
                        written += 1
                    ok += 1
                    self.log_line(
                        f"    [green]ok[/green]: {written} file baru, {cached} ter-cache, "
                        f"{human_size(total_bytes)}"
                    )
                    self.advance_progress()
                    self.state.load()
                    self.refresh_table()
                    self.refresh_summary()
        except Exception as exc:  # noqa: BLE001
            self.log_line(f"[red]Pull gagal:[/red] {type(exc).__name__}: {exc}")
        finally:
            self.set_running(False)
            self.action_refresh_state()
            self.notify(
                f"Pull selesai: {ok} berhasil, {failed} gagal.",
                severity="error" if failed else "information",
            )
