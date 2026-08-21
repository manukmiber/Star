# Astro Data Lake

Local astronomical data lake: pulls astronomy data from official public
sources, normalizes it, and organizes it into a per-object/per-system folder
structure under `data/`.

## Ground rules

- Never fabricate scientific data. A missing field is `null`, and every
  value traces back to a source (`metadata.json` in each leaf folder).
- Anything computed rather than copied says so. Derived folders (exoplanet
  `by_type/`, `habitable_zone/`, TNO sub-classes, trojan L4/L5 camps, named
  binaries) record `derived_from` and `classification_method` in their
  `metadata.json`, and `astro verify` fails a build where a derived folder
  does not. Where a published formula has a stated validity range, going
  outside it returns "not assessed", never an extrapolation.
- Attribution travels with the data. `astro build` stamps the licence line
  of each folder's source into that folder's `README.md`, so a folder stays
  attributed when it is copied out of the tree.
- Every raw download is cached by checksum and never overwritten; raw
  responses live untouched under `data/raw/<source>/<date>/`.
- Requests are rate-limited (default 1 req/s per domain) with exponential
  backoff retry, and identify themselves with a clear `User-Agent`.
- Heavy pulls (Tier 2/3, see below) never run without explicit confirmation.

## Setup

```bash
uv sync
```

## CLI

```bash
astro pull <source>        # pull one source (see `astro status` for keys)
astro pull --all --tier 1  # pull every source in a tier
astro build                # normalize raw -> processed folder structure
astro verify                # checksum / row-count / empty-folder / schema checks
astro status                 # summary: what's been pulled, sizes, dates
```

## Project layout

```
astro_datalake/
├── cli/            # typer CLI (main.py + commands/{pull,build,verify,status}.py)
├── core/           # config, logging, rate-limited HTTP client, checksum cache, naming
├── sources/        # registry.py: every source, its tier, and its probe endpoint
└── schemas/        # pydantic v2 models for normalized objects (added in Fase 3)

data/
├── _catalog/       # master_index.json, crosswalk.parquet, sources.json, schema/
├── raw/            # untouched raw responses, per source per date (gitignored)
├── solar_system/   # sun, planets, dwarf planets, small bodies, artificial satellites
├── stars/          # by_name, by_constellation, by_spectral_type, by_distance, special
├── multiple_systems/   # binary/<named system>, triple, quadruple, star_clusters,
│                       # _catalogs/ (raw WDS/SB9/MSC dumps)
├── exoplanets/         # by_host_star, by_type, habitable_zone,
│                       # by_detection_method, candidates
└── deep_sky/           # messier, ngc, ic, nebulae, galaxies (tier 3)
```

Two structural notes: `solar_system/small_bodies/` also carries
`trojans/{l4,l5}`, `trans_neptunian/{classical,resonant,scattered,detached}`,
`comets/interstellar/` and `meteor_showers/`; `stars/special/` carries
pulsars, magnetars, neutron stars, black holes, brown dwarfs, supergiants,
hypergiants, variables and white dwarfs.

`data/` (except `data/_catalog/schema/`) is gitignored — it's generated
output, regenerated with `astro pull` + `astro build`, not versioned.

## Tiering

- **Tier 1** (~hundreds of MB): runs without asking — planets, moons,
  exoplanets (all tables), HYG stars, binary catalogs (WDS/SB9/MSC), active
  artificial satellites, NEO asteroids + Sentry + close-approach data.
- **Tier 2** (~5-20 GB): reports an estimated size and waits for
  confirmation — full MPCORB (~1.4M asteroids), full SBDB (all classes),
  full SATCAT, Kepler/TESS lightcurve metadata.
- **Tier 3** (hundreds of GB-TB): never runs without an explicit, separate
  instruction — full Gaia DR3 source catalog, FITS/photo data, raw
  lightcurves. Default subset when it does run: parallax > 10 mas OR G < 12.

See `astro_datalake/sources/registry.py` for the exact source -> tier
mapping and `CHANGELOG.md` for endpoint verification results.

## Derived categories

Some folders group objects by a property no catalogue publishes as a column
— an exoplanet's "type", whether it is in the habitable zone, which
Lagrange camp a Jupiter trojan sits in. Those rules live in one place,
`astro_datalake/build/classify.py`, with the thresholds as named constants
and the papers they come from in the docstring. Two things follow from that:

- The rules are testable, and tested against objects whose classification
  is not in dispute — Jupiter is a cold gas giant, Earth is in the
  conservative habitable zone, Pluto is a plutino, Achilles is L4,
  Patroclus is L5.
- Where a rule is genuinely approximate it says so everywhere it lands.
  The trans-Neptunian sub-classes are (a, q, e, i) cuts, not the numerical
  integration real resonance membership needs, and every metadata.json in
  that tree carries that caveat.

## Status

Project is built phase by phase (see CHANGELOG.md). Current phase:
**Fase 5 — closing the gaps REPORT.md §5 listed as unbuilt**. Everything
there is now built except asteroid-family membership, which still needs a
proper-elements catalogue. See `REPORT.md` for object counts, sizes,
sources and what remains open.
