# Changelog

## 2026-08-21 — Fase 8: Model 3D + tekstur (`data/models_3d/`)

Permintaan: "download semua 3D model yang tersedia, bahkan texture kalau
tersedia — satelit buatan manusia (Hubble, JWST, dll), komet, bintang, dll".

Delapan sumber baru terdaftar di `registry.py` (kategori `models_3d/*`), enam
di antaranya benar-benar ditarik lewat mekanisme baru: **stream fetcher**
(`astro_datalake/models3d/`). Berbeda dari `DOWNLOAD_PLAN` yang menahan
seluruh respons di memori, fetcher ini menulis langsung ke disk sambil
menghitung checksum — arsip DAMIT saja 1,3 GB, dan yang dilewati karena batas
ukuran ada yang 2,4 GB; tidak masuk akal di-buffer di memori.

**Yang ditarik:**

| Sumber | Hasil |
|---|---|
| `nasa_3d_resources` (GitHub, commit `11ebb4e`) | 1199 file, 4,7 GB — 227 model, 108 model cetak, 50 set tekstur |
| `pds_sbn_shape_models` | 241 file, 6,2 GB — 64 objek (5 komet, 36 asteroid, 23 satelit alami) |
| `damit_shape_models` | 1 arsip, 1,3 GB — 10.757 asteroid / 16.105 model bentuk |
| `nasa_science_3d` | 216 item katalog, 461 file, 1,3 GB (STL cetak + deskripsi) |
| `nasa_svs_texture_kits` | 19 file, 1,8 GB — CGI Moon Kit (LROC color + LOLA displacement) |
| `nasa_blue_marble_textures` | 25 file, 36 MB — tekstur Bumi Blue Marble |

**Temuan endpoint (semua diverifikasi 2026-08-21):**

- **`nasa3d.arc.nasa.gov` sudah mati** — 301 ke `science.nasa.gov/3d-resources/`,
  dan halaman itu sendiri menunjuk balik ke repo GitHub `nasa/NASA-3D-Resources`.
  Jadi repo-nya yang di-clone; situs barunya tetap ditarik terpisah karena
  memuat STL cetak + deskripsi yang TIDAK ada di repo.
- Listing HTML `science.nasa.gov/3d-resources/` **mengabaikan** `current_page`
  dan `number_of_items` (selalu 15 item halaman pertama). Yang bisa dipaginasi
  cuma REST-nya: `wp-json/smd/v1/content-list` (`order` harus `ASC`/`DESC`
  huruf besar, kalau tidak 400).
- Katalog PDS SBN ada di **JavaScript**, bukan HTML: `js/app.Data.js` +
  `js/app.Datasets.js`, dengan referensi antar-file (`Hudson.basepath + '…'`)
  yang harus di-resolve. Parser-nya di `models3d/sbn.py`.
- Link relatif di katalog itu ditulis relatif ke `/pds/`, bukan ke halamannya.
  Kalau di-resolve ke halaman, server membalas **HTTP 200 + HTML shell**, bukan
  404 — jadi fetcher mengecek isi file (magic bytes), bukan status code.
- `sbn.psi.edu` juga punya link mati beneran (6 URL 404) dan satu typo di
  sumbernya (`'Hudson.basepath' + '…'`, nama const ikut di dalam kutip).
  Semua dicatat di `manifest.json`, tidak disamarkan.
- `science.nasa.gov` sendiri menaut 22 file yang 404 di CDN-nya.
- `www.darts.isas.jaxa.jp` (shape model Ryugu dari Hayabusa2) **diblokir
  network policy environment ini** (CONNECT ditolak 502 oleh proxy) — bukan
  masalah endpoint.
- `solarsystemscope.com` (tekstur CC BY 4.0) **seluruhnya di balik captcha
  bot-gate**: `/textures/` dan URL unduhan langsung sama-sama membalas HTTP 202
  berisi redirect ke `/.well-known/sgcaptcha/`. Tidak ditembus; tekstur setara
  diambil dari NASA.
- `astrogeology.usgs.gov` punya JSON search (1643 entri) tapi file mosaiknya
  ada di resource CKAN per-dataset dan berukuran puluhan–ratusan GB per body —
  didaftarkan sebagai Tier 3 dan tidak ditarik (sama seperti `usgs_gazetteer`).
- SVS `/api/search/?q=…` **mengabaikan `q`** (selalu mengembalikan seluruh
  10.554 item), jadi halaman texture kit disebut per-ID, bukan hasil pencarian.

**Build (`astro build` → `data/models_3d/`):** 382 objek dalam 11 kategori, 2192
file, 15,9 GB "logis" — tapi aset-nya hardlink ke `data/raw/`, jadi tambahan disk
sebenarnya cuma hasil ekstraksi arsip. Ditambah `asteroids/_damit/`: 80.511 file
(10.757 asteroid, 16.105 model bentuk).

Rincian: 333 objek punya mesh, 368 punya tekstur; 1280 file mesh, 805 tekstur,
29 arsip sumber. Format terbanyak: 516 GLB, 484 STL, 421 PNG, 204 JPG, 127 TIF,
72 LWO, 57 OBJ, 56 TAB (PDS), 44 USDZ, 20 BDS, 14 BLEND. Per sumber: 1647 file
dari `nasa_3d_resources`, 260 `nasa_science_3d`, 241 `pds_sbn_shape_models`,
25 Blue Marble, 19 SVS.

- Aset di-**hardlink**, tidak disalin.
- Arsip `.7z` bawaan NASA (29 buah, 2,0 GB terekstrak) dibongkar ke
  `<nama>_extracted/` — di dalamnya ada 128 JPG + 60 TIF tekstur, scene
  LightWave/Maya/3ds Max, dan STL tambahan yang kalau dibiarkan terkompresi
  tidak kelihatan sama sekali. Butuh dependensi baru: `py7zr`.
- Kategori: tipe dari PDS SBN dipakai apa adanya; katalog NASA cuma punya nama
  folder, jadi ditebak lewat aturan regex dan **tebakan itu ditulis di field
  `classified_by`** tiap `model_3d.json`, bukan disamarkan jadi fakta sumber.
- Objek yang sama dari beberapa sumber digabung ke satu folder: mis.
  `spacecraft/hubble_space_telescope/` memuat GLB varian A + B, arsip sumber
  varian B, dan 7 STL cetak, semuanya dengan checksum + atribusi per file.

Cakupan yang diminta, konkretnya: satelit/wahana buatan manusia 182 objek
(Hubble, JWST, Cassini, Voyager, Juno, Kepler, Chandra, Rosetta, Parker Solar
Probe, ISS, Curiosity/Perseverance, dst.) plus 40 objek perangkat darat; komet
5 (67P, Wild 2, Hartley 2, Tempel 1, Halley); asteroid 37 objek bernama +
10.757 dari DAMIT; bulan 47; planet 8; bintang 3 (BP Tauri, DG Tau, U Scorpii)
plus 3 peta bintang seluruh langit (Hipparcos, Tycho, Yale Bright Star); objek
deep-sky 17; fitur permukaan 36.

**Dua bug lama ikut ketemu dan diperbaiki:**

- `build_master_index()` menghitung `data/_catalog/schema/*.json` sebagai objek,
  karena nama file skema memang sengaja sama dengan marker leaf
  (`planet.json`, `model_3d.json`, …). Selama ini lolos `astro verify` cuma
  karena kedua sisi hitungan sama-sama salah; begitu ada tipe baru yang
  skemanya belum ada saat index ditulis, mismatch-nya muncul.
  Efek keduanya: skema `model_3d` yang punya `required` membuat cek schema
  gagal karena file skemanya sendiri ikut divalidasi sebagai instance — skema
  lama lolos cuma karena tidak satu pun punya `required`. `_catalog/` sekarang
  dikecualikan di `build_master_index()` dan di ketiga tempat `astro verify`
  menyapu leaf.
- `astro verify` tidak punya cek apa pun untuk sumber yang checksum-nya
  disimpan di `manifest.json` (bukan sidecar `.sha256` per file, yang akan
  mengotori working tree hasil `git clone`). Sekarang ada cek manifest
  tersampel.

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
