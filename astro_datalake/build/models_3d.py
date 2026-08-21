"""Fase 8 builder: data/models_3d/ — mesh + tekstur per objek.

Sumber (semua sudah ditarik lebih dulu ke data/raw/, builder ini tidak
menyentuh jaringan):

  nasa_3d_resources          '3D Models' / '3D Printing' / 'Images and Textures'
  nasa_science_3d            STL cetak + deskripsi per model dari science.nasa.gov
  pds_sbn_shape_models       shape model komet/asteroid/satelit (OBJ/WRL/TAB/DSK)
  damit_shape_models         export lengkap DAMIT (tar.gz, ribuan model asteroid)
  nasa_svs_texture_kits      CGI Moon Kit (peta warna + displacement)
  nasa_blue_marble_textures  tekstur Bumi Blue Marble

File aset di-hardlink dari data/raw/ (bukan disalin): isinya identik dan
raw-nya tidak pernah ditimpa, jadi hardlink menghemat beberapa GB. Kalau
hardlink gagal (beda filesystem), file disalin.

Pengelompokan kategori: untuk sumber yang MEMANG punya kolom tipe objek
(PDS SBN: comet/asteroid/satellite) tipe itu dipakai apa adanya. Untuk
katalog NASA yang cuma punya nama folder, kategori ditebak dari aturan
regex di CATEGORY_RULES di bawah — tebakan itu ditulis eksplisit di
`classified_by` tiap model_3d.json supaya bisa dicek/diperbaiki, bukan
disamarkan sebagai fakta dari sumber.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import tarfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .common import (
    BuildReport,
    attribution_block,
    write_category_index,
    write_json,
    write_metadata,
    write_text,
)
from ..core.cache import sha256_of_file
from ..core.naming import slugify

MESH_SUFFIXES = {
    ".obj", ".stl", ".glb", ".gltf", ".fbx", ".dae", ".3ds", ".blend", ".lwo",
    ".wrl", ".x3d", ".ply", ".usdz", ".bds", ".dsk", ".tab", ".icq", ".fff", ".vsp3",
}
TEXTURE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".webp"}
ARCHIVE_SUFFIXES = {".7z", ".zip", ".gz", ".tar"}
DOC_SUFFIXES = {".txt", ".pdf", ".md", ".pptx", ".html", ".json"}

# Urutan penting: aturan pertama yang cocok yang dipakai.
CATEGORY_RULES: list[tuple[str, str]] = [
    # Fitur permukaan lebih dulu: "Vesta - Rheasilvia" itu kawah di Vesta, bukan
    # model asteroid Vesta; "Moon - Tycho" itu kawah, bukan model Bulan.
    ("surface_features",
     r"landing site|rover path|\bcrater\b|\brille\b|valles marineris|tharsis|pahrump|"
     r"mount hadley|aristarchus|copernicus|gassendi|\blinne\b|victoria|rheasilvia|numisia|"
     r"snowman|block island|bootprint|southern sea|gale\b|cambridge bay|apollo \d+ view|"
     r"^(?:moon|mars|vesta) - (?!lunar color|lunar terrain|lunar far side|phobos|deimos)"),
    ("comets", r"\bcomet\b|churyumov|tempel|hartley|halley|wild ?2|borrelly|hyakutake|"
               r"^\d+p\b|^\d+p/"),
    ("asteroids", r"\basteroid\b(?! redirection)|\bbennu\b|\bryugu\b|itokawa|\beros\b|\bvesta\b|\bceres\b|"
                  r"toutatis|golevka|kleopatra|geographos|mithra|apophis|arrokoth|\bida\b|"
                  r"mathilde|gaspra|lutetia|steins|castalia|bacchus|1999 rq36|1998 kw4|"
                  r"\bnereus\b|\byorp\b|ra-shalom|didymos|dimorphos|^\d+ [a-z]"),
    ("sky_maps", r"star map|hipparcos|tycho star|yale bright"),
    ("deep_sky", r"supernova|\bnebula\b|\bgalaxy\b|pillars of creation|\bngc ?\d|\bic ?\d{2,}|"
                 r"\bsn ?\d{4}|westerlund|homunculus|jellyfish|whirlpool|\bcrab\b|cygnus loop|"
                 r"cassiopeia a|g292|star cluster"),
    ("stars", r"\bbp tauri\b|\bdg tau\b|\bu scorpii\b|^the sun$|^sun$|solar surface|sunspot"),
    ("moons", r"^moon$|^moon - lunar (?:color|terrain|far side)|\bphobos\b|\bdeimos\b|"
              r" - io\b|europa(?! orbiter)|ganymede|callisto|titan(?! sub)|enceladus|mimas|"
              r"tethys|dione|rhea(?!silvia)|iapetus|phoebe|triton|charon|miranda|ariel|"
              r"umbriel|oberon|titania|amalthea|janus|epimetheus|hyperion|helene|calypso|"
              r"telesto|pandora|prometheus"),
    ("earth_science", r"hurricane|eclipse \d{4}|typhoon|wildfire"),
    ("planets", r"^earth(?:\s*\(|$)|^mars$|^jupiter$|^saturn$|^uranus\b|^neptune$|^venus$|^mercury$|"
                r"^pluto$|^pluto\b"),
    ("ground_and_equipment",
     r"\bdish\b|antenna$|deep space network|deep space station|building|\bgantry\b|crawler|\bhammer\b|wrench|ratchet|grease gun|"
     r"pistol grip|\bhelmet\b|spacesuit|\bsuit\b|\bglove\b|\btether\b|\bradome\b|\bfablab\b|"
     r"mission control|mobile launcher|\btool\b|\btools\b|insignia|medallion|emblem|"
     r"crew lock bag|panels|\bastronaut\b|robonaut|habitat|base station|vehicle assembly|"
     r"flight deck|orbital replacement unit"),
]

SPACECRAFT_FALLBACK = "spacecraft"

# Suffix varian yang di-strip supaya '... (A)' dan '... (B)' jatuh ke satu objek.
VARIANT_SUFFIX = re.compile(r"\s*\((?:[A-Z]|\d{4}|High Res|Detailed|Simplified|Mirror|"
                            r"Internal|IGOAL|Retrograde|Prograde)\)\s*$", re.IGNORECASE)
NOISE_PREFIX = re.compile(r"^(asteroid|comet)\s+", re.IGNORECASE)

SOURCE_META = {
    "nasa_3d_resources": {
        "name": "NASA 3D Resources",
        "url": "https://github.com/nasa/NASA-3D-Resources",
        "license": "Public domain / NASA Open Source Agreement v1.3",
        "attribution": "NASA 3D Resources (github.com/nasa/NASA-3D-Resources)",
    },
    "nasa_science_3d": {
        "name": "NASA Science 3D Resources",
        "url": "https://science.nasa.gov/3d-resources/",
        "license": "Public domain (NASA)",
        "attribution": "NASA Science 3D Resources (science.nasa.gov/3d-resources)",
    },
    "pds_sbn_shape_models": {
        "name": "PDS Small Bodies Node shape models",
        "url": "https://sbn.psi.edu/pds/shape-models/",
        "license": "Public domain (NASA PDS)",
        "attribution": "NASA PDS Small Bodies Node — lihat dataset_link tiap file untuk "
                       "referensi model aslinya",
    },
    "damit_shape_models": {
        "name": "DAMIT",
        "url": "https://damit.cuni.cz/projects/damit/",
        "license": "CC BY 4.0",
        "attribution": "DAMIT (Durech, Sidorin & Kaasalainen), damit.cuni.cz — CC BY 4.0",
    },
    "nasa_svs_texture_kits": {
        "name": "NASA SVS CGI texture kits",
        "url": "https://svs.gsfc.nasa.gov/4720/",
        "license": "Public domain (NASA/GSFC SVS)",
        "attribution": "NASA's Scientific Visualization Studio",
    },
    "nasa_blue_marble_textures": {
        "name": "NASA Earth Observatory — Blue Marble",
        "url": "https://science.nasa.gov/earth/earth-observatory/collections/blue-marble/",
        "license": "Public domain (NASA Earth Observatory)",
        "attribution": "NASA Earth Observatory",
    },
}


def file_role(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in MESH_SUFFIXES:
        return "mesh"
    if suffix in TEXTURE_SUFFIXES:
        return "texture"
    if suffix in ARCHIVE_SUFFIXES:
        return "archive"
    if suffix in DOC_SUFFIXES:
        return "doc"
    return "other"


def normalize_name(name: str) -> tuple[str, str | None]:
    """('Hubble Space Telescope (A)') -> ('Hubble Space Telescope', 'A')."""
    variant = None
    match = VARIANT_SUFFIX.search(name)
    while match:
        variant = match.group(0).strip().strip("()") if variant is None else variant
        name = name[: match.start()].rstrip()
        match = VARIANT_SUFFIX.search(name)
    return name, variant


def object_key(name: str, category: str) -> str:
    """Slug used to merge the same object across sources."""
    base = name
    if category in {"asteroids", "comets"}:
        base = NOISE_PREFIX.sub("", base)
    base = base.replace("/", " ").replace("–", " ").replace("—", " ").replace("-", " ")
    return slugify(base) or slugify(name) or "unnamed"


def classify(name: str) -> tuple[str, str]:
    lowered = name.lower()
    for category, pattern in CATEGORY_RULES:
        if re.search(pattern, lowered):
            return category, f"rule:{category}"
    return SPACECRAFT_FALLBACK, "fallback:spacecraft"


@dataclass
class ModelObject:
    display_name: str
    category: str
    classified_by: str
    files: list[dict] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)
    descriptions: list[dict] = field(default_factory=list)
    object_type: str | None = None

    def add_file(self, path: Path, source_key: str, **extra) -> None:
        self.files.append({"src": path, "source": source_key, **extra})
        self.sources.add(source_key)


def _latest(raw_root: Path, key: str) -> Path | None:
    base = raw_root / key
    if not base.exists():
        return None
    dated = sorted((p for p in base.iterdir() if p.is_dir()), reverse=True)
    return dated[0] if dated else None


def _link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


# ---------------------------------------------------------------------------
# collectors: raw tree -> {object_key: ModelObject}
# ---------------------------------------------------------------------------
NASA_REPO_DIRS = {
    "3D Models": "model",
    "3D Printing": "printable",
    "Images and Textures": "texture",
}


def collect_nasa_repo(raw_root: Path, objects: dict[str, ModelObject], report: BuildReport) -> None:
    root = _latest(raw_root, "nasa_3d_resources")
    if root is None:
        report.note("nasa_3d_resources belum ditarik — dilewati")
        return
    repo = root / "NASA-3D-Resources"
    if not repo.exists():
        report.note(f"{repo} tidak ada — pull nasa_3d_resources belum selesai?")
        return
    for section, collection in NASA_REPO_DIRS.items():
        section_dir = repo / section
        if not section_dir.exists():
            continue
        for entry in sorted(p for p in section_dir.iterdir() if p.is_dir()):
            display, variant = normalize_name(entry.name)
            category, how = classify(entry.name)
            key = object_key(display, category)
            obj = objects.setdefault(key, ModelObject(display, category, how))
            for path in sorted(entry.rglob("*")):
                if path.is_file():
                    obj.add_file(path, "nasa_3d_resources", collection=collection,
                                 variant=variant, upstream_folder=f"{section}/{entry.name}")


def collect_nasa_science(raw_root: Path, objects: dict[str, ModelObject], report: BuildReport) -> None:
    root = _latest(raw_root, "nasa_science_3d")
    if root is None:
        report.note("nasa_science_3d belum ditarik — dilewati")
        return
    items_dir = root / "items"
    if not items_dir.exists():
        return
    for entry in sorted(p for p in items_dir.iterdir() if p.is_dir()):
        item_file = entry / "item.json"
        if not item_file.exists():
            continue
        item = json.loads(item_file.read_text())
        # titles come out of WordPress HTML-escaped ("Spirit &#8211; Opportunity")
        title = html.unescape(item.get("title") or entry.name)
        display, variant = normalize_name(title)
        category, how = classify(title)
        key = object_key(display, category)
        obj = objects.setdefault(key, ModelObject(display, category, how))
        obj.descriptions.append({
            "source": "nasa_science_3d",
            "url": item.get("permalink"),
            "excerpt": _strip_html(item.get("excerpt") or ""),
        })
        for path in sorted(entry.iterdir()):
            if path.is_file() and path.name not in {"item.json", "page.html"} and path.suffix != ".sha256":
                obj.add_file(path, "nasa_science_3d", collection="printable", variant=variant)


def collect_sbn(raw_root: Path, objects: dict[str, ModelObject], report: BuildReport) -> None:
    root = _latest(raw_root, "pds_sbn_shape_models")
    if root is None:
        report.note("pds_sbn_shape_models belum ditarik — dilewati")
        return
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        report.note("manifest.json pds_sbn_shape_models tidak ada — pull belum selesai?")
        return
    manifest = json.loads(manifest_path.read_text())
    type_to_category = {"comet": "comets", "asteroid": "asteroids", "satellite": "moons"}
    for record in manifest.get("files", []):
        name = record.get("object")
        if not name:
            continue
        category = type_to_category.get(record.get("object_type", ""), "other")
        display, _ = normalize_name(name)
        key = object_key(display, category)
        obj = objects.setdefault(key, ModelObject(display, category, "source:pds_sbn_type"))
        obj.object_type = record.get("object_type")
        # tipe dari sumber selalu menang atas tebakan regex
        obj.category = category
        obj.classified_by = "source:pds_sbn_type"
        obj.add_file(root / record["path"], "pds_sbn_shape_models", collection="shape_model",
                     role_hint=record.get("role"), dataset=record.get("dataset"),
                     source_url=record.get("source_url"))


def collect_texture_source(raw_root: Path, key: str, objects: dict[str, ModelObject],
                           report: BuildReport, *, display_name: str, category: str) -> None:
    root = _latest(raw_root, key)
    if root is None:
        report.note(f"{key} belum ditarik — dilewati")
        return
    obj_key = object_key(display_name, category)
    obj = objects.setdefault(obj_key, ModelObject(display_name, category, f"source:{key}"))
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in TEXTURE_SUFFIXES:
            obj.add_file(path, key, collection="texture")


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


# ---------------------------------------------------------------------------
# DAMIT: one tar.gz -> asteroids/_damit/
# ---------------------------------------------------------------------------
DAMIT_KEEP_NAMES = {"shape.txt", "obj.txt", "spin.txt", "shape.png", "IAUspin", "IAUspin.txt"}


def _damit_wanted(name: str) -> bool:
    """Model files only.

    The export also ships lightcurve data and per-fit plots (lcfit_*.png, lc.txt,
    .avi animations) — those are the photometry the models were derived from, not
    the models, and they are ~2/3 of the 230k entries. They stay in the raw
    tarball under data/raw/; only the meshes, spin solutions, their rendered
    previews and the catalog tables get extracted here.
    """
    parts = Path(name).parts
    if len(parts) >= 2 and parts[0] == "tables":
        return name.endswith(".csv")
    return Path(name).name in DAMIT_KEEP_NAMES


def _damit_index(target: Path) -> dict:
    """damit asteroid id -> {number, name, models} from the export's own tables."""
    import csv

    asteroids_csv = target / "tables" / "asteroids.csv"
    if not asteroids_csv.exists():
        return {}
    rows = {}
    with asteroids_csv.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            rows[row["id"]] = {
                "damit_asteroid_id": row["id"],
                "number": row.get("number") or None,
                "name": row.get("name") or None,
                "designation": row.get("designation") or None,
                "models": [],
            }
    files_dir = target / "files"
    if files_dir.exists():
        for asteroid_dir in sorted(files_dir.iterdir()):
            if not asteroid_dir.is_dir() or not asteroid_dir.name.startswith("asteroid_"):
                continue
            damit_id = asteroid_dir.name.removeprefix("asteroid_")
            entry = rows.setdefault(damit_id, {
                "damit_asteroid_id": damit_id, "number": None, "name": None,
                "designation": None, "models": [],
            })
            for model_dir in sorted(asteroid_dir.iterdir()):
                if model_dir.is_dir():
                    entry["models"].append({
                        "path": str(model_dir.relative_to(target)),
                        "files": sorted(f.name for f in model_dir.iterdir() if f.is_file()),
                    })
    return {k: v for k, v in rows.items() if v["models"]}


def extract_damit(raw_root: Path, out_root: Path, report: BuildReport) -> int:
    root = _latest(raw_root, "damit_shape_models")
    if root is None:
        report.note("damit_shape_models belum ditarik — dilewati")
        return 0
    archives = sorted(root.glob("*.tar.gz"))
    if not archives:
        report.note("damit_shape_models: tidak ada .tar.gz di raw dir")
        return 0
    archive = archives[-1]
    target = out_root / "asteroids" / "_damit"
    marker = target / "extracted_from.json"
    if marker.exists():
        previous = json.loads(marker.read_text())
        if previous.get("archive") == archive.name:
            return int(previous.get("file_count", 0))

    target.mkdir(parents=True, exist_ok=True)
    count = 0
    top_level = None
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            parts = Path(member.name.lstrip("./")).parts
            if not parts or ".." in parts or Path(member.name).is_absolute():
                report.note(f"DAMIT: entri tar diabaikan (path tidak aman): {member.name}")
                continue
            top_level = top_level or parts[0]
            inner = str(Path(*parts[1:])) if len(parts) > 1 else parts[0]
            if not _damit_wanted(inner):
                continue
            dest = target / inner
            dest.parent.mkdir(parents=True, exist_ok=True)
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            with dest.open("wb") as fh:
                shutil.copyfileobj(extracted, fh)
            count += 1

    index = _damit_index(target)
    write_json(target / "index.json", {
        "asteroid_count": len(index),
        "model_count": sum(len(v["models"]) for v in index.values()),
        "asteroids": index,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })
    write_json(marker, {
        "archive": archive.name,
        "archive_dir": top_level,
        "archive_sha256": sha256_of_file(archive),
        "file_count": count,
        "kept": sorted(DAMIT_KEEP_NAMES) + ["tables/*.csv"],
        "source": "damit_shape_models",
        "source_url": SOURCE_META["damit_shape_models"]["url"],
        "license": SOURCE_META["damit_shape_models"]["license"],
        "attribution": SOURCE_META["damit_shape_models"]["attribution"],
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    })
    write_text(target / "README.md",
               "# DAMIT\n\n"
               f"{len(index)} asteroid, {sum(len(v['models']) for v in index.values())} model bentuk "
               "(inversi kurva cahaya). Tata letak asli dari upstream: "
               "`files/asteroid_<damit_id>/<model_id>/{obj.txt,shape.txt,spin.txt,shape.png}`, "
               "tabel katalognya di `tables/`. Pemetaan damit_id -> nomor/nama asteroid ada di "
               "`index.json`.\n\n"
               f"Lisensi: {SOURCE_META['damit_shape_models']['license']}. "
               f"Atribusi wajib: {SOURCE_META['damit_shape_models']['attribution']}.\n\n"
               "Kurva cahaya dan plot fit-nya tidak diekstrak ke sini (bukan model); "
               "arsip lengkapnya tetap ada di `data/raw/damit_shape_models/`.\n")
    return count


# ---------------------------------------------------------------------------
# bundled source archives (.7z)
# ---------------------------------------------------------------------------
def extract_bundle(archive: Path, target: Path) -> list[Path]:
    """Unpack a NASA .7z bundle next to the model it belongs to.

    Roughly a third of the 3D Models entries ship their working files as a .7z
    (LightWave/Maya/3ds Max scenes plus the JPG/TIF/TGA texture maps that go
    with them). Left packed, those textures are invisible to anything reading
    this tree, so they get unpacked into `<name>_extracted/` — the archive
    itself stays in place.
    """
    import py7zr

    marker = target / ".extracted_from.json"
    if marker.exists():
        try:
            if json.loads(marker.read_text()).get("sha256") == sha256_of_file(archive):
                return [p for p in sorted(target.rglob("*")) if p.is_file() and p != marker]
        except json.JSONDecodeError:
            pass

    target.mkdir(parents=True, exist_ok=True)
    with py7zr.SevenZipFile(archive, "r") as bundle:
        safe = []
        for name in bundle.getnames():
            parts = Path(name).parts
            if not parts or ".." in parts or Path(name).is_absolute():
                continue
            safe.append(name)
        bundle.extract(path=target, targets=safe)
    write_json(marker, {
        "archive": archive.name,
        "sha256": sha256_of_file(archive),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    })
    return [p for p in sorted(target.rglob("*")) if p.is_file() and p != marker]


# ---------------------------------------------------------------------------
# writer
# ---------------------------------------------------------------------------
def write_object(obj: ModelObject, out_root: Path) -> dict:
    folder = out_root / obj.category / object_key(obj.display_name, obj.category)
    folder.mkdir(parents=True, exist_ok=True)

    entries = []
    used: set[str] = set()
    for record in obj.files:
        src: Path = record["src"]
        if not src.exists():
            continue
        name = src.name
        stem, suffix = Path(name).stem, Path(name).suffix
        counter = 2
        while name in used:  # same filename from two sources
            name = f"{stem}__{counter}{suffix}"
            counter += 1
        used.add(name)
        dst = folder / name
        _link_or_copy(src, dst)
        entries.append({
            "file": name,
            "role": file_role(src),
            "format": suffix.lstrip(".").lower(),
            "size_bytes": dst.stat().st_size,
            "sha256": sha256_of_file(dst),
            "source": record["source"],
            "collection": record.get("collection"),
            "variant": record.get("variant"),
            "upstream_folder": record.get("upstream_folder"),
            "dataset": record.get("dataset"),
            "source_url": record.get("source_url") or SOURCE_META[record["source"]]["url"],
        })

    expected = {e["file"] for e in entries} | {"model_3d.json", "README.md"}
    for path in folder.iterdir():
        if path.is_file() and path.name not in expected:
            path.unlink()
        elif path.is_dir() and path.name.endswith("_extracted"):
            archive = f"{path.name[: -len('_extracted')]}.7z"
            if archive not in expected:
                shutil.rmtree(path)

    for entry in list(entries):
        if entry["role"] != "archive" or entry["format"] != "7z":
            continue
        bundle_dir = folder / f"{Path(entry['file']).stem}_extracted"
        try:
            unpacked = extract_bundle(folder / entry["file"], bundle_dir)
        except Exception as exc:  # noqa: BLE001 - a broken bundle must not kill the build
            entry["extract_error"] = f"{type(exc).__name__}: {exc}"
            continue
        entry["extracted_to"] = bundle_dir.name
        for path in unpacked:
            entries.append({
                "file": str(path.relative_to(folder)),
                "role": file_role(path),
                "format": path.suffix.lstrip(".").lower(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_of_file(path),
                "source": entry["source"],
                "collection": entry.get("collection"),
                "variant": entry.get("variant"),
                "upstream_folder": entry.get("upstream_folder"),
                "dataset": entry.get("dataset"),
                "from_archive": entry["file"],
                "source_url": entry["source_url"],
            })

    sources = [
        {"key": key, **{k: v for k, v in SOURCE_META[key].items() if k != "attribution"}}
        for key in sorted(obj.sources)
    ]
    payload = {
        "display_name": obj.display_name,
        "category": obj.category,
        "object_type": obj.object_type,
        "classified_by": obj.classified_by,
        "file_count": len(entries),
        "has_mesh": any(e["role"] == "mesh" for e in entries),
        "has_texture": any(e["role"] == "texture" for e in entries),
        "formats": sorted({e["format"] for e in entries}),
        "sources": sources,
        "descriptions": obj.descriptions,
        "files": entries,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(folder / "model_3d.json", payload)

    source_field = " + ".join(sorted(obj.sources))
    write_metadata(
        folder / "metadata.json",
        source=source_field,
        source_url=", ".join(s["url"] for s in sources),
        record_count=len(entries),
        classification_method=obj.classified_by,
    )

    lines = [
        f"# {obj.display_name}",
        "",
        f"Kategori: `{obj.category}` (ditentukan lewat `{obj.classified_by}`).",
        f"{len(entries)} file — "
        f"{sum(1 for e in entries if e['role'] == 'mesh')} mesh, "
        f"{sum(1 for e in entries if e['role'] == 'texture')} tekstur.",
    ]
    for desc in obj.descriptions:
        if desc.get("excerpt"):
            lines += ["", "## Deskripsi (dari sumber)", "", desc["excerpt"], "", f"<{desc.get('url')}>"]
    lines += ["", "## Cara pakai atribusinya", ""]
    lines += [f"- {SOURCE_META[key]['attribution']}" for key in sorted(obj.sources)]
    lines += ["", attribution_block([source_field])]
    write_text(folder / "README.md", "\n".join(lines))
    return payload


def build(raw_root: Path, out_root: Path) -> BuildReport:
    report = BuildReport(category="models_3d")
    objects: dict[str, ModelObject] = {}

    collect_nasa_repo(raw_root, objects, report)
    collect_nasa_science(raw_root, objects, report)
    collect_sbn(raw_root, objects, report)
    collect_texture_source(raw_root, "nasa_svs_texture_kits", objects, report,
                           display_name="Moon CGI texture kit", category="moons")
    collect_texture_source(raw_root, "nasa_blue_marble_textures", objects, report,
                           display_name="Earth Blue Marble", category="planets")

    if not objects:
        report.note("tidak ada sumber models_3d yang sudah ditarik — data/models_3d/ tidak dibangun")
        return report

    out_root.mkdir(parents=True, exist_ok=True)
    by_category: dict[str, list[dict]] = defaultdict(list)
    written_leaves: set[Path] = set()
    total_files = 0
    total_bytes = 0
    for obj in objects.values():
        leaf = out_root / obj.category / object_key(obj.display_name, obj.category)
        written_leaves.add(leaf)
        payload = write_object(obj, out_root)
        if payload["file_count"] == 0:
            # e.g. a science.nasa.gov page that only links a viewer, no files:
            # an object folder with nothing in it would just be noise
            shutil.rmtree(out_root / obj.category / object_key(obj.display_name, obj.category))
            continue
        total_files += payload["file_count"]
        total_bytes += sum(f["size_bytes"] for f in payload["files"])
        by_category[obj.category].append({
            "name": obj.display_name,
            "path": f"{obj.category}/{object_key(obj.display_name, obj.category)}",
            "file_count": payload["file_count"],
            "formats": payload["formats"],
            "has_mesh": payload["has_mesh"],
            "has_texture": payload["has_texture"],
            "sources": [s["key"] for s in payload["sources"]],
        })

    _prune_stale_leaves(out_root, written_leaves, by_category, report)

    damit_files = extract_damit(raw_root, out_root, report)

    for category, items in by_category.items():
        write_json(out_root / category / "index.json", {
            "category": category,
            "count": len(items),
            "objects": sorted(items, key=lambda i: i["name"]),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        })
        category_sources = sorted({key for item in items for key in item["sources"]})
        write_metadata(
            out_root / category / "metadata.json",
            source=" + ".join(category_sources),
            source_url=", ".join(SOURCE_META[key]["url"] for key in category_sources),
            record_count=len(items),
        )
        write_category_index(
            out_root / category,
            [item["path"].split("/", 1)[-1] for item in items],
            f"{len(items)} objek dengan model 3D dan/atau tekstur.",
            sources=[" + ".join(category_sources)],
        )

    write_json(out_root / "index.json", {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts": {c: len(v) for c, v in sorted(by_category.items())},
        "object_count": sum(len(v) for v in by_category.values()),
        "file_count": total_files,
        "bytes_total": total_bytes,
        "damit_extracted_files": damit_files,
    })
    write_text(out_root / "README.md", _root_readme(by_category, total_files, total_bytes, damit_files))

    report.object_count = sum(len(v) for v in by_category.values())
    return report


def _prune_stale_leaves(out_root: Path, written: set[Path], by_category: dict,
                        report: BuildReport) -> None:
    """Drop object folders a previous build wrote that this one no longer produces.

    The tree is always rebuilt from raw/, so anything not written this time (an
    object that got renamed, merged, or dropped) is stale. `_damit/` is left
    alone — it is unpacked from the archive, not derived from an object.
    """
    for category_dir in out_root.iterdir():
        if not category_dir.is_dir():
            continue
        for leaf in category_dir.iterdir():
            if not leaf.is_dir() or leaf in written or leaf.name.startswith("_"):
                continue
            shutil.rmtree(leaf)
            report.note(f"hapus folder usang dari build sebelumnya: "
                        f"{leaf.relative_to(out_root)}")
        if not any(category_dir.iterdir()) and category_dir.name not in by_category:
            category_dir.rmdir()


def _root_readme(by_category: dict[str, list[dict]], total_files: int, total_bytes: int,
                 damit_files: int) -> str:
    rows = "\n".join(
        f"| {category} | {len(items)} | {sum(i['file_count'] for i in items)} |"
        for category, items in sorted(by_category.items())
    )
    return f"""# models_3d

Model 3D (mesh) dan tekstur per objek. {sum(len(v) for v in by_category.values())} objek,
{total_files} file, {total_bytes / 1024 ** 3:.1f} GB (hardlink ke `data/raw/`, jadi tidak
menggandakan ruang disk).

| Kategori | Objek | File |
|---|---:|---:|
{rows}

Tiap folder objek berisi file aslinya apa adanya + `model_3d.json` (daftar file, format,
checksum, sumber, lisensi) + `README.md` (atribusi).

`asteroids/_damit/` adalah hasil ekstraksi export lengkap DAMIT ({damit_files} file):
ribuan model bentuk asteroid hasil inversi kurva cahaya, dengan tata letak asli dari
upstream (CC BY 4.0, atribusi wajib ke DAMIT).

Kategori untuk sumber PDS SBN diambil dari kolom tipe objek di katalognya. Untuk katalog
NASA 3D Resources yang hanya punya nama folder, kategori ditebak dengan aturan regex di
`astro_datalake/build/models_3d.py`; tebakan itu ditulis di field `classified_by` tiap
`model_3d.json` — jangan diperlakukan sebagai klasifikasi resmi dari NASA.
"""
