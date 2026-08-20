from astro_datalake.sources.registry import SOURCES, sources_by_tier


def test_registry_has_sources():
    assert len(SOURCES) > 20


def test_every_source_has_valid_tier():
    for key, spec in SOURCES.items():
        assert spec.tier in (1, 2, 3), f"{key} has invalid tier {spec.tier}"


def test_every_source_has_probe_url_and_method():
    for key, spec in SOURCES.items():
        assert spec.probe_url, f"{key} missing probe_url"
        assert spec.probe_method in ("GET", "HEAD"), f"{key} bad probe_method"


def test_tier_filters_partition_sources():
    total = sum(len(sources_by_tier(t)) for t in (1, 2, 3))
    assert total == len(SOURCES)


def test_no_duplicate_keys_by_construction():
    # keys are dict keys, so duplicates are impossible after import;
    # this just confirms the module imported without raising.
    assert "hyg_database" in SOURCES
    assert "gaia_dr3_tap" in SOURCES
