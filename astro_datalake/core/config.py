"""Project-wide settings: paths, rate limits, User-Agent."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Contact used in the User-Agent string, per the etiquette expected by NASA/IPAC/
# CDS APIs (they ask for a way to reach the requester if something goes wrong).
DEFAULT_CONTACT_EMAIL = "bgas3453@gmail.com"

# api.le-systeme-solaire.net requires `Authorization: Bearer <key>` on every
# request. Keys are free and self-service (https://api.le-systeme-solaire.net/
# generatekey.html) and grant read-only access to public solar-system data, so
# this one is checked in on purpose to keep the source fetchable out of the box.
# Override with ASTRO_DL_SOLARSYSTEM_API_KEY to use your own.
DEFAULT_SOLAR_SYSTEM_API_KEY = "5eddd6b8-587c-4d85-94fd-250c1a750fdc"


class Settings(BaseModel):
    project_root: Path = PROJECT_ROOT
    data_dir: Path = PROJECT_ROOT / "data"
    raw_dir: Path = PROJECT_ROOT / "data" / "raw"
    catalog_dir: Path = PROJECT_ROOT / "data" / "_catalog"
    schema_dir: Path = PROJECT_ROOT / "data" / "_catalog" / "schema"
    logs_dir: Path = PROJECT_ROOT / "logs"

    contact_email: str = Field(
        default_factory=lambda: os.environ.get("ASTRO_DL_CONTACT_EMAIL", DEFAULT_CONTACT_EMAIL)
    )
    user_agent: str = ""
    solar_system_api_key: str = Field(
        default_factory=lambda: os.environ.get(
            "ASTRO_DL_SOLARSYSTEM_API_KEY", DEFAULT_SOLAR_SYSTEM_API_KEY
        )
    )
    spacetrack_user: str | None = Field(
        default_factory=lambda: os.environ.get("ASTRO_DL_SPACETRACK_USER")
    )
    spacetrack_password: str | None = Field(
        default_factory=lambda: os.environ.get("ASTRO_DL_SPACETRACK_PASS")
    )

    requests_per_second_per_domain: float = 1.0
    max_retries: int = 5
    request_timeout_seconds: float = 60.0

    def model_post_init(self, __context: object) -> None:
        if not self.user_agent:
            self.user_agent = f"AstroDataLake/1.0 (research; contact: {self.contact_email})"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.raw_dir, self.catalog_dir, self.schema_dir, self.logs_dir):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
