# Astro Data Lake

Local astronomical data lake: pulls astronomy data from official public
sources, normalizes it, and organizes it into a per-object/per-system folder
structure under `data/`.

## Ground rules

- Never fabricate scientific data. A missing field is `null`, and every
  value traces back to a source (`metadata.json` in each leaf folder).
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
├── models3d/       # stream fetchers for 3D mesh/texture sources (Fase 8)
└── schemas/        # pydantic v2 models for normalized objects (added in Fase 3)

data/
├── _catalog/       # master_index.json, crosswalk.parquet, sources.json, schema/
├── raw/            # untouched raw responses, per source per date (gitignored)
├── solar_system/   # sun, planets, dwarf planets, small bodies, artificial satellites
├── stars/          # by_name, by_constellation, by_spectral_type, by_distance, special
├── multiple_systems/
├── exoplanets/      # by_host_star, by_detection_method, by_type, by_mission, ...
├── deep_sky/        # messier, ngc, ic, nebulae, galaxies (tier 3)
└── models_3d/       # model 3D + tekstur per objek (spacecraft/, comets/, asteroids/, ...)
```

## Model 3D & tekstur

`data/models_3d/` holds actual mesh files (GLB/OBJ/STL/WRL/3DS/BLEND/USDZ) and
texture maps per object, not tables:

```
models_3d/
├── spacecraft/            # Hubble, JWST, Cassini, Voyager, Juno, ISS, rovers, ...
├── ground_and_equipment/  # DSN dishes, spacesuits, tools, buildings
├── comets/                # 67P, Wild 2, Hartley 2, Tempel 1, Halley (PDS shape models)
├── asteroids/             # Bennu, Eros, Itokawa, Vesta, ... + _damit/ (16k models)
├── moons/                 # shape models + surface texture maps
├── planets/  stars/  sky_maps/  deep_sky/  surface_features/  earth_science/
```

Each object folder keeps the upstream files as-is plus `model_3d.json` (every
file with its role, format, checksum, source and license) and a `README.md`
carrying the attribution the source asks for. Asset files are **hardlinked**
from `data/raw/`, so the tree costs almost no extra disk.

Category assignment is honest about its provenance: PDS SBN objects use that
catalog's own comet/asteroid/satellite type, while NASA's catalogs only ship
folder names, so those are bucketed by the regex rules in
`astro_datalake/build/models_3d.py` — recorded per object in `classified_by`.

`data/` (except `data/_catalog/schema/`) is gitignored — it's generated
output, regenerated with `astro pull` + `astro build`, not versioned.

## Tiering

- **Tier 1** (~hundreds of MB): runs without asking — planets, moons,
  exoplanets (all tables), HYG stars, binary catalogs (WDS/SB9/MSC), active
  artificial satellites, NEO asteroids + Sentry + close-approach data.
- **Tier 2** (~5-20 GB): reports an estimated size and waits for
  confirmation — full MPCORB (~1.4M asteroids), full SBDB (all classes),
  full SATCAT, Kepler/TESS lightcurve metadata, the NASA 3D Resources repo
  (~4.7 GB), the DAMIT export (~1.3 GB), SVS texture kits.
- **Tier 3** (hundreds of GB-TB): never runs without an explicit, separate
  instruction — full Gaia DR3 source catalog, FITS/photo data, raw
  lightcurves. Default subset when it does run: parallax > 10 mas OR G < 12.

See `astro_datalake/sources/registry.py` for the exact source -> tier
mapping and `CHANGELOG.md` for endpoint verification results.

## Status

Project is being built phase by phase (see `CHANGELOG.md`, full write-up in
`REPORT.md`). Latest phase: **Fase 8 — 3D models + textures**: 6 new sources
pulled (~14 GB raw), `data/models_3d/` built with 382 objects / 2192 asset
files plus 16,105 DAMIT asteroid shape models, `astro verify` green.
