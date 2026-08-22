"""Project-wide settings: paths, rate limits, User-Agent.

Path resolution matters more than it looks. When the package is installed
(`pip install .` — the normal thing to do on Termux) `__file__` lives inside
site-packages, so deriving the data directory from it would scatter
gigabytes of catalogues into the Python install. Resolution order:

1. ``ASTRO_DL_HOME`` if set — explicit wins.
2. The checked-out repository, when we're running from a source tree
   (detected by ``pyproject.toml`` next to the package).
3. ``$XDG_DATA_HOME/astro-datalake``, else ``~/.local/share/astro-datalake``
   — which is exactly where Termux's single-user filesystem wants it.

Deliberately a plain dataclass rather than a pydantic model: pydantic pulls
in ``pydantic-core``, a compiled Rust extension with no Termux wheel, and
this settings object never validates untrusted input. Keeping it stdlib-only
is what lets ``pip install astro-datalake`` finish on a phone without a
toolchain.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parents[1]

# Contact used in the User-Agent string, per the etiquette expected by NASA/IPAC/
# CDS APIs (they ask for a way to reach the requester if something goes wrong).
DEFAULT_CONTACT_EMAIL = "bgas3453@gmail.com"

ENV_HOME = "ASTRO_DL_HOME"

# api.le-systeme-solaire.net requires `Authorization: Bearer <key>` on every
# request. Keys are free and self-service (https://api.le-systeme-solaire.net/
# generatekey.html) and grant read-only access to public solar-system data, so
# this one is checked in on purpose to keep the source fetchable out of the box.
# Override with ASTRO_DL_SOLARSYSTEM_API_KEY to use your own.
DEFAULT_SOLAR_SYSTEM_API_KEY = "5eddd6b8-587c-4d85-94fd-250c1a750fdc"


def _is_source_checkout(path: Path) -> bool:
    return (path / "pyproject.toml").exists() and (path / "astro_datalake").is_dir()


def resolve_project_root() -> Path:
    """Where data/ and logs/ live. See the module docstring for the order."""
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override).expanduser().resolve()

    repo_root = _PACKAGE_DIR.parent
    if _is_source_checkout(repo_root):
        return repo_root

    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return (base / "astro-datalake").resolve()


PROJECT_ROOT = resolve_project_root()


def source_checkout_root() -> Path | None:
    """The git checkout we're running from, or None when pip-installed.

    Distinct from `project_root`, which is where *data* goes. Repo artifacts
    (`public/manifest.json`, which is committed and deployed to Cloudflare)
    belong to the checkout, not to the user's data directory — otherwise
    `astro manifest` on an installed copy would write a stray file into
    ~/.local/share and `--check` would compare against nothing.
    """
    repo_root = _PACKAGE_DIR.parent
    return repo_root if _is_source_checkout(repo_root) else None


def on_termux() -> bool:
    """True when running under Termux on Android.

    Termux sets PREFIX to /data/data/com.termux/files/usr; that's the most
    reliable marker, with the ANDROID_ROOT / TERMUX_VERSION vars as backup.
    """
    prefix = os.environ.get("PREFIX", "")
    return (
        "com.termux" in prefix
        or bool(os.environ.get("TERMUX_VERSION"))
        or (bool(os.environ.get("ANDROID_ROOT")) and Path("/data/data/com.termux").exists())
    )


@dataclass
class Settings:
    project_root: Path = PROJECT_ROOT
    data_dir: Path = PROJECT_ROOT / "data"
    raw_dir: Path = PROJECT_ROOT / "data" / "raw"
    catalog_dir: Path = PROJECT_ROOT / "data" / "_catalog"
    schema_dir: Path = PROJECT_ROOT / "data" / "_catalog" / "schema"
    logs_dir: Path = PROJECT_ROOT / "logs"

    contact_email: str = field(
        default_factory=lambda: os.environ.get("ASTRO_DL_CONTACT_EMAIL", DEFAULT_CONTACT_EMAIL)
    )
    user_agent: str = ""
    solar_system_api_key: str = field(
        default_factory=lambda: os.environ.get(
            "ASTRO_DL_SOLARSYSTEM_API_KEY", DEFAULT_SOLAR_SYSTEM_API_KEY
        )
    )
    spacetrack_user: str | None = field(
        default_factory=lambda: os.environ.get("ASTRO_DL_SPACETRACK_USER")
    )
    spacetrack_password: str | None = field(
        default_factory=lambda: os.environ.get("ASTRO_DL_SPACETRACK_PASS")
    )

    requests_per_second_per_domain: float = 1.0
    max_retries: int = 5
    request_timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        if not self.user_agent:
            platform = "Termux/Android" if on_termux() else "research"
            self.user_agent = f"AstroDataLake/1.0 ({platform}; contact: {self.contact_email})"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.raw_dir, self.catalog_dir, self.schema_dir, self.logs_dir):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
