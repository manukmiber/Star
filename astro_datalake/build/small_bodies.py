"""Fase 3 builder: solar_system/small_bodies/ from JPL SBDB (data/raw/
sbdb_query_neo/ + sbdb_query_full/). Each SBDB `class` code maps 1:1 to a
real API-verified orbit class (see registry.py notes), which drives the
category folders below. Objects with a populated `name` field get their
own leaf folder under named/.

Known gaps (documented, not guessed): SBDB's classes don't carry the
finer structure the brief's tree names — asteroid family membership
(_by_family/vesta,eos,...), Jupiter-trojan L4/L5 split, and TNO dynamical
subclass (classical/plutino/resonant/scattered/detached) all need
specialized orbital analysis or a different catalog (e.g. AstDyS family
proper elements) that wasn't pulled. comets/short_period vs long_period
IS derived here, from a Keplerian P = a^1.5 (yr, a in AU) estimate on
each comet's own semi-major axis — a standard heliocentric-orbit formula,
not a guess at the object's actual measured period. meteor_showers/ has
no source pulled at all and is left empty.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from .common import BuildReport, latest_raw_file, write_category_index, write_category_table, write_json, write_metadata, write_text
from ..core.naming import numbered_asteroid_slug, slugify

CLASS_TO_BUCKET = {
    "IEO": ("near_earth", "atira"),
    "ATE": ("near_earth", "aten"),
    "APO": ("near_earth", "apollo"),
    "AMO": ("near_earth", "amor"),
    "MBA": ("asteroid_belt", "main_belt"),
    "IMB": ("asteroid_belt", "inner_belt"),
    "OMB": ("asteroid_belt", "outer_belt"),
    "MCA": ("asteroid_belt", "mars_crossing"),
    "AST": ("asteroid_belt", "unclassified"),
    "TJN": ("trojans", "jupiter_all"),
    "CEN": ("centaurs", "all"),
    "TNO": ("trans_neptunian", "tno_all"),
    "HTC": ("comets", "halley_type"),
    "JFC": ("comets", "jupiter_family"),
    "ETc": ("comets", "other"),
}

COMET_CLASSES = {"HTC", "JFC", "ETc"}


def _load_class_file(raw_root: Path, key: str, cls: str) -> pl.DataFrame | None:
    p = latest_raw_file(raw_root, key, f"{cls}.json")
    if p is None:
        return None
    payload = json.loads(p.read_text())
    fields = payload["fields"]
    rows = payload["data"]
    if not rows:
        return None
    return pl.DataFrame(rows, schema=fields, orient="row")


def _num(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _asteroid_json(row: dict) -> dict:
    return {
        "display_name": (row.get("name") or row.get("full_name") or "").strip(),
        "full_name": (row.get("full_name") or "").strip(),
        "spkid": row.get("spkid"),
        "designation": row.get("pdes"),
        "orbit_class": row.get("class"),
        "is_neo": row.get("neo") == "Y",
        "is_pha": row.get("pha") == "Y",
        "semi_major_axis_au": _num(row.get("a")),
        "eccentricity": _num(row.get("e")),
        "inclination_deg": _num(row.get("i")),
        "ascending_node_deg": _num(row.get("om")),
        "arg_perihelion_deg": _num(row.get("w")),
        "mean_anomaly_deg": _num(row.get("ma")),
        "epoch_jd": _num(row.get("epoch")),
        "absolute_magnitude_h": _num(row.get("H")),
        "diameter_km": _num(row.get("diameter")),
        "albedo": _num(row.get("albedo")),
        "data_source": "jpl_sbdb_query",
    }


def build(raw_root: Path, out_root: Path) -> BuildReport:
    report = BuildReport(category="small_bodies")

    all_frames: dict[str, pl.DataFrame] = {}
    for key in ("sbdb_query_neo", "sbdb_query_full"):
        base = raw_root / key
        if not base.exists():
            continue
        dated = sorted((p for p in base.iterdir() if p.is_dir()), reverse=True)
        if not dated:
            continue
        for f in dated[0].glob("*.json"):
            cls = f.stem
            df = _load_class_file(raw_root, key, cls)
            if df is not None:
                all_frames[cls] = df
                report.object_count += df.height

    # Category buckets (asteroid_belt, near_earth, trojans, centaurs, trans_neptunian, comets/*)
    bucket_children: dict[str, list[str]] = {}
    for cls, (top, sub) in CLASS_TO_BUCKET.items():
        df = all_frames.get(cls)
        if df is None:
            continue
        dir_path = out_root / top / sub
        write_category_table(dir_path, df)
        write_metadata(dir_path / "metadata.json", source="jpl_sbdb_query", source_url="https://ssd-api.jpl.nasa.gov/sbdb_query.api", record_count=df.height)
        write_text(dir_path / "README.md", f"# {sub}\n\n{df.height} objek kelas SBDB `{cls}`.\n")
        bucket_children.setdefault(top, []).append(sub)

    for top, children in bucket_children.items():
        write_category_index(out_root / top, children, f"Dikelompokkan langsung dari kolom `class` SBDB ({top}).")

    # comets/short_period vs long_period (derived P = a^1.5 yr, a in AU)
    comet_frames = [all_frames[c] for c in COMET_CLASSES if c in all_frames]
    if comet_frames:
        comets = pl.concat(comet_frames, how="diagonal_relaxed").with_columns(
            pl.col("a").cast(pl.Float64, strict=False).alias("_a_au")
        ).with_columns((pl.col("_a_au") ** 1.5).alias("_period_yr_est"))
        short_period = comets.filter(pl.col("_period_yr_est") < 200).drop(["_a_au", "_period_yr_est"])
        long_period = comets.filter(pl.col("_period_yr_est") >= 200).drop(["_a_au", "_period_yr_est"])
        for name, df in [("short_period", short_period), ("long_period", long_period)]:
            dir_path = out_root / "comets" / name
            write_category_table(dir_path, df)
            write_metadata(dir_path / "metadata.json", source="jpl_sbdb_query (derived)", source_url="https://ssd-api.jpl.nasa.gov/sbdb_query.api", record_count=df.height)
            write_text(dir_path / "README.md", f"# {name}\n\n{df.height} komet, dari estimasi periode P=a^1.5 tahun (a dalam AU) atas gabungan kelas HTC+JFC+ETc.\n")
    write_text(out_root / "comets" / "interstellar" / "README.md", "# interstellar\n\nBelum dibangun: butuh query SBDB kelas hiperbolik (e>1) yang belum ditarik.\n")
    write_text(out_root / "meteor_showers" / "README.md", "# meteor_showers\n\nBelum dibangun: tidak ada sumber data meteor shower yang ditarik di Fase 2.\n")
    write_text(out_root / "asteroid_belt" / "_by_family" / "README.md", "# _by_family\n\nBelum dibangun: keanggotaan famili asteroid (Vesta/Eos/Koronis/...) butuh proper elements dari katalog khusus (mis. AstDyS), tidak ada di data SBDB yang ditarik.\n")
    write_text(out_root / "trojans" / "_l4_l5_split_not_built" / "README.md", "# L4/L5 split\n\nBelum dibangun: SBDB class TJN tidak membedakan L4/L5, butuh analisis posisi relatif ke Jupiter.\n")

    # named/<slug>/ — every object across all classes with a populated `name`
    named_dir = out_root / "named"
    named_slugs = []
    for cls, df in all_frames.items():
        if "name" not in df.columns:
            continue
        named = df.filter(pl.col("name").is_not_null() & (pl.col("name") != ""))
        for row in named.iter_rows(named=True):
            pdes = (row.get("pdes") or "").strip()
            name = row["name"].strip()
            slug = numbered_asteroid_slug(int(pdes), name) if pdes.isdigit() else slugify(name)
            if slug in named_slugs:
                slug = f"{slug}__{cls.lower()}"
            named_slugs.append(slug)
            obj_dir = named_dir / slug
            write_json(obj_dir / "asteroid.json", _asteroid_json(row))
            write_metadata(obj_dir / "metadata.json", source="jpl_sbdb_query", source_url="https://ssd-api.jpl.nasa.gov/sbdb_query.api")
            write_text(obj_dir / "README.md", f"# {name}\n\nKelas orbit SBDB: {cls}. {row.get('full_name', '').strip()}\n")

    write_category_index(named_dir, named_slugs, f"{len(named_slugs)} objek bernama lintas seluruh kelas SBDB yang ditarik.")
    report.object_count += len(named_slugs)

    report.note(
        "Belum dibangun (butuh sumber/analisis tambahan): asteroid_belt/_by_family, "
        "trojans L4/L5 split, trans_neptunian dynamical subclass (classical/plutino/"
        "resonant/scattered/detached), comets/interstellar, meteor_showers."
    )
    return report
