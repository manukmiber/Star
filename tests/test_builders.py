"""Tests for the parsing and bookkeeping the Fase 5 builders depend on.

These are the bits where a silent mistake would poison real data: a
misparsed fixed-format file, an attribution block that stops being
idempotent, or a source that gets registered but never wired to a
downloader.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from astro_datalake.build.catalog import LEAF_MARKERS, SCHEMAS, attribution_pass
from astro_datalake.build.common import (
    ATTRIBUTION_BEGIN,
    ATTRIBUTION_END,
    attribution_block,
    license_of,
    source_key_of,
    write_metadata,
    write_readme,
)
from astro_datalake.build.small_bodies import (
    IAU_INTERSTELLAR_OBJECTS,
    MDC_COLUMNS,
    _parse_horizons_elements,
    _parse_mdc,
)
from astro_datalake.downloaders import DOWNLOAD_PLAN
from astro_datalake.models3d import STREAM_PLAN
from astro_datalake.sources.registry import SOURCES


# --- registry / downloader wiring ------------------------------------------


def test_every_source_is_wired_to_a_download_plan_or_explicit_none():
    """A registered source must be either downloadable or deliberately not.

    A missing key means `astro pull` silently reports 'skipped' for a source
    nobody decided to skip. Tabular sources live in DOWNLOAD_PLAN, binary
    mesh/texture trees in models3d.STREAM_PLAN — either counts, neither being
    present does not.
    """
    planned = set(DOWNLOAD_PLAN) | set(STREAM_PLAN)
    for key in SOURCES:
        assert key in planned, f"{key} has no DOWNLOAD_PLAN/STREAM_PLAN entry (not even None)"


def test_a_source_is_wired_to_exactly_one_plan():
    overlap = set(DOWNLOAD_PLAN) & set(STREAM_PLAN)
    assert not overlap, f"pulled twice, by two different mechanisms: {sorted(overlap)}"


def test_download_plan_has_no_stray_keys():
    for key in set(DOWNLOAD_PLAN) | set(STREAM_PLAN):
        assert key in SOURCES, f"{key} is downloadable but not registered"


def test_fase5_sources_are_registered_and_downloadable():
    for key in (
        "atnf_pulsar_catalog",
        "blackcat_bh_transients",
        "iau_meteor_data_center",
        "sbdb_query_hyperbolic",
        "jpl_horizons_elements",
        "simbad_tap",
    ):
        assert key in SOURCES
        assert DOWNLOAD_PLAN[key] is not None, f"{key} registered but has no fetcher"


def test_every_source_declares_a_license_or_says_it_is_unverified():
    for key, spec in SOURCES.items():
        assert spec.license or spec.notes, f"{key} has neither a license nor a note about it"


# --- attribution ------------------------------------------------------------


def test_attribution_block_names_source_and_license():
    block = attribution_block(["wds_catalog"])
    assert ATTRIBUTION_BEGIN in block and ATTRIBUTION_END in block
    assert "wds_catalog" in block
    assert "CDS" in block


def test_attribution_block_dedupes_and_handles_unknown_sources():
    assert attribution_block(["hyg_database", "hyg_database"]).count("`hyg_database`") == 1
    assert "tidak terdaftar" in attribution_block(["not_a_source"])


def test_source_key_of_reads_the_first_token():
    assert source_key_of("wds_catalog (VizieR B/wds)") == "wds_catalog"
    assert source_key_of("jpl_sbdb_query (derived)") is None  # not a registry key
    assert source_key_of("") is None
    assert license_of("hyg_database") == "CC BY-SA 4.0 (per repo)"


def test_write_metadata_fills_license_from_the_registry(tmp_path: Path):
    write_metadata(tmp_path / "metadata.json", source="hyg_database", source_url="x")
    assert json.loads((tmp_path / "metadata.json").read_text())["license"] == "CC BY-SA 4.0 (per repo)"


def test_attribution_pass_is_idempotent(tmp_path: Path):
    folder = tmp_path / "thing"
    folder.mkdir()
    write_metadata(folder / "metadata.json", source="hyg_database", source_url="x")
    write_readme(folder, "thing", "isi folder")

    assert attribution_pass(tmp_path) == 1
    first = (folder / "README.md").read_text()
    assert attribution_pass(tmp_path) == 1
    second = (folder / "README.md").read_text()

    assert first.count(ATTRIBUTION_BEGIN) == 1
    assert second.count(ATTRIBUTION_BEGIN) == 1
    assert "isi folder" in second
    assert (tmp_path / "ATTRIBUTION.md").exists()


def test_attribution_pass_replaces_a_stale_block(tmp_path: Path):
    folder = tmp_path / "thing"
    folder.mkdir()
    write_metadata(folder / "metadata.json", source="hyg_database", source_url="x")
    (folder / "README.md").write_text(
        f"# thing\n\nisi\n\n{ATTRIBUTION_BEGIN}\nsumber lama yang salah\n{ATTRIBUTION_END}\n"
    )
    attribution_pass(tmp_path)
    text = (folder / "README.md").read_text()
    assert "sumber lama yang salah" not in text
    assert "hyg_database" in text


def test_attribution_pass_skips_folders_with_no_registry_source(tmp_path: Path):
    folder = tmp_path / "thing"
    folder.mkdir()
    (folder / "metadata.json").write_text(json.dumps({"source": "something_unregistered"}))
    assert attribution_pass(tmp_path) == 0


# --- catalog schemas --------------------------------------------------------


def test_every_leaf_marker_is_validated_by_verify():
    """No leaf type in the master index that `astro verify` would skip."""
    from astro_datalake.cli.commands.verify import MARKER_TO_SCHEMA

    for marker in LEAF_MARKERS:
        if marker == "planet.json":
            continue  # two schemas share this filename, dispatched by path in verify
        assert marker in MARKER_TO_SCHEMA, f"{marker} is indexed but never schema-checked"
        assert MARKER_TO_SCHEMA[marker] in SCHEMAS


def test_verify_only_maps_markers_that_exist():
    from astro_datalake.cli.commands.verify import MARKER_TO_SCHEMA

    for marker in MARKER_TO_SCHEMA:
        assert marker in LEAF_MARKERS, f"{marker} is schema-checked but never indexed"


# --- IAU Meteor Data Center fixed-format parsing ----------------------------

MDC_SAMPLE = """: header line that must be skipped
:  LP    IAUNo   AdNo  Code
+2345678901234567890
"00001"|"00001"|"000"|"CAP"|" 1"|"2006-mm-dd"|"alpha-Capricornids     "|" annual "|\
"       "|"       "|"128.9  "|"306.6  "|"-8.2   "|"0.54   "|"0.25   "|"22.2   "|\
"306.91 "|"178.01 "|" 10.67 "|" 88.04 "|"259.32 "|"       "|"2.618  "|"0.602  "|\
"       "|"266.67 "|"128.9  "|"7.68   "|"000000036"|"00000"|"00"|"169P/NEAT"|"  "|\
"  "|"LookUp"|"Jenniskens, 2006"
"00002"|"00004"|"001"|"GEM"|" 1"|"2007-mm-dd"|"Geminids               "|" annual "|\
"       "|"       "|"261.0  "|"113.5  "|"32.5   "|"1.02   "|"-0.15  "|"35.0   "|\
"113.20 "|"208.00 "|" 10.40 "|" 88.00 "|"324.00 "|"       "|"1.36   "|"0.140  "|\
"0.897  "|"324.4  "|"261.0  "|"23.6   "|"000000100"|"00000"|"00"|"3200 Phaethon"|"  "|\
"  "|"LookUp"|"Jenniskens, 2006"
"""


def test_parse_mdc_skips_headers_and_unquotes(tmp_path: Path):
    path = tmp_path / "mdc.txt"
    path.write_text(MDC_SAMPLE)
    df = _parse_mdc(path)

    assert df.height == 2
    assert df.columns == MDC_COLUMNS
    assert df["Code"].to_list() == ["CAP", "GEM"]
    assert df["shower_name"].to_list() == ["alpha-Capricornids", "Geminids"]
    # The parent body is the last column before the technique/lookup/reference tail.
    assert df["Origin"].to_list() == ["169P/NEAT", "3200 Phaethon"]
    assert df["Vg"].to_list() == ["22.2", "35.0"]


def test_parse_mdc_ignores_rows_with_the_wrong_field_count(tmp_path: Path):
    path = tmp_path / "mdc.txt"
    path.write_text(MDC_SAMPLE + '"99999"|"broken row"\n')
    assert _parse_mdc(path).height == 2


def test_parse_mdc_returns_none_when_there_is_no_data(tmp_path: Path):
    path = tmp_path / "mdc.txt"
    path.write_text(": only a header\n")
    assert _parse_mdc(path) is None


# --- Horizons ELEMENTS parsing ----------------------------------------------

HORIZONS_SAMPLE = """*****
$$SOE
2461200.500000000 = A.D. 2026-Jun-09 00:00:00.0000 TDB
 EC= 4.825454719794290E-02 QR= 4.951493392874314E+00 IN= 1.303603985775937E+00
 OM= 1.005182155184106E+02 W = 2.735519333965584E+02 Tp=  2459965.956987159792
 N = 8.309754921907504E-02 MA= 1.025874987725663E+02 TA= 1.079064638275311E+02
 A = 5.202539584819136E+00 AD= 5.453585776763958E+00 PR= 4.332257730621037E+03
$$EOE
*****
"""


def test_parse_horizons_elements(tmp_path: Path):
    path = tmp_path / "jupiter.txt"
    path.write_text(HORIZONS_SAMPLE)
    elements = _parse_horizons_elements(path)

    assert elements["epoch_jd"] == pytest.approx(2461200.5)
    assert elements["A"] == pytest.approx(5.2025395848)
    assert elements["OM"] == pytest.approx(100.5182155)
    assert elements["W"] == pytest.approx(273.5519334)
    assert elements["MA"] == pytest.approx(102.5874988)
    assert elements["N"] == pytest.approx(0.0830975492)


def test_parse_horizons_elements_rejects_a_response_with_no_element_block(tmp_path: Path):
    path = tmp_path / "bad.txt"
    path.write_text("API error: no ephemeris\n")
    assert _parse_horizons_elements(path) is None


# --- interstellar object table ----------------------------------------------


def test_iau_interstellar_table_matches_sbdb_designations():
    """SBDB files these under their pre-interstellar designations."""
    assert IAU_INTERSTELLAR_OBJECTS["2017 U1"] == "1I/'Oumuamua"
    assert IAU_INTERSTELLAR_OBJECTS["2019 Q4"] == "2I/Borisov"
    assert IAU_INTERSTELLAR_OBJECTS["2025 N1"] == "3I/ATLAS"
    assert len(IAU_INTERSTELLAR_OBJECTS) == 3
