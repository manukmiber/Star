"""Folder-naming helpers: lowercase, snake_case, ASCII-only slugs.

Rules (see README section "Aturan Penamaan Folder"):
- lowercase, snake_case, ASCII only
- spaces -> underscore, strip anything outside [a-z0-9_-]
- callers are responsible for numeric prefixes (planets) and catalog-number
  prefixes (numbered asteroids) — this module only handles the text part.
"""

from __future__ import annotations

import re
import unicodedata


def slugify(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.strip().lower()
    normalized = normalized.replace(" ", "_")
    normalized = re.sub(r"[^a-z0-9_-]", "", normalized)
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_-")


def numbered_asteroid_slug(number: int, name: str) -> str:
    """e.g. (1, 'Ceres') -> '00001_ceres'."""
    return f"{number:05d}_{slugify(name)}"


def planet_slug(order: int, name: str) -> str:
    """e.g. (3, 'Earth') -> '03_earth'."""
    return f"{order:02d}_{slugify(name)}"


def dedupe_slug(base_slug: str, catalog_id: str) -> str:
    """Append a catalog ID suffix when two objects would slugify to the same name."""
    return f"{base_slug}__{slugify(catalog_id)}"
