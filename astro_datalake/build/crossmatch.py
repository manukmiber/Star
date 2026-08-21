"""Positional cross-matching, used to give catalogue rows their common names.

WDS, SB9 and MSC identify systems by discoverer code or Durchmusterung
number, never as "Alpha Centauri". HYG carries the common names but not the
double-star measurements. The only honest bridge between them is the sky
position, so this module does the nearest-neighbour match and — importantly
— reports the separation it accepted, so a folder can record how good its
own identification was instead of asserting one.

The match is deliberately conservative: one nearest counterpart inside a
tolerance, no probabilistic association, no magnitude or proper-motion
priors. Anything past that would need SIMBAD's own name resolver, which is
a different (and better) tool than a hand-rolled likelihood.
"""

from __future__ import annotations

import numpy as np

ARCSEC_PER_DEG = 3600.0


def angular_separation_deg(
    ra1_deg: np.ndarray | float,
    dec1_deg: np.ndarray | float,
    ra2_deg: np.ndarray | float,
    dec2_deg: np.ndarray | float,
) -> np.ndarray:
    """Great-circle separation in degrees (haversine — stable at small angles)."""
    ra1, dec1, ra2, dec2 = (np.radians(np.asarray(x, dtype=float)) for x in (ra1_deg, dec1_deg, ra2_deg, dec2_deg))
    d_ra = ra2 - ra1
    d_dec = dec2 - dec1
    a = np.sin(d_dec / 2.0) ** 2 + np.cos(dec1) * np.cos(dec2) * np.sin(d_ra / 2.0) ** 2
    return np.degrees(2.0 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0))))


def match_nearest(
    target_ra: np.ndarray,
    target_dec: np.ndarray,
    catalog_ra: np.ndarray,
    catalog_dec: np.ndarray,
    tolerance_arcsec: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Nearest catalogue row within `tolerance_arcsec` for each target.

    Returns (index, separation_arcsec) arrays the same length as the
    targets; unmatched entries get index -1 and separation NaN.

    Declination-banded rather than brute-forced: a full target x catalogue
    distance matrix for the WDS (1.6e5 rows) would be gigabytes, while the
    band cuts each target down to a few hundred candidates.
    """
    target_ra = np.asarray(target_ra, dtype=float)
    target_dec = np.asarray(target_dec, dtype=float)
    catalog_ra = np.asarray(catalog_ra, dtype=float)
    catalog_dec = np.asarray(catalog_dec, dtype=float)

    tol_deg = tolerance_arcsec / ARCSEC_PER_DEG
    order = np.argsort(catalog_dec, kind="stable")
    sorted_dec = catalog_dec[order]

    match_index = np.full(target_ra.shape, -1, dtype=np.int64)
    match_sep = np.full(target_ra.shape, np.nan, dtype=float)

    lo_all = np.searchsorted(sorted_dec, target_dec - tol_deg, side="left")
    hi_all = np.searchsorted(sorted_dec, target_dec + tol_deg, side="right")

    for i, (lo, hi) in enumerate(zip(lo_all, hi_all)):
        if hi <= lo or not np.isfinite(target_ra[i]) or not np.isfinite(target_dec[i]):
            continue
        candidates = order[lo:hi]
        seps = angular_separation_deg(
            target_ra[i], target_dec[i], catalog_ra[candidates], catalog_dec[candidates]
        )
        best = int(np.argmin(seps))
        if seps[best] <= tol_deg:
            match_index[i] = candidates[best]
            match_sep[i] = seps[best] * ARCSEC_PER_DEG

    return match_index, match_sep
