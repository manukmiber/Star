"""Parser for the PDS SBN shape-model catalog.

sbn.psi.edu/pds/shape-models/ renders client-side, so the HTML carries no
data. The catalog itself lives in two Angular files:

  js/app.Datasets.js  — {dataset key: {name, link, basepath}}
  js/app.Data.js      — .factory('Comets'|'Asteroids'|'Satellites'), each an
                        array of {name, type, datasets: [{name, link, files}]}

Entries in app.Data.js reference the datasets by local const
(`Hudson.basepath + '1998ky26.tab'`), so the two files have to be read
together. This module resolves those references and returns plain dicts —
no JS engine, no network.
"""

from __future__ import annotations

import json
import re

FACTORIES = ("Comets", "Asteroids", "Satellites")

_KEY = re.compile(r"([{,\[]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)")
_SINGLE_QUOTED = re.compile(r"'([^']*)'")
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_CONCAT = re.compile(r'("(?:[^"\\]|\\.)*")\s*\+\s*("(?:[^"\\]|\\.)*")')
# Upstream typo: a couple of entries write `'Hudson.basepath' + 'x.usdz'` with the
# const name inside the quotes, so the link they build is a dead relative path on
# the source site too. Either the const name survives verbatim, or (once the
# surrounding literal has been resolved) a stray quote ends up inside the link —
# both are detected here and skipped, with the broken link reported.
_UNRESOLVED_CONST = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.(basepath|link|name)")


def _balanced_array(src: str, start: int) -> str:
    """Return the JS array literal starting at `src[start]` == '['."""
    depth = 0
    for idx in range(start, len(src)):
        char = src[idx]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return src[start : idx + 1]
    raise ValueError("unterminated array literal")


def _js_object_to_json(blob: str) -> object:
    quoted = _KEY.sub(r'\1"\2"\3', blob)
    quoted = _SINGLE_QUOTED.sub(lambda m: json.dumps(m.group(1)), quoted)
    quoted = _TRAILING_COMMA.sub(r"\1", quoted)
    while True:  # fold "a" + "b" (JS string concat) into one literal
        folded = _CONCAT.sub(
            lambda m: json.dumps(json.loads(m.group(1)) + json.loads(m.group(2))), quoted
        )
        if folded == quoted:
            break
        quoted = folded
    return json.loads(quoted)


def parse_datasets(datasets_js: str) -> dict[str, dict]:
    start = datasets_js.index("{", datasets_js.index("return"))
    depth = 0
    for idx in range(start, len(datasets_js)):
        if datasets_js[idx] == "{":
            depth += 1
        elif datasets_js[idx] == "}":
            depth -= 1
            if depth == 0:
                blob = datasets_js[start : idx + 1]
                break
    else:  # pragma: no cover - malformed upstream file
        raise ValueError("unterminated Datasets object")
    return _js_object_to_json(blob)  # type: ignore[return-value]


def _resolve_consts(factory_body: str, datasets: dict[str, dict]) -> dict[str, dict]:
    """`const Hudson = Datasets['Hudson_radar'];` -> {'Hudson': {...}}."""
    consts = {}
    for alias, key in re.findall(r"const\s+(\w+)\s*=\s*Datasets\[['\"]([^'\"]+)['\"]\]", factory_body):
        if key in datasets:
            consts[alias] = datasets[key]
    return consts


def _inline_const_refs(blob: str, consts: dict[str, dict]) -> str:
    """Replace `X.basepath + 'f.tab'` and `X.name` with their literal values."""
    for alias, dataset in consts.items():
        basepath = dataset.get("basepath", "")
        blob = re.sub(
            rf"\b{re.escape(alias)}\.basepath\s*\+\s*'([^']*)'",
            lambda m, base=basepath: json.dumps(base + m.group(1)),
            blob,
        )
        for field in ("name", "link", "basepath"):
            blob = re.sub(
                rf"\b{re.escape(alias)}\.{field}\b",
                json.dumps(dataset.get(field)),
                blob,
            )
    return blob


def parse_catalog(data_js: str, datasets_js: str) -> list[dict]:
    """Return one dict per object: {name, type, datasets: [...]}.

    `type` comes from the upstream record when present; entries that omit it
    (the catalog has a couple) fall back to the factory they were listed under,
    which is the same claim the source page makes visually.
    """
    datasets = parse_datasets(datasets_js)
    objects: list[dict] = []
    for factory in FACTORIES:
        match = re.search(rf"\.?factory\(\s*['\"]{factory}['\"]", data_js)
        if match is None:
            continue
        array_start = data_js.index("[", data_js.index("return", match.end()))
        blob = _balanced_array(data_js, array_start)
        consts = _resolve_consts(data_js[match.end() : array_start], datasets)
        parsed = _js_object_to_json(_inline_const_refs(blob, consts))
        fallback_type = {"Comets": "comet", "Asteroids": "asteroid", "Satellites": "satellite"}[factory]
        for entry in parsed:  # type: ignore[union-attr]
            entry.setdefault("type", fallback_type)
            entry["factory"] = factory
            objects.append(entry)
    return objects


# Where the catalog's derived meshes and previews actually live. Several entries
# are written against a base that 404s (or, for the ios previews, against no base
# at all), but the file itself is served from here under <parent>/<name> — so a
# failed URL is retried against this base before being reported as missing.
FALLBACK_BASE = "https://sbn.psi.edu/pds/shape-models/files/"


def dataset_dir_hints(objects: list[dict]) -> dict[str, list[str]]:
    """Per dataset, the `files/<dir>/` folders its working links actually use.

    Entries in one dataset share a folder ("RADAR", "SATURN_SMALL_MOONS", ...),
    but only some of them spell it out: the rest point at the PDS archive host,
    whose own directory name ("data") says nothing about where the derived mesh
    lives. Collecting the folder from the entries that do get it right is what
    lets the broken ones be retried in the right place, instead of guessing.
    """
    import re

    # links appear both relative ("shape-models/files/RADAR/x.obj") and absolute
    pattern = re.compile(r"shape-models/files/([^/\"]+)/")
    hints: dict[str, list[str]] = {}
    for entry in objects:
        for dataset in entry.get("datasets") or []:
            name = dataset.get("name") or ""
            for match in pattern.finditer(json.dumps(dataset)):
                folder = match.group(1)
                hints.setdefault(name, [])
                if folder not in hints[name]:
                    hints[name].append(folder)
    return hints


def fallback_urls(link: str, dir_hints: list[str] | None = None) -> list[str]:
    """Candidate URLs for a link that did not serve a file at its written form."""
    from urllib.parse import urlparse

    parts = [p for p in urlparse(link).path.split("/") if p]
    if not parts:
        return []
    name = parts[-1]
    candidates = [FALLBACK_BASE + f"{folder}/{name}" for folder in dir_hints or []]
    if len(parts) >= 2:
        candidates.append(FALLBACK_BASE + f"{parts[-2]}/{name}")
    candidates.append(FALLBACK_BASE + name)
    return [c for i, c in enumerate(candidates) if c not in candidates[:i] and c != link]


def catalog_file_urls(entry: dict, base_url: str,
                      dir_hints: dict[str, list[str]] | None = None) -> list[dict]:
    """Flatten one catalog entry into downloadable {url, role, format} records."""
    from urllib.parse import urljoin

    out: list[dict] = []
    for dataset in entry.get("datasets") or []:
        hints = (dir_hints or {}).get(dataset.get("name") or "", [])
        files = dataset.get("files") or {}
        data = files.get("data") or {}
        previews = files.get("previews") or {}
        candidates = [("primary", data.get("primary"))]
        for derived in data.get("derived") or []:
            candidates.append(("derived", derived))
        for name, preview in (previews or {}).items():
            candidates.append((f"preview_{name}", preview))
        for role, spec in candidates:
            if not spec:
                continue
            link = spec.get("downloadLink") or spec.get("path")
            if not link:
                continue
            if _UNRESOLVED_CONST.match(link) or '"' in link:
                out.append({
                    "url": None,
                    "broken_upstream": link,
                    "fallback_urls": fallback_urls(link.replace('"', ""), hints),
                    "role": role,
                    "format": (spec.get("fileFormat") or spec.get("fileformat") or "").upper(),
                    "dataset_name": dataset.get("name"),
                    "dataset_link": dataset.get("link"),
                })
                continue
            resolved = urljoin(base_url, link)
            out.append({
                "url": resolved,
                "fallback_urls": fallback_urls(resolved, hints),
                "role": role,
                "format": (spec.get("fileFormat") or spec.get("fileformat") or link.rsplit(".", 1)[-1]).upper(),
                "dataset_name": dataset.get("name"),
                "dataset_link": dataset.get("link"),
            })
    return out
