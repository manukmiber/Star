"""Fase 5: derived classification.

Everything in this module is *derived* from values that were actually
pulled from a source — it never invents a measurement. Each function
returns a label plus, where it matters, the numbers the label was computed
from, so a leaf folder can record `classification_method` next to the
answer and a reader can redo the arithmetic.

Three families of rules live here:

1. Exoplanet size/thermal classes (`exoplanet_types`) — radius/mass/period
   cuts. The size boundaries follow the usual observational convention
   (Fulton et al. 2017's radius valley at ~1.8 R_E; the Neptune/Jupiter
   size split at ~4 and ~10 R_E); the "hot" cut is the standard P < 10 d.
   These are conventions, not measurements: the thresholds are constants
   here so they can be read, argued with, and changed in one place.

2. Habitable zone (`habitable_zone_flux_limits`) — Kopparapu et al. (2013,
   ApJ 765, 131; coefficients from the 2014 erratum). Valid for
   2600 K <= Teff <= 7200 K; outside that range the functions return None
   rather than extrapolating.

3. Solar-system dynamical classes — trans-Neptunian sub-classes from
   (a, q, e, i) cuts around Neptune's mean-motion resonances, and the
   Jupiter-trojan L4/L5 camp from mean longitude relative to Jupiter's.
   The L4/L5 split is exact geometry (mod-360 arithmetic on angles the
   source provides). The TNO sub-classes are NOT: real membership in a
   resonance requires numerically integrating the resonant argument, and
   the cuts here are an approximation, labelled as such everywhere they
   are written to disk.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# 1. Exoplanet size / thermal classes
# ---------------------------------------------------------------------------

# Radius bins in Earth radii. 1.8 R_E is the Fulton et al. (2017) radius
# valley; 4 R_E ~ Neptune (3.86); 10 R_E ~ Jupiter (11.2) minus room for the
# inflated hot Jupiters that sit below it.
RADIUS_BINS_EARTH = [
    ("terrestrial", 0.0, 1.25),
    ("super_earth", 1.25, 1.8),
    ("sub_neptune", 1.8, 4.0),
    ("neptune_like", 4.0, 10.0),
    ("gas_giant", 10.0, math.inf),
]

# Mass fallback in Earth masses, used only when radius is missing.
# Neptune = 17.1 M_E, Saturn = 95.2 M_E, Jupiter = 317.8 M_E.
MASS_BINS_EARTH = [
    ("terrestrial", 0.0, 2.0),
    ("super_earth", 2.0, 10.0),
    ("sub_neptune", 10.0, 25.0),
    ("neptune_like", 25.0, 50.0),
    ("gas_giant", 50.0, math.inf),
]

HOT_PERIOD_DAYS = 10.0
WARM_PERIOD_DAYS = 200.0
ULTRA_SHORT_PERIOD_DAYS = 1.0

# "Potentially rocky" ceiling — Rogers (2015) finds most planets above
# ~1.6 R_E are not rocky.
ROCKY_MAX_RADIUS_EARTH = 1.6
ROCKY_MAX_MASS_EARTH = 10.0


def _bin_label(value: float | None, bins: list[tuple[str, float, float]]) -> str | None:
    if value is None or not math.isfinite(value) or value <= 0:
        return None
    for label, lo, hi in bins:
        if lo <= value < hi:
            return label
    return None


def size_class(radius_earth: float | None, mass_earth: float | None) -> tuple[str | None, str]:
    """(label, basis) where basis is 'radius', 'mass', or 'none'."""
    label = _bin_label(radius_earth, RADIUS_BINS_EARTH)
    if label is not None:
        return label, "radius"
    label = _bin_label(mass_earth, MASS_BINS_EARTH)
    if label is not None:
        return label, "mass"
    return None, "none"


def thermal_class(orbital_period_days: float | None) -> str | None:
    if orbital_period_days is None or not math.isfinite(orbital_period_days) or orbital_period_days <= 0:
        return None
    if orbital_period_days < HOT_PERIOD_DAYS:
        return "hot"
    if orbital_period_days < WARM_PERIOD_DAYS:
        return "warm"
    return "cold"


def exoplanet_types(
    radius_earth: float | None = None,
    mass_earth: float | None = None,
    orbital_period_days: float | None = None,
) -> list[str]:
    """Every by_type/ bucket a planet belongs in (buckets deliberately overlap).

    A hot Jupiter is filed under both `gas_giant` and `hot_jupiter`; a
    1.3-day super-Earth is filed under both `super_earth` and
    `ultra_short_period`. Planets with neither radius nor mass get no size
    label at all rather than a guessed one.
    """
    labels: list[str] = []
    size, _basis = size_class(radius_earth, mass_earth)
    if size:
        labels.append(size)
    temp = thermal_class(orbital_period_days)
    if size in {"gas_giant", "neptune_like"} and temp:
        noun = "jupiter" if size == "gas_giant" else "neptune"
        labels.append(f"{temp}_{noun}")
    if (
        orbital_period_days is not None
        and math.isfinite(orbital_period_days)
        and 0 < orbital_period_days < ULTRA_SHORT_PERIOD_DAYS
    ):
        labels.append("ultra_short_period")
    return labels


def is_potentially_rocky(radius_earth: float | None, mass_earth: float | None) -> bool | None:
    """None when neither radius nor mass is known — not False."""
    if radius_earth is not None and math.isfinite(radius_earth) and radius_earth > 0:
        return radius_earth <= ROCKY_MAX_RADIUS_EARTH
    if mass_earth is not None and math.isfinite(mass_earth) and mass_earth > 0:
        return mass_earth <= ROCKY_MAX_MASS_EARTH
    return None


# ---------------------------------------------------------------------------
# 2. Habitable zone — Kopparapu et al. (2013), erratum (2014)
# ---------------------------------------------------------------------------

# Seff = Seff_sun + a*T + b*T^2 + c*T^3 + d*T^4, with T = Teff - 5780 K.
KOPPARAPU_COEFFS: dict[str, tuple[float, float, float, float, float]] = {
    "recent_venus": (1.776, 2.136e-4, 2.533e-8, -1.332e-11, -3.097e-15),
    "runaway_greenhouse": (1.107, 1.332e-4, 1.580e-8, -8.308e-12, -1.931e-15),
    "maximum_greenhouse": (0.356, 6.171e-5, 1.698e-9, -3.198e-12, -5.575e-16),
    "early_mars": (0.320, 5.547e-5, 1.526e-9, -2.874e-12, -5.011e-16),
}

KOPPARAPU_TEFF_MIN = 2600.0
KOPPARAPU_TEFF_MAX = 7200.0


@dataclass(frozen=True)
class HabitableZone:
    """Insolation limits in Earth units (S_earth = 1). Higher S = closer in."""

    teff_k: float
    recent_venus: float
    runaway_greenhouse: float
    maximum_greenhouse: float
    early_mars: float

    def zone_of(self, insolation_earth: float | None) -> str | None:
        """'conservative', 'optimistic', or None (outside both / unknown)."""
        s = insolation_earth
        if s is None or not math.isfinite(s) or s <= 0:
            return None
        if self.maximum_greenhouse <= s <= self.runaway_greenhouse:
            return "conservative"
        if self.early_mars <= s <= self.recent_venus:
            return "optimistic"
        return None


def habitable_zone_flux_limits(teff_k: float | None) -> HabitableZone | None:
    """None outside 2600-7200 K — the polynomial is not valid there."""
    if teff_k is None or not math.isfinite(teff_k):
        return None
    if not (KOPPARAPU_TEFF_MIN <= teff_k <= KOPPARAPU_TEFF_MAX):
        return None
    t = teff_k - 5780.0
    limits = {}
    for name, (s_sun, a, b, c, d) in KOPPARAPU_COEFFS.items():
        limits[name] = s_sun + a * t + b * t**2 + c * t**3 + d * t**4
    return HabitableZone(teff_k=teff_k, **limits)


def insolation_earth(
    insol: float | None = None,
    log_luminosity_solar: float | None = None,
    semi_major_axis_au: float | None = None,
) -> tuple[float | None, str]:
    """(S in Earth units, provenance).

    Prefers the archive's own `pl_insol`. Falls back to S = L / a^2 from the
    host's log-luminosity and the planet's semi-major axis — the definition
    of insolation, not an estimate.
    """
    if insol is not None and math.isfinite(insol) and insol > 0:
        return insol, "pl_insol"
    if (
        log_luminosity_solar is not None
        and semi_major_axis_au is not None
        and math.isfinite(log_luminosity_solar)
        and math.isfinite(semi_major_axis_au)
        and semi_major_axis_au > 0
    ):
        return (10.0**log_luminosity_solar) / (semi_major_axis_au**2), "derived_from_st_lum_and_pl_orbsmax"
    return None, "unavailable"


# ---------------------------------------------------------------------------
# 3a. Trans-Neptunian dynamical sub-classes (approximate)
# ---------------------------------------------------------------------------

# Mean-motion resonances with Neptune, as (p, q, label, half_width_au) where
# the TNO completes q orbits per p of Neptune's: a_res = a_N * (p/q)^(2/3).
# The half-widths are rough stand-ins for the real libration widths, which
# shrink with resonance order — a flat window wide enough for the 3:2 would
# swallow half the classical belt into the weak 7:4 (it puts Albion, the
# original cubewano, in a resonance it is not in).
NEPTUNE_RESONANCES: list[tuple[int, int, str, float]] = [
    (4, 3, "4_3", 0.3),
    (3, 2, "3_2_plutino", 0.5),
    (5, 3, "5_3", 0.3),
    (7, 4, "7_4", 0.2),
    (2, 1, "2_1_twotino", 0.4),
    (5, 2, "5_2", 0.6),
    (3, 1, "3_1", 0.5),
]

# Inside the main belt, a perihelion this low means Neptune is still able to
# handle the object; beyond the 2:1 the usual dividing line for "detached"
# is q > 40 AU.
CLASSICAL_MIN_PERIHELION_AU = 37.0
DETACHED_MIN_PERIHELION_AU = 40.0
COLD_CLASSICAL_MAX_INCLINATION_DEG = 5.0


def resonance_semi_major_axis(p: int, q: int, a_neptune_au: float) -> float:
    return a_neptune_au * (p / q) ** (2.0 / 3.0)


def tno_class(
    a_au: float | None,
    e: float | None,
    i_deg: float | None,
    a_neptune_au: float,
    q_au: float | None = None,
) -> tuple[str | None, str | None]:
    """(class, subclass) — approximate, see module docstring.

    Order of tests matters: resonance first (a plutino can have a
    scattered-looking perihelion), then Neptune-coupled scattering, then the
    classical belt, then everything beyond the 2:1 as detached.
    """
    if a_au is None or not math.isfinite(a_au) or a_au <= 0:
        return None, None
    if q_au is None and e is not None and math.isfinite(e):
        q_au = a_au * (1.0 - e)

    for p, q_res, label, half_width in NEPTUNE_RESONANCES:
        centre = resonance_semi_major_axis(p, q_res, a_neptune_au)
        if abs(a_au - centre) <= half_width:
            return "resonant", label

    a_classical_inner = resonance_semi_major_axis(3, 2, a_neptune_au)
    a_classical_outer = resonance_semi_major_axis(2, 1, a_neptune_au)

    if a_au < a_classical_inner:
        return "inner_belt", None

    if a_au <= a_classical_outer:
        if q_au is not None and q_au < CLASSICAL_MIN_PERIHELION_AU:
            return "scattered", None
        if i_deg is not None and math.isfinite(i_deg):
            hot_cold = "cold" if i_deg < COLD_CLASSICAL_MAX_INCLINATION_DEG else "hot"
        else:
            hot_cold = "unknown_inclination"
        return "classical", hot_cold

    # Beyond the 2:1: still Neptune-coupled (scattered) or decoupled (detached).
    if q_au is not None and q_au < DETACHED_MIN_PERIHELION_AU:
        return "scattered", None
    return "detached", None


# ---------------------------------------------------------------------------
# 3b. Jupiter trojans: L4 (Greek) vs L5 (Trojan) camp
# ---------------------------------------------------------------------------

JUPITER_MEAN_MOTION_DEG_PER_DAY = 0.0830975  # from Horizons; overridden by the pulled value


def mean_longitude_deg(node_deg: float, arg_peri_deg: float, mean_anomaly_deg: float) -> float:
    """L = Omega + omega + M, wrapped into [0, 360)."""
    return (node_deg + arg_peri_deg + mean_anomaly_deg) % 360.0


def propagate_mean_longitude_deg(
    l0_deg: float, epoch0_jd: float, epoch_jd: float, mean_motion_deg_per_day: float
) -> float:
    return (l0_deg + mean_motion_deg_per_day * (epoch_jd - epoch0_jd)) % 360.0


def trojan_camp(object_mean_longitude_deg: float, jupiter_mean_longitude_deg: float) -> str:
    """L4 leads Jupiter by ~60 deg, L5 trails it by ~60 deg."""
    delta = (object_mean_longitude_deg - jupiter_mean_longitude_deg) % 360.0
    return "l4" if 0.0 < delta < 180.0 else "l5"


# ---------------------------------------------------------------------------
# 4. MK luminosity class, for supergiants / hypergiants
# ---------------------------------------------------------------------------

HYPERGIANT_MARKERS = ("ia+", "ia-0", "ia0", "0-ia")
SUPERGIANT_CLASSES = ("ia+", "ia", "iab", "ib", "i")

# Longest first, so 'iab' is never read as 'ia', 'iii' never as 'ii', and
# 'iv' never as 'v'. Case-folded MK tokens.
_LUMINOSITY_TOKENS = ("viii", "vii", "iii", "iab", "vi", "iv", "ia", "ib", "ii", "v", "i")

_LUMINOSITY_DISPLAY = {"ia": "Ia", "iab": "Iab", "ib": "Ib"}


def luminosity_class(spectral_type: str | None) -> str | None:
    """'Ia+', 'Ia', 'Iab', 'Ib', 'I', 'II'... from an MK string, or None.

    HYG/SIMBAD spectral strings are messy ('K5III', 'B0.5Ia+', 'M2Iab-Ib',
    'G2V+K1V'); this reads the first luminosity-class token it can find and
    gives up rather than guessing when there isn't one.
    """
    if not spectral_type:
        return None
    s = spectral_type.strip().lower()
    for marker in HYPERGIANT_MARKERS:
        if marker in s:
            return "Ia+"
    best: tuple[int, str] | None = None
    for token in _LUMINOSITY_TOKENS:
        idx = s.find(token)
        if idx == -1:
            continue
        # Earliest match wins ('M2Iab-Ib' is a Iab); ties go to the longer
        # token, which _LUMINOSITY_TOKENS ordering already guarantees.
        if best is None or idx < best[0]:
            best = (idx, token)
    if best is None:
        return None
    token = best[1]
    return _LUMINOSITY_DISPLAY.get(token, token.upper())


def is_supergiant(spectral_type: str | None) -> bool:
    lc = luminosity_class(spectral_type)
    return lc is not None and lc.lower() in SUPERGIANT_CLASSES


def is_hypergiant(spectral_type: str | None) -> bool:
    return luminosity_class(spectral_type) == "Ia+"
