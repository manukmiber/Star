# REPORT — Astro Data Lake

Dibuat: 2026-08-20. Mencakup Fase 0–4 (scaffold, probe, pull Tier 1+2, build, verify).
Semua data ditarik dari sumber publik resmi, disimpan mentah apa adanya di `data/raw/`,
lalu dinormalisasi ke `data/` sesuai struktur di brief. Tidak ada data ilmiah yang
dikarang — field yang tidak ada di sumber ditulis `null` dan bisa ditelusuri lewat
`metadata.json` di tiap folder objek.

## 1. Jumlah objek per kategori

| Kategori | Jumlah | Catatan |
|---|---:|---|
| Planet tata surya (+ Matahari) | 9 | 8 planet + Sun, dari JPL Horizons OBJ_DATA |
| Bulan planet | 454 | dari JPL SSD (`jpl_sat_elem`) |
| Pluto + bulannya | 1 + 5 | Charon, Nix, Hydra, Kerberos, Styx |
| Asteroid/komet/TNO (semua kelas SBDB) | 1.558.235 | MBA 1.378.000, OMB 50.111, IMB 32.859, MCA 29.923, APO 23.989, TJN 16.378, AMO 14.721, TNO 7.285, ATE 3.435, CEN 1.045, HTC 111, unclassified/AST 153, ETc 79, JFC 17, IEO 38 |
| — di antaranya, objek bernama (folder sendiri) | 26.530 | `solar_system/small_bodies/named/00001_ceres/`, dst. |
| Satelit buatan (SATCAT lengkap) | 70.332 | termasuk 35.480 yang sudah decayed |
| Bintang bernama (HYG) | 465–467 | `stars/by_name/` — termasuk Sirius, Betelgeuse, Vega, Proxima Centauri |
| Bintang total di HYG (semua, tanpa/dengan nama) | 119.626 | dasar `by_constellation`, `by_spectral_type`, `by_distance` |
| Sistem biner/multiple (baris katalog) | 168.903 | WDS 157.917 + SB9 (main/orbits/alias) + MSC 12.484, belum di-resolve ke nama umum |
| **Exoplanet terkonfirmasi** | **6.336** | dari `pscomppars`, satu baris per planet |
| **Bintang induk exoplanet (folder `by_host_star/`)** | **4.749** | fitur utama yang diminta — lihat contoh TRAPPIST-1 (7 planet b–h) |
| Deep-sky (OpenNGC, incl. Messier) | 14.077 | 110 objek Messier dapat folder sendiri, sisanya per-kategori (NGC/IC/nebula/galaxy) |

Total baris/objek yang tercatat di `data/_catalog/master_index.json` (leaf object dengan
JSON per-objek, tidak termasuk baris tabel kategori-level): planet 6.345, moon 460,
dwarf_planet 1, star 467, exoplanet_host_star 4.749, asteroid 26.530, deep_sky_object 108.

## 2. Total ukuran disk

| Folder | Ukuran |
|---|---:|
| `data/raw/` (mentah, apa adanya) | 730 MB |
| `data/exoplanets/` | 493 MB |
| `data/solar_system/` | 515 MB |
| `data/stars/` | 104 MB |
| `data/multiple_systems/` | 12 MB |
| `data/deep_sky/` | 11 MB |
| `data/_catalog/` | 2.7 MB |
| **Total `data/`** | **~1.9 GB** |

Jauh di bawah kuota disk sesi ini (30 GB tersedia saat pull dijalankan).

## 3. Sumber data yang berhasil ditarik (38 dari 46 terdaftar) + lisensi

| Sumber | Lisensi/atribusi |
|---|---|
| NASA Exoplanet Archive TAP (pscomppars, ps, cumulative, toi, k2pandc, stellarhosts) | Public domain (NASA); atribusi diminta IPAC |
| JPL Horizons API | Public domain (NASA/JPL) |
| JPL Planetary Satellite Physical Parameters / Mean Elements / Discovery | Public domain (NASA/JPL) |
| JPL SBDB Query API (NEO + semua kelas lain) | Public domain (NASA/JPL) |
| CNEOS Close Approach Data API, Sentry | Public domain (NASA/JPL) |
| CelesTrak GP data (11 grup) + SATCAT | CelesTrak — atribusi diminta |
| Minor Planet Center MPCORB, Comet Elements | Lihat kebijakan data MPC (perlu verifikasi ulang syaratnya) |
| HYG Database | CC BY-SA 4.0 |
| IAU Catalog of Star Names (IAU-CSN, via WGSN/Rochester) | CC BY (produk IAU) |
| Washington Double Star Catalog, SB9, Multiple Star Catalog (via VizieR) | CDS — atribusi wajib per katalog |
| OpenNGC, Messier | CC BY-SA 4.0 |
| Kepler Eclipsing Binary Catalog | Perlu verifikasi syarat Villanova |
| exoplanet.eu catalog | Perlu verifikasi syarat exoplanet.eu |

**Penting soal atribusi**: data dari CDS/VizieR (WDS, SB9, MSC) dan CelesTrak/MPC secara
eksplisit meminta atribusi ke sumber aslinya di setiap penggunaan turunan — ini belum
diotomatisasi di README per-folder, baru dicatat di `metadata.json`/`sources.json`.

## 4. Sumber yang tidak/belum ditarik, dan kenapa

> **Catatan 2026-08-21 (Fase 8):** tabel di bawah ini adalah keadaan waktu
> laporan ini ditulis (Fase 0–4). Sejak itu tujuh dari sumber-sumber ini sudah
> bisa ditarik — `usgs_gazetteer`, `open_exoplanet_catalogue`,
> `ucs_satellite_db`, `simbad_tap`, `gaia_dr3_nss`, `gaia_dr3_tap`, dan
> `vizier_tap` — dan `nssdc_planetary_factsheet` diganti sumber baru
> `le_systeme_solaire`. Sekarang 45 dari 47 sumber bisa ditarik; yang tersisa
> hanya `nssdc_planetary_factsheet` (endpoint-nya memang sudah mati) dan
> `spacetrack` (butuh akun). Alasan per sumber ada di CHANGELOG.md.

| Sumber | Alasan |
|---|---|
| `spacetrack` | Butuh akun gratis; kredensial tidak tersedia di environment ini |
| `ucs_satellite_db` | Halaman lama sudah tidak menyediakan link download langsung — sekarang di-gate lewat form opt-in email (`forms.ucs.org/get-satellite-database-updates`) |
| `open_exoplanet_catalogue` | Satu file XML per sistem (ribuan file kecil) di repo GitHub yang di luar scope akses repo sesi ini; `api.github.com`/`codeload.github.com` diblokir untuk repo itu |
| `simbad_tap` | Sengaja tidak di-bulk-dump (>15 juta baris, scope tak terbatas) — dipakai ad-hoc untuk crossmatch, belum dikerjakan |
| `usgs_gazetteer` | Data-nya per-body GIS shapefile (~100+ file di S3), bukan tabel flat — butuh downloader khusus, belum ditulis |
| `gaia_dr3_nss` (Tier 2) | Endpoint ESA TAP mengembalikan HTTP 503 saat probe (kemungkinan maintenance/beban, dikonfirmasi bukan salah URL — bahkan halaman utama arsip Gaia timeout saat dicek ulang) |
| `gaia_dr3_tap` (Tier 3) | Sama seperti di atas; lagipula full Gaia DR3 (1.8 miliar baris, TB-skala) sengaja tidak ditarik penuh — di luar kuota disk sesi ini |

### Endpoint yang tadinya salah/mati, sudah diperbaiki

- `hyg_database`: nama file yang benar adalah `hygdata_v41.csv`, bukan `hyg_v42.csv` yang ditebak awal.
- `iau_star_names`: halaman `iau.org/public/themes/naming_stars/` 404 — diganti ke sumber IAU-CSN resmi WGSN di `pas.rochester.edu`.
- `kepler_eb_catalog`: butuh `https://`, bukan `http://` (server menolak plain HTTP dengan 400).
- `msc_catalog`: nama tabel VizieR yang benar `J/ApJS/235/6/catalog`, bukan `.../table1`.
- **`nssdc_planetary_factsheet`** — ditemukan saat Fase 3 (bukan Fase 1): endpoint mengembalikan HTTP 200 tapi seluruh path `/planetary/factsheet/*` ternyata 307-redirect ke halaman generik `nasa.gov/nssdc/`, bukan data fact sheet. Fase 1 salah menandainya "hidup" karena hanya cek status code, bukan konten. Diganti pakai `jpl_horizons` OBJ_DATA sebagai sumber parameter fisik planet.

## 5. Yang belum lengkap / butuh kerja lanjutan

- **Crosswalk lintas katalog** (`data/_catalog/crosswalk.parquet`) baru berisi ID dari HYG
  sendiri (hip/hd/hr/gliese/nama umum). Gaia DR3 source_id, TIC, KIC, dan SIMBAD main_id
  BELUM di-crossmatch — butuh query SIMBAD/Gaia per-objek yang di-defer.
- **`stars/special/`**: 5 dari 9 subkategori (neutron_stars, pulsars, magnetars,
  black_holes, brown_dwarfs, supergiants, hypergiants — 7 sebenarnya) belum dibangun;
  HYG tidak punya kolom object-type yang cukup andal, butuh katalog khusus (ATNF pulsar,
  Villanova WD, dst.) atau crossmatch SIMBAD.
- **`exoplanets/by_type/`** (hot_jupiter, super_earth, dst.) dan **`habitable_zone/`**
  belum dibangun — butuh klasifikasi turunan (ambang radius/massa/insolasi) yang belum
  dikerjakan di pass ini.
- **`multiple_systems/binary/<nama_sistem>/`** (mis. `alpha_centauri/`) belum dibangun —
  WDS/SB9/MSC tidak menyimpan nama umum bintang langsung, butuh crossmatch nama.
- **`small_bodies/asteroid_belt/_by_family/`**, split L4/L5 Jupiter trojan, dan subclass
  dinamis TNO (classical/plutino/resonant/scattered/detached) butuh data proper-elements
  dari katalog khusus (mis. AstDyS) yang tidak ditarik.
- **`small_bodies/meteor_showers/`** dan **`comets/interstellar/`**: tidak ada sumber
  yang ditarik sama sekali untuk ini.
- **`usgs_gazetteer`** dan **`ucs_satellite_db`** (lihat tabel di atas).
- **Atribusi otomatis**: README per-folder belum menyalin baris atribusi wajib dari
  CDS/VizieR/CelesTrak/MPC secara otomatis — saat ini hanya ada di `metadata.json`.
- **Tier 3 (Gaia DR3 penuh)**: sengaja tidak dijalankan — di luar kuota disk yang wajar
  untuk sesi ini (1.8 miliar baris). Kalau tetap diminta, defaultnya subset
  `parallax > 10 mas OR phot_g_mean_mag < 12` per brief, tapi endpoint ESA TAP sedang
  503 saat percobaan terakhir (2026-08-20) — perlu dicek ulang lebih dulu.

## 6. Verifikasi (`astro verify`)

Semua cek lulus setelah dua bug ditemukan-dan-diperbaiki di Fase 4:
checksum raw 100% cocok, `master_index.json` sinkron dengan filesystem, tidak ada folder
kosong, 1117/1117 sampel JSON valid terhadap JSON Schema di `data/_catalog/schema/`.

## 7. Saran langkah berikutnya

1. Bangun crossmatch SIMBAD/Gaia untuk melengkapi `crosswalk.parquet` dan
   `stars/special/` (pulsar, WD, dst.).
2. Tulis downloader `usgs_gazetteer` khusus (parsing shapefile per-body dari S3).
3. Tambahkan klasifikasi turunan untuk `by_type` dan `habitable_zone` exoplanet.
4. Kalau butuh Open Exoplanet Catalogue: tambahkan repo-nya via `add_repo` lalu
   `git clone` langsung, daripada fetch per-file lewat HTTP.
5. Minta akses Space-Track.org / file UCS Satellite Database secara manual kalau
   datanya benar-benar dibutuhkan (keduanya butuh registrasi manusia).
