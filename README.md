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
astro manifest             # regenerate public/manifest.json (the download index)
```

## TUI

`astro tui` opens a Textual UI over the same machinery the CLI uses — it
calls `DOWNLOAD_PLAN` and `linkcheck` directly, so the two can't drift apart.

```
┌ Sumber ┬ Link ┬ Space-Track ┬ Log ┐
│ 52 sources, tier/status/link-verdict/size, live filter and tier picker    │
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

Targets come from `sources/links.py`, so what gets verified is exactly what
`astro pull`, `astro manifest` and the website will fetch. Each check uses a
cheap twin derived from the target's own parameters — an ADQL `top 5`, a
`MAXREC`/`limit` cap — and reads at most 32 KB of the body, so a full run
costs kilobytes rather than gigabytes. POST targets are checked with POST
(the USGS Gazetteer is a POST-only search form; GETting it just returns 500).

`gaia_dr3_tap` is 182 targets that are one ADQL query sliced by
`random_index`; those are checked as a spread of four rather than all 182,
and the report says so. Sources whose targets are genuinely different
requests — `jpl_horizons`' ten bodies, `sbdb_query_full`'s eleven orbit
classes — are always checked in full. `--full` checks everything.

Results land in `data/_catalog/link-check.json`, merged rather than
overwritten so checking one source doesn't discard what's known about the
rest.

Latest full run (2026-08-22, 52 sources / 276 registered targets, 98
checked): **47 ready to download**, 3 hitting the intermittent CDS/VizieR
TAP outage, 1 retired (`nssdc_planetary_factsheet`, superseded by
`le_systeme_solaire` + `jpl_horizons`), and 1 behind a credential wall
(Space-Track).

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


## Download links

Every source's exact download URL lives in `astro_datalake/sources/links.py`
as data, not as code. One `DownloadTarget` per file to fetch, carrying its
URL, HTTP method, query parameters, form body, headers, timeout and expected
size. A source is in exactly one state:

| Status | Meaning |
|---|---|
| `direct` | Plain GET URL; click it or `curl` it as-is. |
| `query` | GET/POST with parameters (TAP/ADQL, SBDB, a form POST). Still fully resolvable. |
| `credentialed` | Real documented endpoint, needs an account (`spacetrack`). |
| `retired` | Endpoint is gone; `replaced_by` names what covers it now. |

That one definition feeds three consumers, so a link can never disagree with
itself:

- `astro_datalake/downloaders.py` turns each target into an async fetcher,
- `astro manifest` renders `public/manifest.json`,
- the static site and the Worker read that manifest.

50 of the 52 sources are fetchable with no setup. The two that are not:
`nssdc_planetary_factsheet` (retired — NASA now 307-redirects the whole
fact-sheet path to a generic landing page; `le_systeme_solaire` and
`jpl_horizons` cover the same parameters) and `spacetrack` (free account
required; set `ASTRO_DL_SPACETRACK_USER` / `ASTRO_DL_SPACETRACK_PASS`).

### API keys

`le_systeme_solaire` needs `Authorization: Bearer <key>`. A working key is
checked into `core/config.py` as the default so the source works out of the
box; override it with `ASTRO_DL_SOLARSYSTEM_API_KEY`. The key is deliberately
kept out of every published artifact — the manifest publishes header *names*
only, and the site's curl snippets show `$ASTRO_DL_SOLARSYSTEM_API_KEY` in
place of the value. A test enforces this.

## Web frontend (Cloudflare)

`public/` is a static download index rendered from `manifest.json`, and
`worker/index.js` is a small JSON API over the same manifest.

The Worker deliberately never streams a dataset through itself — catalogue
files here run from 70 KB to ~200 MB. It only reads the manifest, answers
filter/lookup queries over ~110 entries, and `302`s download requests
straight to the upstream host, so the bytes go source → client and a large
download costs the Worker one header write.

```
GET /api/health                       manifest freshness + counts
GET /api/sources?tier=&category=&q=   filtered source list
GET /api/sources/<key>                one source with all its targets
GET /api/download/<key>[/<file>]      302 to upstream (or the recipe, if the
                                      target needs a POST body or auth header)
```

### Deploying

The build was failing with:

```
✘ [ERROR] Could not detect a directory containing static files
          (e.g. html, css and js) for the project
```

because the repo is a Python project that had no wrangler config at all, so
`npx wrangler deploy` had neither an entrypoint nor an assets directory to
infer. `wrangler.toml` now supplies both (`main` + `[assets]`), which is the
Workers Static Assets layout, and `npx wrangler deploy` works unchanged.

`public/manifest.json` is committed because the Cloudflare build only runs
`uv sync` and `npx wrangler deploy` — there is no generation step in CI. Run
`astro manifest` after touching `links.py`; `astro manifest --check` (and a
test) fails if the committed copy has drifted.

If your Cloudflare project is Pages rather than Workers, deploy with
`npx wrangler pages deploy public` instead — don't add `pages_build_output_dir`
to `wrangler.toml`, it conflicts with `main`.

## Project layout

```
astro_datalake/
├── cli/            # typer CLI (main.py + commands/{pull,build,verify,status}.py)
├── core/           # config, logging, rate-limited HTTP client, checksum cache, naming
├── sources/        # registry.py: source -> tier/probe; links.py: source -> download URLs
├── downloaders.py  # fetchers generated from links.py
├── manifest.py     # renders public/manifest.json from links.py
└── schemas/        # pydantic v2 models for normalized objects (added in Fase 3)

public/             # static download index (index.html + app.js + manifest.json)
worker/             # Cloudflare Worker: catalogue JSON API + download redirects
wrangler.toml       # Workers + static assets deploy config

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

Project is built phase by phase (see CHANGELOG.md). Fase 5 closed the gaps
REPORT.md §5 listed as unbuilt — everything there is built except
asteroid-family membership, which still needs a proper-elements catalogue.
Fase 8 completed the download-link registry for all 52 sources and added the
Cloudflare frontend, then added `astro links` (live verification of every
registered target), a Space-Track client that follows the documented API
rules, the TUI, and a pure-Python core that installs on Termux. See
`REPORT.md` for object counts, sizes, sources and what remains open, and
`data/_catalog/link-check.json` for the latest link-verification run.
