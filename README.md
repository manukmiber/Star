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
uv sync                 # core + dev
uv sync --extra build   # also polars / BeautifulSoup / jsonschema (for build + verify)
```

On a phone, see [Termux](#termux-android) below.

## CLI

```bash
astro doctor               # check this machine: paths, disk, packages, terminal, network
astro links                # test every download link, report what's ready to pull
astro pull <source>        # pull one source (see `astro status` for keys)
astro pull --all --tier 1  # pull every source in a tier
astro build                # normalize raw -> processed folder structure
astro verify               # checksum / row-count / empty-folder / schema checks
astro status               # summary: what's been pulled, sizes, dates
astro tui                  # interactive terminal UI
astro spacetrack policy    # Space-Track presets + retrieval-rate status
```

## TUI

`astro tui` opens a Textual UI over the same machinery the CLI uses — it
calls `DOWNLOAD_PLAN` and `linkcheck` directly, so the two can't drift apart.

```
┌ Sumber ┬ Link ┬ Space-Track ┬ Log ┐
│ 46 sources, tier/status/link-verdict/size, live filter and tier picker    │
│ detail pane shows the exact HTTP requests that source will issue          │
└──────────────────────────────────────────────────────────────────────────┘
```

| Key | Action |
| --- | --- |
| `space` | select / deselect the highlighted source |
| `a` / `c` | select every ready source in view / clear the selection |
| `p` | pull the selection (or the highlighted source) |
| `l` | re-check links for the selection (or everything in view) |
| `s` | pull Space-Track |
| `/` | focus the search box |
| `r` | reload state from disk |
| `q` | quit |

Long jobs run in Textual workers, so the table keeps repainting while a
multi-hundred-megabyte pull is in flight. Below 80 columns the layout
switches to a stacked, single-column mode meant for a phone.

## Link checking

`astro links` is stricter than a status-code ping, because a status code
lies: `nssdc_planetary_factsheet` answers `200` while redirecting to a
generic NASA landing page with none of the promised data. A link counts as
working only when it answers < 400, doesn't redirect away from the host *or
path* we asked for, and returns a body that actually looks like the format
the downloader will parse (JSON parses, CSV has a delimited header row —
semicolons and `#`-comment preambles included — gzip has its magic number,
TLE has 69-character element lines).

Failures are split by fault. A 5xx, a timeout, or a message like CDS's
"Unable to check the ADQL query!" is reported as a **server-side outage**
("retry later"), not a broken link — those URLs are demonstrably correct and
answer fine minutes later. Only a genuine 404, a bad redirect, or wrong
content is called broken.

Heavy sources are checked through a cheap twin of the real request (a TAP
`top 5`, an SBDB `limit=5`, a Space-Track `limit/1`), and only the first
32 KB of any body is read, so verifying all 74 links costs kilobytes.
Results land in `data/_catalog/link-check.json`, merged rather than
overwritten so checking one source doesn't discard what's known about the
rest.

## Space-Track

Implemented against [the documented API](https://www.space-track.org/documentation#/api):
cookie login at `/ajaxauth/login`, REST query URLs
(`/basicspacedata/query/class/<class>/<predicate>/<value>/.../format/json`),
`>` `<` `,` `--` `~~` `^` `null-val` `now-N` operators, `/modeldef/` for
predicate definitions, and logout on the way out.

The guidelines are enforced, not just read:

- **Throttling** — the client holds itself to 25 requests/minute and
  275/hour with a 2-second floor between requests, under the documented
  ceilings of 30/minute and 300/hour.
- **Retrieval frequency** — the documentation's per-class rate table (GP
  once/hour, SATCAT and BOXSCORE once/day after 1700 UTC, CDM every 8 hours,
  GP_HISTORY once per lifetime, …) is encoded in `RETRIEVAL_POLICY` and
  checked against an on-disk ledger. A too-soon pull is skipped with a
  reason rather than sent — violating those rates is the documented way to
  get an account suspended.
- **Batching** — multiple objects go out as one comma-delimited request,
  which the docs ask for explicitly.

```bash
export ASTRO_DL_SPACETRACK_USER='your-email'      # free account at space-track.org
export ASTRO_DL_SPACETRACK_PASS='your-password'

astro spacetrack policy                            # what's due, what's rate-limited
astro spacetrack query gp --norad 25544,43873 --format tle
astro spacetrack query --preset satcat --save      # store under data/raw/ with a checksum
astro spacetrack modeldef gp                       # the API's own predicate list
astro spacetrack query decay -P MSG_EPOCH='>now-1' --dry-run   # print the URL, send nothing
```

Without credentials the source is skipped, never faked.

## Termux (Android)

```bash
pkg install git
git clone <repo> && cd Star
bash scripts/termux-setup.sh
```

The core install is **100% pure Python** — no compiler, no Rust toolchain,
no native wheels. `astro pull`, `astro links`, `astro status`, `astro tui`,
`astro doctor` and `astro spacetrack` all run on a stock `pkg install
python`. (Settings deliberately use a stdlib dataclass instead of pydantic,
whose `pydantic-core` has no Termux wheel.)

`astro build` and `astro verify` additionally need polars / BeautifulSoup /
jsonschema — the `build` extra. polars has no prebuilt Termux wheel, so
either compile it (`pkg install rust binutils && pip install
'astro-datalake[build]'`) or run `astro build` elsewhere and copy `data/`
over.

Data location resolves in this order: `$ASTRO_DL_HOME`, then the repo when
running from a source checkout, then `$XDG_DATA_HOME/astro-datalake` or
`~/.local/share/astro-datalake`. That last step matters once the package is
pip-installed — without it, catalogues would land inside site-packages.
Run `astro doctor` to see what this device resolved to, plus free disk,
terminal width and network reachability.

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
├── multiple_systems/
├── exoplanets/      # by_host_star, by_detection_method, by_type, by_mission, ...
└── deep_sky/        # messier, ngc, ic, nebulae, galaxies (tier 3)
```

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

## Status

Built phase by phase — see CHANGELOG.md. Latest run of `astro links`
(2026-08-21, all 46 sources / 74 declared URLs): **37 ready to download**,
4 hitting a CDS/VizieR server-side outage, 2 behind a credential wall
(Space-Track, UCS), 2 access points with no bulk dataset of their own
(SIMBAD TAP, USGS Gazetteer), and 1 genuinely dead (`nssdc_planetary_factsheet`,
which redirects to a NASA landing page — physical planet parameters come
from JPL Horizons instead).
