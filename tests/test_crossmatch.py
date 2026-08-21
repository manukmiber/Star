"""Tests for the positional cross-matcher."""

from __future__ import annotations

import numpy as np
import pytest

from astro_datalake.build.crossmatch import angular_separation_deg, match_nearest


def test_separation_of_identical_positions_is_zero():
    assert angular_separation_deg(10.0, 20.0, 10.0, 20.0) == pytest.approx(0.0)


def test_separation_along_the_equator_is_the_ra_difference():
    assert angular_separation_deg(0.0, 0.0, 1.0, 0.0) == pytest.approx(1.0)


def test_separation_shrinks_with_cos_dec():
    """One degree of RA at dec=60 is half a degree on the sky."""
    assert angular_separation_deg(0.0, 60.0, 1.0, 60.0) == pytest.approx(0.5, abs=1e-3)


def test_separation_of_the_poles():
    assert angular_separation_deg(0.0, 90.0, 180.0, -90.0) == pytest.approx(180.0)


def test_mizar_alcor_separation():
    """Mizar and Alcor are ~709 arcsec apart (a naked-eye pair)."""
    mizar = (200.98141, 54.92536)
    alcor = (201.30642, 54.98797)
    sep_arcsec = angular_separation_deg(*mizar, *alcor) * 3600
    assert sep_arcsec == pytest.approx(709, abs=5)


def test_match_nearest_picks_the_closest_within_tolerance():
    targets_ra = np.array([10.0, 20.0, 30.0])
    targets_dec = np.array([0.0, 0.0, 0.0])
    # Catalogue: one 1" away from target 0, one 2" away from target 0
    # (so the nearest wins), one far from target 1, none near target 2.
    catalog_ra = np.array([10.0 + 1 / 3600, 10.0 + 2 / 3600, 20.5])
    catalog_dec = np.array([0.0, 0.0, 0.0])

    idx, sep = match_nearest(targets_ra, targets_dec, catalog_ra, catalog_dec, tolerance_arcsec=5.0)

    assert idx[0] == 0
    assert sep[0] == pytest.approx(1.0, abs=0.01)
    assert idx[1] == -1 and np.isnan(sep[1])
    assert idx[2] == -1 and np.isnan(sep[2])


def test_match_nearest_respects_the_tolerance():
    idx, _ = match_nearest(np.array([0.0]), np.array([0.0]), np.array([0.01]), np.array([0.0]), 5.0)
    assert idx[0] == -1  # 36 arcsec away, tolerance is 5
    idx, sep = match_nearest(np.array([0.0]), np.array([0.0]), np.array([0.01]), np.array([0.0]), 60.0)
    assert idx[0] == 0
    assert sep[0] == pytest.approx(36.0, abs=0.1)


def test_match_nearest_ignores_nan_targets():
    idx, _ = match_nearest(np.array([np.nan]), np.array([0.0]), np.array([0.0]), np.array([0.0]), 5.0)
    assert idx[0] == -1


def test_match_nearest_handles_an_empty_catalog():
    idx, sep = match_nearest(np.array([1.0]), np.array([1.0]), np.array([]), np.array([]), 5.0)
    assert idx[0] == -1 and np.isnan(sep[0])
