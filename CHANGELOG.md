# Changelog

## 2026-08-21 — Fase 8: lengkapi semua link download + frontend Cloudflare

### Link registry (`astro_datalake/sources/links.py`)

Semua URL download sekarang jadi **data**, bukan kode: satu `DownloadTarget`
per file (URL, method, params, form body, header, timeout, perkiraan ukuran).
47 sumber, 113 target, dan satu definisi itu dipakai bareng oleh downloader,
generator manifest, situs statis, dan Worker — jadi link tidak bisa beda-beda
antar tempat.

`downloaders.py` ditulis ulang di atas registry itu. Yang tadinya
**38 dari 46 sumber** bisa ditarik, sekarang **45 dari 47**.

### Sumber yang tadinya dilewati, sekarang jalan

Semua diverifikasi live 2026-08-21, bukan tebakan:

- **`usgs_gazetteer`** — catatan lama bilang datanya cuma tersedia sebagai
  ~100 shapefile GIS per-benda. Salah: POST kosong ke `/SearchResults`
  meng-export **seluruh gazetteer dalam satu tabel HTML** — 16.353 fitur
  resmi di semua benda (Moon 9.201, Mars 2.096, Venus 2.046, Merkurius 606,
  Titan 305, ...), 42,6 MB, lengkap dengan diameter, lat-lon pusat/batas,
  sistem koordinat, tipe fitur, dan tanggal persetujuan. Dinaikkan ke Tier 1.
- **`open_exoplanet_catalogue`** — repo utamanya satu XML per sistem (ribuan
  file) dan endpoint tarball GitHub diblokir di environment ini. Tapi proyek
  OEC sendiri menerbitkan seluruh katalog sebagai satu XML ter-gzip di repo
  pendamping `oec_gzip` (1,05 MB, di-refresh tiap commit). Beres.
- **`ucs_satellite_db`** — tadinya ditandai butuh kredensial karena halaman
  landing-nya cuma menawarkan form opt-in email. Ternyata link media-nya
  publik tanpa autentikasi: `https://www.ucs.org/media/11492` → .xlsx 1,5 MB.
  `requires_credentials` dicabut.
- **`simbad_tap`** — sebelumnya tidak ditarik sama sekali (`basic` >15 juta
  baris). Sekarang dua query ADQL terbatas: `basic` di-join ke `allfluxes`
  untuk V < 10, plus cross-identifier `ident` untuk subset yang sama.
  Catatan: magnitudo ada di `allfluxes`, bukan `basic` — `where V < 10` polos
  balas HTTP 400 "Unknown column V".
- **`gaia_dr3_tap` / `gaia_dr3_nss`** — HTTP 503 waktu Fase 1 ternyata outage
  sementara di sisi ESA; server jawab normal lagi. Subset default Tier 3
  (parallax > 10 mas ATAU G < 12) **dihitung live: 3.602.117 baris**, bukan
  diperkirakan. Dipecah jadi 37 potongan `random_index` biar tiap potongan
  muat di endpoint sync (satu potongan 50 juta lebar ≈ 90 ribu baris, ~70 s).
- **`vizier_tap`** — dulu cuma "titik akses, bukan dataset". Sekarang punya
  artefak sendiri: METAcat, indeks semua katalog yang dilayani VizieR, lewat
  endpoint ASU (4,65 MB). Catatan: query `TAP_SCHEMA` di TAPVizieR balas
  HTTP 500 (bug translasi SQL di server), jadi ASU yang dipakai.
- **`spacetrack`** — sekarang punya downloader beneran (POST login →
  cookie sesi → GET query gp/satcat/decay), bukan cuma "skip". Tetap
  dilewati kalau `ASTRO_DL_SPACETRACK_USER`/`PASS` tidak diset.

### `nssdc_planetary_factsheet` diganti, bukan ditambal

Dicek ulang 2026-08-21: `marsfact.html` dan `planet_table_ratio.html`
dua-duanya balas halaman landing nasa.gov 245 kB yang byte-nya identik —
redirect-nya bukan per-path, memang tidak ada yang tersisa. Ditandai
`retired` dengan `replaced_by` yang eksplisit.

Penggantinya, sumber baru **`le_systeme_solaire`**: satu request → 554 benda
(8 planet, 4 planet katai, 479 bulan, 55 asteroid, 7 komet, Matahari) dengan
massa, volume, densitas, gravitasi, kecepatan lepas, radius rata-rata/
ekuator/kutub, flattening, periode orbit & rotasi sidereal, kemiringan
sumbu, suhu rata-rata, elemen orbit, dan data penemuan. Butuh header
`Authorization: Bearer <key>`; key gratis ditaruh sebagai default di
`core/config.py` (override lewat `ASTRO_DL_SOLARSYSTEM_API_KEY`) supaya
sumbernya langsung jalan tanpa setup.

Nilai key tidak pernah bocor ke artefak publik: manifest hanya menerbitkan
*nama* header, dan cuplikan curl di situs menampilkan
`$ASTRO_DL_SOLARSYSTEM_API_KEY`. Ada test yang menjaga itu.

### Frontend Cloudflare — memperbaiki build yang gagal

Build gagal dengan:

```
✘ [ERROR] Could not detect a directory containing static files
          (e.g. html, css and js) for the project
```

Penyebabnya: repo ini proyek Python tanpa config wrangler sama sekali, jadi
`npx wrangler deploy` tidak punya entrypoint maupun direktori aset untuk
ditebak. Ditambahkan:

- **`wrangler.toml`** — `main` + `[assets]` (layout Workers Static Assets),
  jadi `npx wrangler deploy` jalan tanpa mengubah deploy command.
- **`worker/index.js`** — API JSON kecil di atas manifest. Worker sengaja
  **tidak pernah** mengalirkan dataset lewat dirinya sendiri: file di sini
  ukurannya 70 kB sampai ~200 MB, jadi `/api/download/<key>` cuma `302` ke
  host asalnya. Byte-nya jalan sumber → klien, dan download 200 MB cuma
  memakan satu penulisan header di Worker.
- **`public/`** — indeks download statis yang di-render dari `manifest.json`:
  filter per tier/status/kata kunci, tiap file dengan URL, method, ukuran.
  Target yang butuh POST body atau header auth ditampilkan sebagai perintah
  curl, bukan link yang pasti gagal.
- **`astro manifest`** — menulis `public/manifest.json` dari `links.py`.
  Filenya di-commit karena build Cloudflare cuma menjalankan `uv sync` dan
  `npx wrangler deploy` (tidak ada langkah generate di CI); `--check` dan
  satu test gagal kalau salinannya sudah basi.

Diverifikasi lokal: `wrangler deploy --dry-run` membaca direktori aset dan
lolos, `wrangler dev` melayani semua rute, dan halaman di-render headless
tanpa error JS.

### Tes

`tests/test_links.py` — kelengkapan registry, bentuk URL (https, host, nama
file aman, tidak ada duplikat), potongan Gaia harus bersambung tanpa celah
atau tumpang tindih, setiap sumber yang dilewati wajib punya alasan, dan
nilai header rahasia tidak boleh muncul di output terbitan.


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
