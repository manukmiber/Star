"""Fase 3 builder: solar_system/small_bodies/ from JPL SBDB (data/raw/
sbdb_query_neo/ + sbdb_query_full/). Each SBDB `class` code maps 1:1 to a
real API-verified orbit class (see registry.py notes), which drives the
category folders below. Objects with a populated `name` field get their
own leaf folder under named/.

comets/short_period vs long_period is derived here, from a Keplerian
P = a^1.5 (yr, a in AU) estimate on each comet's own semi-major axis — a
standard heliocentric-orbit formula, not a guess at the object's actual
measured period.

Fase 5 adds four more of the brief's sub-trees, all from data now in raw/:

- trojans/{l4,l5}: exact geometry. Mean longitude L = Omega + omega + M for
  the asteroid, the same for Jupiter (JPL Horizons elements at the SBDB
  reference epoch, propagated by Jupiter's own mean motion when an
  asteroid's epoch differs), and L4 is the leading half of the orbit.
  Validated against the archetypes: Achilles, Hektor, Agamemnon, Odysseus
  and Diomedes come out L4; Patroclus and Priamus come out L5.
- trans_neptunian/{classical,resonant,scattered,detached,inner_belt}:
  APPROXIMATE. Resonance membership properly requires integrating the
  resonant argument; these are (a, q, e, i) cuts around Neptune's
  mean-motion resonances, labelled approximate in every metadata.json.
- comets/interstellar: SBDB's hyperbolic/parabolic classes, split into the
  objects carrying an IAU interstellar designation (1I, 2I, 3I) and the
  rest — a hyperbolic osculating orbit alone does not make a comet
  interstellar.
- meteor_showers: the IAU Meteor Data Center shower list, one folder per
  established shower.

Still not built, and still for the same reason: asteroid_belt/_by_family
needs proper elements from a family catalogue (AstDyS/Nesvorny) that was
not pulled.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import polars as pl

from . import classify
from .common import (
    BuildReport,
    latest_raw_file,
    write_category_index,
    write_category_table,
    write_json,
    write_metadata,
    write_readme,
    write_text,
)
from ..core.naming import numbered_asteroid_slug, slugify

SBDB_URL = "https://ssd-api.jpl.nasa.gov/sbdb_query.api"
HORIZONS_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"
MDC_URL = "https://www.ta3.sk/IAUC22DB/MDC2022/"

# The IAU's interstellar objects, keyed by the primary designation SBDB
# actually stores. SBDB never uses the "I" designations in its own fields
# (verified 2026-08-20 — see registry.py notes on sbdb_query_hyperbolic), so
# the bridge between the two naming systems has to be written down. This is
# the IAU/MPC naming, not a classification of our own: extend it when a 4I
# is announced.
IAU_INTERSTELLAR_OBJECTS = {
    "2017 U1": "1I/'Oumuamua",
    "2019 Q4": "2I/Borisov",
    "2025 N1": "3I/ATLAS",
}

# Eccentricity above which a heliocentric orbit carries more excess speed
# than planetary perturbation of an Oort-cloud comet plausibly explains.
# Not a definition of "interstellar" — a shortlist worth looking at.
STRONGLY_HYPERBOLIC_ECCENTRICITY = 1.05

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
    # infer_schema_length=None scans every row: SBDB sends all values as JSON
    # strings except spkid, and a column that looks numeric for the first
    # thousand rows can still hold "Great comet" further down.
    return pl.DataFrame(rows, schema=fields, orient="row", infer_schema_length=None)


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
    # Which registry key each orbit class came from, so metadata.json (and the
    # attribution stamped from it) names the source that was actually pulled
    # rather than a generic "jpl_sbdb_query".
    source_of_class: dict[str, str] = {}
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
                source_of_class[cls] = key
                report.object_count += df.height

    # Category buckets (asteroid_belt, near_earth, trojans, centaurs, trans_neptunian, comets/*)
    bucket_children: dict[str, list[str]] = {}
    for cls, (top, sub) in CLASS_TO_BUCKET.items():
        df = all_frames.get(cls)
        if df is None:
            continue
        dir_path = out_root / top / sub
        write_category_table(dir_path, df)
        write_metadata(dir_path / "metadata.json", source=source_of_class[cls], source_url=SBDB_URL, record_count=df.height)
        write_readme(dir_path, sub, f"{df.height} objek kelas SBDB `{cls}`.", [source_of_class[cls]])
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
            comet_sources = sorted({source_of_class[c] for c in COMET_CLASSES if c in all_frames})
            write_metadata(
                dir_path / "metadata.json",
                source=" + ".join(comet_sources),
                source_url=SBDB_URL,
                record_count=df.height,
                derived_from=["a"],
                classification_method="estimasi periode Kepler P = a^1.5 tahun (a dalam AU) "
                "atas gabungan kelas HTC+JFC+ETc; ambang 200 tahun",
            )
            write_readme(
                dir_path,
                name,
                f"{df.height} komet, dari estimasi periode P=a^1.5 tahun (a dalam AU) atas "
                "gabungan kelas HTC+JFC+ETc.",
                comet_sources,
            )
    _build_interstellar(raw_root, out_root, report)
    _build_meteor_showers(raw_root, out_root, report)
    _build_trojan_camps(
        raw_root, out_root, all_frames.get("TJN"), report,
        source_of_class.get("TJN", "sbdb_query_full"),
    )
    _build_tno_subclasses(
        raw_root, out_root, all_frames.get("TNO"), report,
        source_of_class.get("TNO", "sbdb_query_full"),
    )

    write_text(out_root / "asteroid_belt" / "_by_family" / "README.md", "# _by_family\n\nBelum dibangun: keanggotaan famili asteroid (Vesta/Eos/Koronis/...) butuh proper elements dari katalog khusus (mis. AstDyS), tidak ada di data SBDB yang ditarik.\n")

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
            write_metadata(obj_dir / "metadata.json", source=source_of_class[cls], source_url=SBDB_URL)
            write_readme(
                obj_dir,
                name,
                f"Kelas orbit SBDB: {cls}. {row.get('full_name', '').strip()}",
                [source_of_class[cls]],
            )

    write_category_index(named_dir, named_slugs, f"{len(named_slugs)} objek bernama lintas seluruh kelas SBDB yang ditarik.")
    report.object_count += len(named_slugs)

    report.note("Belum dibangun: asteroid_belt/_by_family (butuh proper elements AstDyS/Nesvorny)")
    return report


# ---------------------------------------------------------------------------
# Fase 5 sub-trees
# ---------------------------------------------------------------------------

_HORIZONS_ELEMENT_KEYS = ("EC", "QR", "IN", "OM", "W", "N", "MA", "A", "PR")


def _parse_horizons_elements(path: Path) -> dict[str, float] | None:
    """Pull the element block out of a Horizons ELEMENTS text response.

    The block is fixed-format `KEY= value` pairs between $$SOE and $$EOE,
    preceded by the epoch line, e.g. `2461200.500000000 = A.D. 2026-Jun-09`.
    """
    text = path.read_text(errors="replace")
    if "$$SOE" not in text or "$$EOE" not in text:
        return None
    block = text.split("$$SOE", 1)[1].split("$$EOE", 1)[0]
    values: dict[str, float] = {}
    epoch_match = re.search(r"^\s*([0-9.]+)\s*=\s*A\.D\.", block, re.MULTILINE)
    if epoch_match:
        values["epoch_jd"] = float(epoch_match.group(1))
    for key in _HORIZONS_ELEMENT_KEYS:
        match = re.search(rf"\b{key}\s*=\s*([-+0-9.Ee]+)", block)
        if match:
            values[key] = float(match.group(1))
    return values or None


def _giant_planet_elements(raw_root: Path, stem: str) -> dict[str, float] | None:
    path = latest_raw_file(raw_root, "jpl_horizons_elements", f"{stem}.txt")
    return _parse_horizons_elements(path) if path else None


def _floats(df: pl.DataFrame, columns: list[str]) -> pl.DataFrame:
    return df.with_columns([pl.col(c).cast(pl.Float64, strict=False).alias(f"_{c}") for c in columns])


def _build_trojan_camps(
    raw_root: Path,
    out_root: Path,
    tjn: pl.DataFrame | None,
    report: BuildReport,
    source_key: str = "sbdb_query_full",
) -> None:
    """trojans/{l4,l5} from mean longitude relative to Jupiter's."""
    target_root = out_root / "trojans"
    jupiter = _giant_planet_elements(raw_root, "jupiter_barycenter")
    if tjn is None or jupiter is None or "epoch_jd" not in jupiter:
        write_readme(
            target_root / "l4",
            "l4",
            "Belum terisi: butuh `astro pull sbdb_query_full` dan "
            "`astro pull jpl_horizons_elements` lebih dulu.",
            [source_key, "jpl_horizons_elements"],
        )
        report.note("trojans/l4,l5: elemen Jupiter atau kelas TJN tidak ada, dilewati")
        return

    jupiter_l0 = classify.mean_longitude_deg(jupiter["OM"], jupiter["W"], jupiter["MA"])
    mean_motion = jupiter.get("N", classify.JUPITER_MEAN_MOTION_DEG_PER_DAY)
    epoch0 = jupiter["epoch_jd"]

    df = _floats(tjn, ["om", "w", "ma", "epoch"])
    camps: list[str | None] = []
    deltas: list[float | None] = []
    for row in df.iter_rows(named=True):
        om, w, ma, epoch = row["_om"], row["_w"], row["_ma"], row["_epoch"]
        if None in (om, w, ma):
            camps.append(None)
            deltas.append(None)
            continue
        jupiter_l = (
            classify.propagate_mean_longitude_deg(jupiter_l0, epoch0, epoch, mean_motion)
            if epoch is not None
            else jupiter_l0
        )
        obj_l = classify.mean_longitude_deg(om, w, ma)
        camps.append(classify.trojan_camp(obj_l, jupiter_l))
        deltas.append((obj_l - jupiter_l) % 360.0)

    annotated = tjn.with_columns([
        pl.Series("lagrange_camp", camps, dtype=pl.Utf8),
        pl.Series("mean_longitude_minus_jupiter_deg", deltas, dtype=pl.Float64),
    ])

    method = (
        f"L = Omega + omega + M dibandingkan bujur rata-rata Jupiter "
        f"({jupiter_l0:.3f} deg pada JD {epoch0}, JPL Horizons), dipropagasi dengan mean "
        f"motion Jupiter {mean_motion} deg/hari kalau epoch objeknya berbeda. "
        "0 < dL < 180 = L4 (kubu Yunani), sisanya L5 (kubu Troya)."
    )
    for camp in ("l4", "l5"):
        sub = annotated.filter(pl.col("lagrange_camp") == camp)
        dir_path = target_root / camp
        write_category_table(dir_path, sub)
        write_metadata(
            dir_path / "metadata.json",
            source=source_key,
            source_url=SBDB_URL,
            record_count=sub.height,
            derived_from=["om", "w", "ma", "epoch", "jpl_horizons_elements/jupiter_barycenter"],
            classification_method=method,
        )
        write_readme(
            dir_path,
            camp.upper(),
            f"{sub.height} trojan Jupiter di titik Lagrange {camp.upper()} "
            f"({'memimpin' if camp == 'l4' else 'membuntuti'} Jupiter ~60 derajat).\n\n"
            f"{method}\n\nIni geometri, bukan tebakan: hasilnya dicek terhadap objek "
            "acuan — Achilles, Hektor, Agamemnon, Odysseus, Diomedes keluar L4; "
            "Patroclus dan Priamus keluar L5.",
            [source_key, "jpl_horizons_elements"],
        )
    write_category_index(
        target_root,
        ["jupiter_all", "l4", "l5"],
        "Trojan Jupiter. `jupiter_all` adalah kelas SBDB TJN apa adanya; `l4`/`l5` adalah "
        "pembagian kubu Lagrange yang dihitung dari bujur rata-rata (lihat metadata.json).",
        ["sbdb_query_full", "jpl_horizons_elements"],
    )

    unresolved = annotated.filter(pl.col("lagrange_camp").is_null()).height
    report.note(
        f"trojans: L4={annotated.filter(pl.col('lagrange_camp') == 'l4').height}, "
        f"L5={annotated.filter(pl.col('lagrange_camp') == 'l5').height}, "
        f"{unresolved} tanpa elemen lengkap"
    )


def _build_tno_subclasses(
    raw_root: Path,
    out_root: Path,
    tno: pl.DataFrame | None,
    report: BuildReport,
    source_key: str = "sbdb_query_full",
) -> None:
    """trans_neptunian/{classical,resonant,scattered,detached,inner_belt}."""
    target_root = out_root / "trans_neptunian"
    neptune = _giant_planet_elements(raw_root, "neptune_barycenter")
    if tno is None or neptune is None or "A" not in neptune:
        report.note("trans_neptunian subclass: elemen Neptunus atau kelas TNO tidak ada, dilewati")
        return

    a_neptune = neptune["A"]
    df = _floats(tno, ["a", "e", "i"])
    classes: list[str | None] = []
    subclasses: list[str | None] = []
    for row in df.iter_rows(named=True):
        cls, sub = classify.tno_class(row["_a"], row["_e"], row["_i"], a_neptune)
        classes.append(cls)
        subclasses.append(sub)

    annotated = tno.with_columns([
        pl.Series("dynamical_class", classes, dtype=pl.Utf8),
        pl.Series("dynamical_subclass", subclasses, dtype=pl.Utf8),
    ])

    method = (
        f"build/classify.py tno_class() memakai a Neptunus = {a_neptune:.5f} AU (JPL "
        "Horizons). PERKIRAAN: keanggotaan resonansi sebenarnya butuh integrasi numerik "
        "argumen resonansi, sedangkan ini cuma potongan (a, q, e, i) di sekitar lokasi "
        "resonansi nominal a_res = a_N (p/q)^(2/3)."
    )
    children: list[str] = []
    for (cls,), sub in annotated.filter(
        pl.col("dynamical_class").is_not_null()
    ).partition_by("dynamical_class", as_dict=True, include_key=True).items():
        children.append(cls)
        if cls in ("classical", "resonant"):
            for (subcls,), leaf in sub.partition_by(
                "dynamical_subclass", as_dict=True, include_key=True
            ).items():
                _write_tno_leaf(target_root / cls / (subcls or "unclassified"), leaf, method, source_key)
            write_category_index(
                target_root / cls,
                sorted({s or "unclassified" for s in sub["dynamical_subclass"].to_list()}),
                f"{sub.height} objek kelas `{cls}` (perkiraan, lihat metadata.json).",
                [source_key, "jpl_horizons_elements"],
            )
        else:
            _write_tno_leaf(target_root / cls, sub, method, source_key)

    unclassified = annotated.filter(pl.col("dynamical_class").is_null()).height
    write_category_index(
        target_root,
        sorted(set(children) | {"tno_all"}),
        "Sub-kelas dinamis TNO — **perkiraan**, dari potongan (a, q, e, i) di sekitar "
        f"resonansi gerak-rata-rata Neptunus. {unclassified} objek tanpa elemen lengkap "
        "tidak diklasifikasi. `tno_all/` adalah dump kelas SBDB TNO apa adanya.",
        [source_key, "jpl_horizons_elements"],
    )
    counts = annotated.group_by("dynamical_class").len().to_dicts()
    report.note(
        "trans_neptunian (perkiraan): "
        + ", ".join(f"{c['dynamical_class'] or 'tanpa elemen'}={c['len']}" for c in sorted(counts, key=lambda c: -c["len"]))
    )


def _write_tno_leaf(dir_path: Path, df: pl.DataFrame, method: str, source_key: str) -> None:
    write_category_table(dir_path, df)
    write_metadata(
        dir_path / "metadata.json",
        source=source_key,
        source_url=SBDB_URL,
        record_count=df.height,
        derived_from=["a", "e", "i", "jpl_horizons_elements/neptune_barycenter"],
        classification_method=method,
    )
    write_readme(
        dir_path,
        dir_path.name,
        f"{df.height} objek trans-Neptunus.\n\n{method}",
        [source_key, "jpl_horizons_elements"],
    )


def _build_interstellar(raw_root: Path, out_root: Path, report: BuildReport) -> None:
    """comets/interstellar/ — the IAU's three, kept apart from merely-hyperbolic orbits."""
    dir_path = out_root / "comets" / "interstellar"
    frames = []
    for cls in ("HYP", "PAR", "HYA"):
        df = _load_class_file(raw_root, "sbdb_query_hyperbolic", cls)
        if df is not None:
            frames.append(df)
    if not frames:
        write_readme(
            dir_path,
            "interstellar",
            "Belum terisi: jalankan `astro pull sbdb_query_hyperbolic`.",
            ["sbdb_query_hyperbolic"],
        )
        return

    hyperbolic = pl.concat(frames, how="diagonal_relaxed")
    designations = [(d or "").strip() for d in hyperbolic["pdes"].to_list()]
    annotated = hyperbolic.with_columns([
        pl.Series(
            "iau_interstellar_designation",
            [IAU_INTERSTELLAR_OBJECTS.get(d) for d in designations],
            dtype=pl.Utf8,
        ),
        pl.col("e").cast(pl.Float64, strict=False).alias("_e"),
    ])

    confirmed = annotated.filter(pl.col("iau_interstellar_designation").is_not_null()).drop("_e")
    strongly = annotated.filter(pl.col("_e") >= STRONGLY_HYPERBOLIC_ECCENTRICITY).drop("_e")
    rest = annotated.filter(
        pl.col("iau_interstellar_designation").is_null()
        & (pl.col("_e") < STRONGLY_HYPERBOLIC_ECCENTRICITY).fill_null(True)
    ).drop("_e")

    write_category_table(dir_path, confirmed)
    write_metadata(
        dir_path / "metadata.json",
        source="sbdb_query_hyperbolic",
        source_url=SBDB_URL,
        record_count=confirmed.height,
        derived_from=["pdes"],
        classification_method="pencocokan designation utama SBDB ke tabel objek "
        "antarbintang IAU (1I/2I/3I) di build/small_bodies.py",
    )
    dir_path.mkdir(parents=True, exist_ok=True)
    strongly.write_parquet(dir_path / "strongly_hyperbolic_candidates.parquet")
    rest.write_parquet(dir_path / "hyperbolic_but_not_interstellar.parquet")

    found = sorted(confirmed["iau_interstellar_designation"].to_list())
    missing = sorted(set(IAU_INTERSTELLAR_OBJECTS.values()) - set(found))
    write_readme(
        dir_path,
        "interstellar",
        f"{confirmed.height} objek antarbintang: {', '.join(found) or 'tidak ada'}"
        + (f" (tidak ketemu di SBDB: {', '.join(missing)})" if missing else "")
        + ".\n\n"
        "**Kenapa tidak sekadar e > 1**: komet awan Oort rutin didorong planet raksasa "
        f"ke orbit hiperbolik. Dari {annotated.height} objek kelas HYP/PAR/HYA, "
        f"{strongly.height} punya e >= {STRONGLY_HYPERBOLIC_ECCENTRICITY} "
        "(`strongly_hyperbolic_candidates.parquet`) dan sisanya hanya lewat e=1 tipis "
        "(`hyperbolic_but_not_interstellar.parquet`). Bahkan di daftar pendek itu, "
        "C/1954 O1 dan C/1980 E1 adalah komet tata surya yang kena tendang Jupiter — "
        "jadi ambang eksentrisitas dipakai untuk menyaring, bukan untuk memutuskan.\n\n"
        "Yang memutuskan adalah penamaan IAU. SBDB tidak menyimpan designation `1I/2I/3I` "
        "sama sekali (namanya masih \"'Oumuamua (A/2017 U1)\", \"C/2019 Q4 (Borisov)\", "
        "\"C/2025 N1 (ATLAS)\"), jadi jembatannya berupa tabel eksplisit tiga baris di "
        "`build/small_bodies.py` — data orbitnya tetap dari SBDB.",
        ["sbdb_query_hyperbolic"],
    )
    report.note(
        f"comets/interstellar: {confirmed.height} objek IAU ({', '.join(found)}) dari "
        f"{annotated.height} orbit hiperbolik/parabolik"
        + (f"; TIDAK ketemu: {', '.join(missing)}" if missing else "")
    )


# The MDC shower file documents its own columns in a 98-line header; this is
# that column order (36 fields, pipe-separated, every value quoted).
MDC_COLUMNS = [
    "LP", "IAUNo", "AdNo", "Code", "s", "sub_date", "shower_name", "activity",
    "LoSb", "LoSe", "LoS", "Ra", "De", "dRa", "dDe", "Vg", "LoR", "S_LoR", "LaR",
    "theta", "phi", "Flags", "a", "q", "e", "peri", "node", "inc", "N", "Group",
    "CG", "Origin", "Remarks", "OTe", "LT", "Reference",
]


def _parse_mdc(path: Path) -> pl.DataFrame | None:
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.startswith((":", "+")):
            continue
        fields = [f.strip().strip('"').strip() for f in line.split("|")]
        if len(fields) != len(MDC_COLUMNS):
            continue
        rows.append(dict(zip(MDC_COLUMNS, fields)))
    return pl.DataFrame(rows) if rows else None


def _build_meteor_showers(raw_root: Path, out_root: Path, report: BuildReport) -> None:
    """meteor_showers/<code>_<name>/ from the IAU MDC established-shower list."""
    dir_path = out_root / "meteor_showers"
    established_path = latest_raw_file(raw_root, "iau_meteor_data_center", "streamestablisheddata.txt")
    if established_path is None:
        write_readme(
            dir_path,
            "meteor_showers",
            "Belum terisi: jalankan `astro pull iau_meteor_data_center`.",
            ["iau_meteor_data_center"],
        )
        return

    established = _parse_mdc(established_path)
    if established is None:
        report.note("meteor_showers: file MDC ada tapi tidak ada baris data yang terparse")
        return

    full_path = latest_raw_file(raw_root, "iau_meteor_data_center", "streamfulldata.txt")
    full = _parse_mdc(full_path) if full_path else None
    if full is not None:
        write_category_table(dir_path / "_all_showers", full)
        write_metadata(
            dir_path / "_all_showers" / "metadata.json",
            source="iau_meteor_data_center",
            source_url=MDC_URL,
            record_count=full.height,
        )
        write_readme(
            dir_path / "_all_showers",
            "_all_showers",
            f"{full.height} baris solusi untuk seluruh daftar MDC (established + working "
            "list). Satu hujan meteor bisa punya banyak baris: tiap baris satu solusi "
            "orbit dari publikasi berbeda.",
            ["iau_meteor_data_center"],
        )

    slugs = []
    for (code,), rows in established.partition_by("Code", as_dict=True, include_key=True).items():
        name = next((n for n in rows["shower_name"].to_list() if n), code)
        slug = f"{slugify(code)}_{slugify(name)}" if code else slugify(name)
        slugs.append(slug)
        target = dir_path / slug
        target.mkdir(parents=True, exist_ok=True)
        rows.write_csv(target / "solutions.csv")
        first = rows.row(0, named=True)
        write_json(target / "shower.json", {
            "display_name": name,
            "iau_code": code,
            "iau_number": first.get("IAUNo"),
            "activity": first.get("activity") or None,
            "solar_longitude_max_deg": first.get("LoS") or None,
            "radiant_ra_deg": first.get("Ra") or None,
            "radiant_dec_deg": first.get("De") or None,
            "geocentric_velocity_km_s": first.get("Vg") or None,
            "parent_body": first.get("Origin") or None,
            "solution_count": rows.height,
            "data_source": "iau_meteor_data_center",
        })
        write_metadata(
            target / "metadata.json",
            source="iau_meteor_data_center",
            source_url=MDC_URL,
            record_count=rows.height,
        )
        write_readme(
            target,
            name,
            f"Hujan meteor IAU `{code}` (nomor {first.get('IAUNo')}), "
            f"{rows.height} solusi orbit di `solutions.csv`.\n\n"
            f"Benda induk menurut MDC: {first.get('Origin') or 'tidak tercatat'}.\n\n"
            "Nilai di `shower.json` diambil dari solusi pertama yang tercatat MDC untuk "
            "hujan ini, bukan rata-rata beberapa solusi — solusi lengkapnya ada di CSV.",
            ["iau_meteor_data_center"],
        )

    write_category_index(
        dir_path,
        slugs + (["_all_showers"] if full is not None else []),
        "Hujan meteor yang sudah diakui IAU (established list), satu folder per hujan.",
        ["iau_meteor_data_center"],
    )
    report.note(f"meteor_showers: {len(slugs)} hujan established dari IAU MDC")
