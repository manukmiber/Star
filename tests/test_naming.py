from astro_datalake.core.naming import (
    dedupe_slug,
    numbered_asteroid_slug,
    planet_slug,
    slugify,
)


def test_slugify_basic():
    assert slugify("Earth") == "earth"
    assert slugify("HD 209458") == "hd_209458"
    assert slugify("TRAPPIST-1") == "trappist-1"
    assert slugify("Kepler-90") == "kepler-90"


def test_slugify_strips_non_ascii_and_punctuation():
    assert slugify("Beta Pictoris b") == "beta_pictoris_b"
    assert slugify("55 Cancri e") == "55_cancri_e"
    assert slugify("  extra   spaces  ") == "extra_spaces"


def test_planet_slug():
    assert planet_slug(3, "Earth") == "03_earth"
    assert planet_slug(1, "Mercury") == "01_mercury"


def test_numbered_asteroid_slug():
    assert numbered_asteroid_slug(1, "Ceres") == "00001_ceres"
    assert numbered_asteroid_slug(433, "Eros") == "00433_eros"


def test_dedupe_slug():
    assert dedupe_slug("hd_209458", "TIC 420814525") == "hd_209458__tic_420814525"
