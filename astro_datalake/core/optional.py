"""Helpers for optional, natively-compiled dependencies.

`astro pull`, `astro links`, `astro status` and `astro tui` run on the
pure-Python core so they work on Termux out of the box. `astro build` and
`astro verify` need polars / BeautifulSoup / jsonschema, which are installed
via the `build` extra. When one is missing we want an instruction, not a
bare ImportError two frames deep in a builder.
"""

from __future__ import annotations

from importlib import import_module
from importlib.util import find_spec

from .config import on_termux

#: module name -> (pip extra it belongs to, what it's needed for)
OPTIONAL_MODULES: dict[str, tuple[str, str]] = {
    "polars": ("build", "membaca/menulis tabel saat `astro build`"),
    "numpy": ("build", "perhitungan crossmatch/orbit saat `astro build`"),
    "bs4": ("build", "mem-parse tabel HTML JPL saat `astro build`"),
    "jsonschema": ("build", "validasi JSON-schema saat `astro verify`"),
    "textual": ("", "TUI (`astro tui`)"),
}

TERMUX_HINTS = {
    "numpy": (
        "Di Termux pakai `pkg install python-numpy` (ada paket siap pakai), "
        "jangan `pip install numpy` yang akan mengompilasi dari sumber."
    ),
    "polars": (
        "Di Termux polars tidak punya wheel siap pakai; pasang lewat "
        "`pkg install rust binutils && pip install polars` (butuh waktu & ruang), "
        "atau jalankan `astro build` di mesin lain dan sinkronkan folder data/."
    ),
}


class MissingDependency(RuntimeError):
    """An optional dependency is needed but not installed."""


def is_available(module: str) -> bool:
    try:
        return find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def install_hint(module: str) -> str:
    extra, purpose = OPTIONAL_MODULES.get(module, ("build", "fitur ini"))
    lines = [f"Paket `{module}` dibutuhkan untuk {purpose}, tapi belum terpasang."]
    if extra:
        lines.append(f"Pasang dengan:  pip install 'astro-datalake[{extra}]'   (atau: uv sync --extra {extra})")
    else:
        lines.append(f"Pasang dengan:  pip install {module}")
    if on_termux() and module in TERMUX_HINTS:
        lines.append(TERMUX_HINTS[module])
    return "\n".join(lines)


def require(module: str):
    """Import `module`, or raise MissingDependency with install instructions."""
    try:
        return import_module(module)
    except ImportError as exc:
        raise MissingDependency(install_hint(module)) from exc


def missing_for(*modules: str) -> list[str]:
    return [module for module in modules if not is_available(module)]
