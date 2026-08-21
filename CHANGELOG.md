# Changelog

## 2026-08-21 — Fase 8: Link checker, Space-Track sesuai dokumentasi, TUI, Termux

### `astro links` — tes semua link, bukan cuma status code

Fase 1 percaya status code dan tertipu `nssdc_planetary_factsheet` (HTTP 200
tapi redirect ke halaman landing NASA). Link checker baru menuntut tiga hal:
status < 400, tidak redirect keluar dari host **atau path** yang diminta, dan
isi body benar-benar berbentuk format yang akan di-parse downloader.

Downloader sekarang mendeklarasikan sendiri URL yang akan dimintanya
(`_declare` / `declared_requests`), jadi yang diuji adalah target download
sungguhan — bukan daftar URL terpisah yang gampang basi. Query berat dicek
lewat kembaran murah (`top 5` untuk TAP, `limit=5` untuk SBDB, `limit/1`
untuk Space-Track) dan hanya 32 KB pertama body yang dibaca: 74 link
terverifikasi dengan biaya kilobyte.

Temuan nyata saat dijalankan, dan perbaikannya:

- OpenNGC/Messier ditandai rusak padahal sehat — CSV-nya delimiter `;`.
  Sniffer sekarang mengenali `,` `;` tab `|`.
- Kepler EB catalog ditandai rusak — file dibuka baris komentar `##`
  sebelum header. Sniffer melewati preamble berkomentar.
- Endpoint Space-Track menjawab 401 dan dihitung rusak; padahal 401 justru
  bukti endpoint hidup dan terjaga. 401/403 kini status tersendiri.
- VizieR (CDS) sempat 500 lalu normal lagi beberapa menit kemudian.
  Ditambah retry, dan **kegagalan sisi server dipisahkan dari link rusak**:
  5xx, timeout, atau pesan seperti "Unable to check the ADQL query!" /
  "TAP service too busy" dilaporkan sebagai *server-side outage — retry
  later*, bukan link mati. Pesan error server ikut ditampilkan, karena
  "HTTP 400" saja tidak memberi tahu apa-apa.
- Laporan single-source sempat menimpa laporan lengkap; sekarang di-merge.

Hasil run penuh 2026-08-21 (46 sumber / 74 URL): **37 siap didownload**,
4 kena gangguan server CDS/VizieR, 2 butuh kredensial, 2 access point tanpa
dataset sendiri, 1 benar-benar mati (`nssdc_planetary_factsheet`).

### Sumber yang tadinya tanpa downloader

Tiga celah ditutup setelah link-nya terbukti hidup:

- `gaia_dr3_nss` dan `gaia_dr3_tap` — ESA TAP sudah pulih dari 503 di Fase 1.
  Ditambah fetcher TAP **async (UWS)**: POST `/async`, poll `/phase`, ambil
  `/results/result`. Endpoint sync memotong di MAXREC (2000 baris di ESA),
  jadi tidak mungkin dipakai untuk katalog. Subset Tier 3 tetap sesuai brief:
  `parallax > 10 or phot_g_mean_mag < 12`.
- `open_exoplanet_catalogue` — ada mirror `oec_gzip/systems.xml.gz`, satu
  file gzip berisi seluruh sistem, jadi masalah "ribuan file XML" hilang.
  Di sesi ini github.com diblokir proxy (403), tapi di mesin/HP biasa jalan.

Sisanya sengaja tanpa downloader dan tercatat alasannya: `nssdc` (mati),
`simbad_tap` + `vizier_tap` (titik akses, bukan dataset), `usgs_gazetteer`
(shapefile per-benda), `ucs_satellite_db` (di balik form email).

### Space-Track sesuai `space-track.org/documentation#/api`

Ditulis ulang jadi klien penuh di `sources/spacetrack.py`. Dokumentasi
resmi diambil dan dibaca ulang 2026-08-21; yang bersifat aturan ikut
dipaksakan, bukan sekadar dicatat:

- Login cookie `/ajaxauth/login`, logout `/ajaxauth/logout`. Sukses = JSON
  string kosong; gagal = objek JSON. Cookie `chocolatechip` ikut diperiksa.
- URL REST lengkap: controller (`basicspacedata`, `expandedspacedata`,
  `fileshare`, `combinedopsdata`, `publicfiles`), action `query`/`modeldef`,
  predikat berurutan, `orderby`, `limit/N,offset`, `predicates`, `distinct`,
  `metadata`, `emptyresult/show`, `format`.
- Operator `>` `<` `,` `--` `~~` `^` `null-val` `now-N` dipertahankan saat
  percent-encoding; `>` jadi `%3E` persis seperti contoh di dokumentasi,
  sementara `/` dalam nilai justru di-encode agar tidak merusak path.
- **Throttle**: klien menahan diri di 25 req/menit dan 275 req/jam dengan
  jeda minimal 2 detik — di bawah batas resmi 30/menit dan 300/jam.
- **Frekuensi per class**: tabel data-retrieval di dokumentasi (GP 1/jam,
  SATCAT & BOXSCORE 1/hari setelah 1700 UTC, CDM tiap 8 jam, GP_HISTORY
  1/seumur-hidup, TIP 1/jam, DECAY 1/hari) dikodekan di `RETRIEVAL_POLICY`
  dan dicek terhadap ledger di disk. Pull yang terlalu cepat dilewati
  dengan alasan, bukan dikirim — melanggar aturan itu cara resmi untuk
  kena suspend.
- Batching comma-delimited untuk banyak objek, persis seperti yang diminta
  dokumentasi ("do not send hundreds of individual /class/gp/ queries").
- Query bawaan GP memakai pola yang disarankan dokumentasi:
  `/decay_date/null-val/epoch/%3Enow-10/`.

CLI baru: `astro spacetrack policy | query | modeldef`, dengan `--dry-run`
yang mencetak URL tanpa mengirim apa pun.

### TUI (`astro tui`)

Textual, empat tab (Sumber / Link / Space-Track / Log). Tabel 46 sumber
dengan filter teks + tier, panel detail yang menampilkan URL HTTP persis
yang akan diminta sumber itu, pull dan cek-link jalan di worker sehingga UI
tetap responsif. Panel Space-Track menampilkan status kredensial, batas
yang dipatuhi, dan kapan tiap class boleh diambil lagi.

Logika data dipisah ke `tui/state.py` (tanpa Textual) supaya bisa dites
tanpa terminal; sisanya dites headless lewat Pilot, termasuk layout sempit.

### Termux

- **Dependency inti jadi 100% pure Python.** `pydantic` dibuang dari core
  (`pydantic-core` adalah ekstensi Rust tanpa wheel Termux) dan diganti
  dataclass stdlib; `polars`/`beautifulsoup4`/`jsonschema` pindah ke extra
  `build`. Dependency yang ternyata tidak pernah diimpor (`pandas`,
  `pyarrow`, `astropy`, `astroquery`, `tqdm`) dihapus. `beautifulsoup4`
  yang selama ini terpakai tapi tidak terdaftar kini terdaftar.
  Diverifikasi: `pip install .` di venv bersih tidak memasang satu pun
  `.so`, dan `astro pull cneos_sentry` tetap menarik data sungguhan.
- **Path data tidak lagi diturunkan dari `__file__`.** Kalau paket
  di-install (hal normal di Termux), data akan mendarat di site-packages.
  Sekarang: `$ASTRO_DL_HOME` → repo (kalau source checkout) →
  `$XDG_DATA_HOME/astro-datalake` → `~/.local/share/astro-datalake`.
- `astro build`/`astro verify` memberi instruksi pemasangan yang jelas
  (termasuk catatan khusus Termux untuk polars) alih-alih ImportError.
- `astro doctor` baru: Python, deteksi Termux, folder data + izin tulis,
  ruang disk, paket opsional, lebar terminal, `TERM`, kredensial
  Space-Track, dan jangkauan jaringan ke tiap penyedia data.
- TUI beralih ke layout satu kolom di bawah 80 kolom (ukuran layar HP).
- `scripts/termux-setup.sh` untuk pemasangan sekali jalan.

### Tes

75 tes lolos: `test_spacetrack.py` (bentuk URL vs dokumentasi, encoding
operator, throttle, ledger, login sukses/gagal, 401, 429+retry, logout),
`test_linkcheck.py` (sniffing tiap format, redirect landing-page,
auth-wall, outage server vs link rusak, kembaran check-URL), dan
`test_tui.py` (headless lewat Pilot, termasuk layout HP).

## 2026-08-20 — Fase 3-4: Build struktur folder + Verifikasi

Full detail ada di masing-masing pesan commit dan di `REPORT.md`; ringkasan
di sini:

- `nssdc_planetary_factsheet` ternyata **mati** meski Fase 1 menandainya
  "hidup": seluruh path `/planetary/factsheet/*` 307-redirect ke halaman
  generik `nasa.gov/nssdc/`, bukan data fact sheet. Fase 1 hanya cek status
  code, bukan konten — pelajaran untuk probing endpoint yang redirect.
  Diganti pakai `jpl_horizons` OBJ_DATA.
- `.gitignore` punya bug: pola `build/`/`dist/` tanpa leading slash
  mencocokkan `astro_datalake/build/` juga (bukan cuma direktori artefak
  packaging di root), jadi modul builder sempat tidak ter-commit padahal
  jalan lokal. Diperbaiki jadi `/build/`, `/dist/`.
- `astro verify` menemukan bug schema: `limit_flag` di `sourced_value`
  diasumsikan string, padahal NASA Exoplanet Archive mengisinya numerik
  (0/1/-1) — 200/200 sampel `exoplanet_planet.json` gagal validasi sampai
  skema diperbaiki jadi `number|string|null`.
- Ditarik tambahan `openngc` + `messier_catalog` (tadinya salah ditandai
  Tier 3 di registry padahal cuma ~2MB) karena user minta pull semua.
- Build final: 469 objek solar_system, 465-467 bintang bernama, 6336
  exoplanet di 4749 folder bintang induk, 1.58 juta objek small-bodies
  (26530 di antaranya bernama & dapat folder sendiri), 70332 satelit
  buatan, 14077 objek deep-sky, 168903 baris sistem biner/multiple.
  Total ~1.9GB. Semua cek `astro verify` lulus setelah fix di atas.

## 2026-08-20 — Fase 2: Tarik data Tier 1 + Tier 2

Ran `astro pull --all --tier 1` then `astro pull --all --tier 2` (user
explicitly approved skipping the Tier 2 "report size, wait for
confirmation" pause — "gede juga gapapa, langsung pull aja"). Both via
`astro_datalake/downloaders.py` (new), wired into a now-real `astro pull`
CLI command (was a stub in Fase 0).

**Tier 1: 32/37 sources pulled, 0 errors, 5 deliberately skipped, ~421MB.**
**Tier 2: 4/6 sources pulled, 0 errors, 2 deliberately skipped, +~300MB.**
**Total raw data: ~723MB across 36 source folders.**

Deliberately skipped (documented per-source in `registry.py` notes, not
silent failures):
- `simbad_tap`, `vizier_tap` — access points used ad-hoc (crossmatch,
  per-catalog queries already covered by wds/msc/sb9), not bulk-dumped.
- `spacetrack`, `ucs_satellite_db` — require credentials/registration not
  available in this environment.
- `open_exoplanet_catalogue` — thousands of small per-system XML files on
  a GitHub repo outside this session's repo-access scope; would also mean
  thousands of individual 1 req/s requests. Needs a `git clone` done
  outside this constraint, or the repo added via `add_repo`.
- `usgs_gazetteer`, `gaia_dr3_nss` — Tier 2 but no download plan written
  yet (Gazetteer is per-body GIS shapefiles, not a flat table; Gaia NSS
  blocked by the same ESA 503 as `gaia_dr3_tap`, see Fase 1 notes).

Spot-checked (not fabricated, straight from the live responses):
HYG = 119,627 rows; `pscomppars` = 6,337 planets; SBDB `MBA.json` returned
exactly 1,378,000 rows matching its own `count` field (API did not
truncate); `MPCORB.DAT.gz` passes `gzip -t`.


Format: newest entry first. Every dead/changed endpoint discovered during
probing (Fase 1) or later gets logged here with the date, what was tried,
and what replaced it (if anything).

## 2026-08-20 — Fase 1: Probe endpoint

Ran `uv run python -m astro_datalake.probe` against all 46 registered
sources (small GET with `limit=5`/`top 5` where applicable, or HEAD).
Results written to `data/_catalog/sources.json` (gitignored, regenerable).

**43/46 alive, 2 dead (both same root cause), 1 skipped (needs credentials).**

Fixes applied to `astro_datalake/sources/registry.py` for endpoints that
were dead or wrong on the first pass:

- **`hyg_database`** — 404. The guessed filename `hyg_v42.csv` doesn't
  exist. Correct current file: `hygdata_v41.csv` (HYG v4.1) at
  `raw.githubusercontent.com/astronexus/HYG-Database/main/hyg/CURRENT/hygdata_v41.csv`.
  Fixed.
- **`iau_star_names`** — 404 (the `iau.org/public/themes/naming_stars/`
  page redirects through a login flow and 404s on direct fetch). Replaced
  with the **IAU-CSN** (IAU Catalog of Star Names) machine-readable file
  maintained by the IAU Division C Working Group on Star Names itself at
  `https://www.pas.rochester.edu/~emamajek/WGSN/IAU-CSN.txt` — notably,
  this file's own header cites the iau.org page as "the official IAU
  version," so it's the same data, just the actually-fetchable copy.
  Fixed.
- **`kepler_eb_catalog`** — 400 Bad Request over plain `http://`; the
  Villanova server accepts `https://` fine (200) but 500s on the
  `/results/?q=1` guess. Fixed the scheme; the real query-parameter format
  for `/results/` still needs to be reverse-engineered from the site before
  Fase 2 writes a real downloader for it (probe now just checks the
  homepage is up).
- **`msc_catalog`** — 400, "table J/ApJS/235/6/table1 is not found". Queried
  `TAP_SCHEMA.tables` on TAPVizieR and found the real table names for this
  catalog: `catalog`, `notes`, `orbits`, `systems`. Fixed to use
  `J/ApJS/235/6/catalog`.
- **`exoplanet_eu`** — looked dead (`ReadTimeout` at 20s) but is just slow:
  a plain GET streamed 1.5MB+ within 25s and was still going. Not dead;
  added a per-source `probe_timeout` override (45s) and switched
  `base_url`/`probe_url` from `http://` to `https://` (the `http://` URL
  301-redirects to `https://` anyway).

Still dead / unresolved:

- **`gaia_dr3_tap`** (Tier 3) and **`gaia_dr3_nss`** (Tier 2) — both
  `HTTP 503` from `gea.esac.esa.int`. Confirmed it's not a wrong URL: even
  the plain archive homepage (`gea.esac.esa.int/archive/`) timed out on
  retry, which points to an ESA-side outage/maintenance window, not a dead
  endpoint. Neither is needed for Tier 1, so this doesn't block Fase 2 —
  re-check before any Tier 2/3 pull that touches Gaia.
- **`spacetrack`** — skipped by design (requires a free account;
  `ASTRO_DL_SPACETRACK_USER`/`PASS` not set in this environment).

Also: created GitHub branch `main` from the Fase 0 commit (the repository
had zero branches/commits before this project), so the feature branch has
a base to open a PR against.

## 2026-08-20 — Fase 0: Scaffold

- Initial project scaffold: CLI (`astro pull|build|verify|status`), config,
  rate-limited/retrying HTTP client, checksum-based raw cache, folder-naming
  helpers, and the master source registry (`astro_datalake/sources/registry.py`)
  covering all sources listed in the task brief (sections A–H).
- No network calls made yet. Endpoint liveness has **not** been verified —
  that's Fase 1, next.
- Tier assignments in the registry are a best-effort mapping of the brief's
  Tier 1/2/3 lists onto concrete endpoints; a few sources not explicitly
  named in those lists (USGS Gazetteer, IAU star names, Gaia DR3 NSS,
  OpenNGC/Messier) carry a `notes` field explaining the assumption made and
  are flagged for reconsideration in the Fase 5 report.
