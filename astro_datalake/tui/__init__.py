"""Textual TUI for the Astro Data Lake (`astro tui`)."""

from __future__ import annotations


def run() -> None:
    """Launch the TUI. Imported lazily so the CLI works without Textual."""
    from .app import AstroApp

    AstroApp().run()


__all__ = ["run"]
