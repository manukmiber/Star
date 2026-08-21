"""Shared helpers for every Fase 3 builder: leaf-folder writers, the
{value, err_upper, err_lower, limit_flag, ref} sourced-value shape, and
category-folder index/README/parquet writers.

Every builder module in astro_datalake/build/ follows the same contract:
a `build(raw_dir: Path, out_dir: Path) -> BuildReport` function that reads
already-downloaded raw files (never the network) and writes the processed
tree under data/.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

from ..sources.registry import SOURCES


@dataclass
class BuildReport:
    category: str
    object_count: int = 0
    leaf_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def note(self, msg: str) -> None:
        self.warnings.append(msg)


def sv(value: Any, err_upper: Any = None, err_lower: Any = None, limit_flag: str | None = None, ref: str | None = None) -> dict:
    """A numeric value with its uncertainty, per brief section 7."""
    return {
        "value": value,
        "err_upper": err_upper,
        "err_lower": err_lower,
        "limit_flag": limit_flag,
        "ref": ref,
    }


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n")


ATTRIBUTION_BEGIN = "<!-- attribution:begin -->"
ATTRIBUTION_END = "<!-- attribution:end -->"


def source_keys_of(source: str) -> list[str]:
    """Every registry key named in a builder's free-text `source` string.

    Builders write things like "wds_catalog (VizieR B/wds)" for one source
    and "jpl_sat_elem + jpl_sat_phys_par + jpl_sat_discovery" for a folder
    fed by three, so reading only the first token would under-attribute the
    combined ones.
    """
    if not source:
        return []
    keys = []
    for token in re.split(r"[^A-Za-z0-9_]+", source):
        if token in SOURCES and token not in keys:
            keys.append(token)
    return keys


def source_key_of(source: str) -> str | None:
    """First registry key in `source`, or None when it names none."""
    keys = source_keys_of(source)
    return keys[0] if keys else None


def license_of(source: str) -> str | None:
    key = source_key_of(source)
    return SOURCES[key].license if key else None


def attribution_block(sources: list[str]) -> str:
    """Markdown attribution section for one or more sources.

    CDS/VizieR, CelesTrak and MPC all ask for attribution in derived work,
    so the licence line from the registry is copied into every folder that
    carries their data instead of living only in metadata.json.
    """
    lines = [ATTRIBUTION_BEGIN, "## Sumber & atribusi", ""]
    seen: set[str] = set()
    for source in sources:
        for key in source_keys_of(source):
            if key in seen:
                continue
            seen.add(key)
            spec = SOURCES[key]
            lines.append(f"- **{spec.name}** (`{key}`)")
            lines.append(f"  - URL: {spec.base_url}")
            lines.append(f"  - Lisensi/atribusi: {spec.license or 'belum diverifikasi'}")
    if not seen:
        lines.append("- Sumber tidak terdaftar di `sources/registry.py`.")
    lines.append("")
    lines.append(ATTRIBUTION_END)
    return "\n".join(lines)


def write_metadata(
    path: Path,
    *,
    source: str,
    source_url: str,
    record_count: int | None = None,
    license: str | None = None,
    upstream_version: str | None = None,
    sha256_of_raw: str | None = None,
    retrieved_at: str | None = None,
    derived_from: list[str] | None = None,
    classification_method: str | None = None,
) -> None:
    """`license` defaults to the registry's entry for `source` when omitted.

    `derived_from` / `classification_method` are for folders whose contents
    are computed rather than copied (exoplanet by_type, TNO sub-classes,
    trojan camps): they name the inputs and the rule, so a derived label is
    never mistaken for a measured one.
    """
    payload = {
        "source": source,
        "source_url": source_url,
        "retrieved_at": retrieved_at or datetime.now(timezone.utc).isoformat(),
        "record_count": record_count,
        "license": license if license is not None else license_of(source),
        "upstream_version": upstream_version,
        "sha256_of_raw": sha256_of_raw,
    }
    if derived_from is not None:
        payload["derived_from"] = derived_from
    if classification_method is not None:
        payload["classification_method"] = classification_method
    write_json(path, payload)


def write_readme(dir_path: Path, title: str, body: str, sources: list[str] | None = None) -> None:
    """Write dir_path/README.md with the attribution block already attached."""
    text = f"# {title}\n\n{body.strip()}\n"
    if sources:
        text += "\n" + attribution_block(sources) + "\n"
    write_text(dir_path / "README.md", text)


def write_category_index(
    dir_path: Path, children: list[str], description: str, sources: list[str] | None = None
) -> None:
    write_json(dir_path / "index.json", {
        "children": sorted(children),
        "count": len(children),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })
    write_readme(dir_path, dir_path.name, f"{description}\n\n{len(children)} entri.", sources)


def write_category_table(dir_path: Path, df: pl.DataFrame, max_csv_rows: int = 100_000) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    df.write_parquet(dir_path / "all.parquet")
    if df.height < max_csv_rows:
        try:
            df.write_csv(dir_path / "all.csv")
        except pl.exceptions.ComputeError:
            pass  # nested/struct columns (e.g. sourced-value dicts) — parquet already has it


def latest_raw_dir(raw_root: Path, key: str) -> Path | None:
    """data/raw/<key>/<latest YYYY-MM-DD>/"""
    base = raw_root / key
    if not base.exists():
        return None
    dated = sorted((p for p in base.iterdir() if p.is_dir()), reverse=True)
    return dated[0] if dated else None


def latest_raw_file(raw_root: Path, key: str, filename: str) -> Path | None:
    d = latest_raw_dir(raw_root, key)
    if d is None:
        return None
    f = d / filename
    return f if f.exists() else None
