"""Tests for the Fase 5 derived-classification rules.

Each case is anchored on a real object whose class is not in dispute, so a
regression here means the rule stopped agreeing with the sky, not just with
a previous run.
"""

from __future__ import annotations

import math

import pytest

from astro_datalake.build.classify import (
    HabitableZone,
    exoplanet_types,
    habitable_zone_flux_limits,
    insolation_earth,
    is_hypergiant,
    is_potentially_rocky,
    is_supergiant,
    luminosity_class,
    mean_longitude_deg,
    propagate_mean_longitude_deg,
    resonance_semi_major_axis,
    size_class,
    thermal_class,
    tno_class,
    trojan_camp,
)

A_NEPTUNE = 30.07


# --- exoplanet size / thermal classes --------------------------------------


@pytest.mark.parametrize(
    "radius_earth, mass_earth, expected",
    [
        (1.0, 1.0, "terrestrial"),        # Earth
        (0.53, 0.107, "terrestrial"),     # Mars-size
        (1.6, 5.0, "super_earth"),        # e.g. LHS 1140 b regime
        (2.6, 8.6, "sub_neptune"),        # e.g. GJ 1214 b
        (3.86, 17.1, "sub_neptune"),      # Neptune itself sits just under 4 R_E
        (9.4, 95.2, "neptune_like"),      # Saturn-size, below the 10 R_E cut
        (11.2, 317.8, "gas_giant"),       # Jupiter
        (None, 317.8, "gas_giant"),       # mass fallback
        (None, 1.0, "terrestrial"),
        (None, None, None),               # nothing known -> no guess
    ],
)
def test_size_class(radius_earth, mass_earth, expected):
    assert size_class(radius_earth, mass_earth)[0] == expected


def test_size_class_reports_basis():
    assert size_class(11.2, 317.8)[1] == "radius"
    assert size_class(None, 317.8)[1] == "mass"
    assert size_class(None, None)[1] == "none"


@pytest.mark.parametrize(
    "period, expected",
    [(0.7, "hot"), (3.5, "hot"), (10.0, "warm"), (88.0, "warm"), (365.25, "cold"), (None, None)],
)
def test_thermal_class(period, expected):
    assert thermal_class(period) == expected


def test_hot_jupiter_is_also_a_gas_giant():
    # 51 Peg b: 4.23 d, ~1.9 M_J = 604 M_E, no reliable radius.
    labels = exoplanet_types(radius_earth=None, mass_earth=604.0, orbital_period_days=4.23)
    assert "gas_giant" in labels
    assert "hot_jupiter" in labels
    assert "ultra_short_period" not in labels


def test_ultra_short_period_flags_regardless_of_size():
    # Kepler-78 b: 0.355 d, 1.2 R_E.
    labels = exoplanet_types(radius_earth=1.2, orbital_period_days=0.355)
    assert labels == ["terrestrial", "ultra_short_period"]


def test_cold_jupiter():
    # Jupiter itself: 11.2 R_E, 4332.6 d.
    assert "cold_jupiter" in exoplanet_types(radius_earth=11.2, orbital_period_days=4332.6)


def test_unknown_planet_gets_no_labels():
    assert exoplanet_types() == []


def test_potentially_rocky_is_tri_state():
    assert is_potentially_rocky(1.1, None) is True
    assert is_potentially_rocky(2.4, None) is False
    assert is_potentially_rocky(None, 3.0) is True
    assert is_potentially_rocky(None, None) is None


# --- habitable zone --------------------------------------------------------


def test_kopparapu_limits_at_solar_teff():
    """At Teff = 5780 K the polynomial reduces to the published Seff_sun."""
    hz = habitable_zone_flux_limits(5780.0)
    assert isinstance(hz, HabitableZone)
    assert hz.recent_venus == pytest.approx(1.776)
    assert hz.runaway_greenhouse == pytest.approx(1.107)
    assert hz.maximum_greenhouse == pytest.approx(0.356)
    assert hz.early_mars == pytest.approx(0.320)


def test_kopparapu_out_of_range_returns_none():
    assert habitable_zone_flux_limits(9000.0) is None   # too hot: A-type
    assert habitable_zone_flux_limits(2000.0) is None   # too cool
    assert habitable_zone_flux_limits(None) is None


def test_earth_is_in_the_conservative_zone():
    hz = habitable_zone_flux_limits(5772.0)
    assert hz.zone_of(1.0) == "conservative"


def test_venus_is_too_hot_and_mars_is_not():
    hz = habitable_zone_flux_limits(5772.0)
    assert hz.zone_of(1.91) is None            # Venus sits inside the recent-Venus limit
    assert hz.zone_of(0.43) == "conservative"  # Mars is inside the conservative HZ (Kopparapu)
    assert hz.zone_of(0.33) == "optimistic"    # just outside max-greenhouse, inside early-Mars
    assert hz.zone_of(1.50) == "optimistic"    # between runaway-greenhouse and recent-Venus


def test_trappist1_e_is_in_the_conservative_zone():
    # TRAPPIST-1: Teff 2566 K is just below the polynomial's floor, so the
    # archive value of 2559 K must refuse rather than extrapolate; at the
    # published 2600 K floor TRAPPIST-1 e (S = 0.646) is habitable-zone.
    assert habitable_zone_flux_limits(2559.0) is None
    hz = habitable_zone_flux_limits(2600.0)
    assert hz.zone_of(0.646) == "conservative"


def test_insolation_prefers_archive_value_then_derives():
    assert insolation_earth(insol=1.2) == (1.2, "pl_insol")
    value, provenance = insolation_earth(log_luminosity_solar=0.0, semi_major_axis_au=1.0)
    assert value == pytest.approx(1.0)
    assert provenance == "derived_from_st_lum_and_pl_orbsmax"
    assert insolation_earth()[0] is None


# --- trans-Neptunian sub-classes -------------------------------------------


def test_resonance_locations_match_textbook_values():
    assert resonance_semi_major_axis(3, 2, A_NEPTUNE) == pytest.approx(39.4, abs=0.1)
    assert resonance_semi_major_axis(2, 1, A_NEPTUNE) == pytest.approx(47.8, abs=0.1)
    assert resonance_semi_major_axis(5, 2, A_NEPTUNE) == pytest.approx(55.4, abs=0.1)


@pytest.mark.parametrize(
    "name, a, e, i, expected",
    [
        ("Pluto",      39.48, 0.2488, 17.16, ("resonant", "3_2_plutino")),
        ("Orcus",      39.17, 0.2266, 20.59, ("resonant", "3_2_plutino")),
        ("Albion",     44.13, 0.0712,  2.19, ("classical", "cold")),
        ("Makemake",   45.43, 0.1610, 28.98, ("classical", "hot")),
        ("Eris",       67.86, 0.4359, 44.04, ("scattered", None)),
        ("Sedna",     506.80, 0.8496, 11.93, ("detached", None)),
        ("2000 CR105", 222.2, 0.8046, 22.71, ("detached", None)),
    ],
)
def test_tno_class_on_known_objects(name, a, e, i, expected):
    assert tno_class(a, e, i, A_NEPTUNE) == expected, name


def test_tno_class_without_elements():
    assert tno_class(None, None, None, A_NEPTUNE) == (None, None)


# --- Jupiter trojans -------------------------------------------------------


def test_mean_longitude_wraps():
    assert mean_longitude_deg(316.53, 134.31, 93.31) == pytest.approx(184.15, abs=0.01)
    assert 0 <= mean_longitude_deg(350.0, 350.0, 350.0) < 360


def test_trojan_camps_of_the_archetypes():
    """Jupiter's mean longitude at JD 2461200.5 is 116.66 deg (Horizons).

    588 Achilles is the archetypal Greek-camp (L4) trojan and 617 Patroclus
    the archetypal Trojan-camp (L5) one; elements below are SBDB's at that
    same epoch.
    """
    jupiter_l = mean_longitude_deg(100.518, 273.552, 102.587)
    assert jupiter_l == pytest.approx(116.66, abs=0.01)

    achilles = mean_longitude_deg(316.53, 134.31, 93.31)
    patroclus = mean_longitude_deg(44.35, 308.84, 58.68)
    assert trojan_camp(achilles, jupiter_l) == "l4"
    assert trojan_camp(patroclus, jupiter_l) == "l5"


def test_trojan_camp_is_exactly_the_leading_half():
    assert trojan_camp(60.0, 0.0) == "l4"
    assert trojan_camp(300.0, 0.0) == "l5"
    assert trojan_camp(0.0, 0.0) == "l5"  # delta == 0 is not leading


def test_propagate_mean_longitude():
    assert propagate_mean_longitude_deg(0.0, 0.0, 10.0, 1.0) == pytest.approx(10.0)
    assert propagate_mean_longitude_deg(350.0, 0.0, 20.0, 1.0) == pytest.approx(10.0)
    assert math.isfinite(propagate_mean_longitude_deg(100.0, 2461200.5, 2457132.5, 0.0830975))


# --- MK luminosity class ---------------------------------------------------


@pytest.mark.parametrize(
    "spect, expected",
    [
        ("K5III", "III"),          # Aldebaran-like
        ("M2Iab-Ib", "Iab"),       # Betelgeuse
        ("B0.5Ia+", "Ia+"),        # a hypergiant
        ("G2V", "V"),              # the Sun
        ("A0IV", "IV"),
        ("F5Ib", "Ib"),
        ("K0Ia", "Ia"),
        ("G2V+K1V", "V"),          # binary spectral string
        ("DA2", None),             # white dwarf: no luminosity class
        ("T8", None),              # brown dwarf
        ("", None),
        (None, None),
    ],
)
def test_luminosity_class(spect, expected):
    assert luminosity_class(spect) == expected


def test_supergiant_and_hypergiant_predicates():
    assert is_supergiant("M2Iab-Ib") is True
    assert is_supergiant("B0.5Ia+") is True      # a hypergiant is still class I
    assert is_supergiant("G2V") is False
    assert is_hypergiant("B0.5Ia+") is True
    assert is_hypergiant("M2Iab-Ib") is False
