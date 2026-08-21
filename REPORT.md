# REPORT — Astro Data Lake

Dibuat: 2026-08-20, ditambah bagian 8 (model 3D + tekstur) pada 2026-08-21.
Mencakup Fase 0–5 (scaffold, probe, pull, build, verify, dan penutupan gap) dan
Fase 8. Semua data ditarik dari sumber publik resmi, disimpan mentah apa adanya di
`data/raw/`, lalu dinormalisasi ke `data/` sesuai struktur di brief. Tidak ada data
ilmiah yang dikarang — field yang tidak ada di sumber ditulis `null` dan bisa
ditelusuri lewat `metadata.json` di tiap folder objek.

Angka di bagian 1–7 dari build terakhir 2026-08-20 (setelah Fase 5); bagian 8 dari
build 2026-08-21.

## 1. Jumlah objek per kategori

| Kategori | Jumlah | Catatan |
|---|---:|---|
| Planet tata surya (+ Matahari) | 9 | 8 planet + Sun, dari JPL Horizons OBJ_DATA |
| Bulan planet | 459 | dari JPL SSD (`jpl_sat_elem`): Saturnus 291, Jupiter 115, Uranus 29, Neptunus 16, Pluto 5, Mars 2, Bumi 1 |
| Pluto | 1 | folder `dwarf_planet` sendiri |
| Asteroid/komet/TNO (semua kelas SBDB) | 1.560.435 | 42.185 kelas NEO + 1.515.962 kelas lain + 2.288 HYP/PAR/HYA (baru di Fase 5) |
| — di antaranya, objek bernama (folder sendiri) | 26.529 | `solar_system/small_bodies/named/00001_ceres/`, dst. |
| — trojan Jupiter, kubu L4 / L5 | 10.403 / 5.975 | **baru**: pembagian dihitung dari bujur rata-rata |
| — TNO per sub-kelas dinamis | 7.285 (semua) | **baru**: classical 2.311, scattered 2.307, resonant 1.928, inner_belt 431, detached 308 (perkiraan) |
| — objek antarbintang | 3 | **baru**: 1I/'Oumuamua, 2I/Borisov, 3I/ATLAS |
| Hujan meteor (established IAU) | 113 | **baru**, dari IAU Meteor Data Center |
| Satelit buatan (SATCAT lengkap) | 70.352 | termasuk yang sudah decayed |
| Bintang bernama (HYG) | 465 | `stars/by_name/`; leaf `star` di master_index 466, karena Matahari (`solar_system/sun/`) juga pakai `star.json` |
| Bintang total di HYG | 119.626 | dasar `by_constellation`, `by_spectral_type`, `by_distance` |
| Bintang kategori khusus | 13.362 baris | **baru sebagian**: pulsar 2.536, magnetar 24, bintang neutron 86, lubang hitam 5, katai coklat 3.903, maharaksasa 538, hipergiant 104, variabel 5.992, katai putih 174 |
| Sistem biner/multiple (baris katalog) | 168.903 | WDS 157.917 + SB9 + MSC 12.484 |
| — sistem bernama (folder sendiri) | 293 | **baru**: hasil cross-match posisi WDS × HYG |
| **Exoplanet terkonfirmasi** | **6.336** | dari `pscomppars`, satu baris per planet |
| **Bintang induk exoplanet (folder `by_host_star/`)** | **4.749** | fitur utama yang diminta — lihat contoh TRAPPIST-1 (7 planet b–h) |
| — exoplanet per kelas turunan | 12 kategori | **baru**: gas_giant 1.870, super_earth 927, hot_jupiter 703, terrestrial 576, ultra_short_period 164, dst. |
| — exoplanet di zona layak huni | 184 konservatif | **baru**: 275 optimis, 18 konservatif **dan** berpotensi berbatu |
| Deep-sky (OpenNGC, incl. Messier) | 14.077 baris | 107 objek Messier dapat folder sendiri, sisanya per-kategori |

`data/_catalog/master_index.json` (leaf object dengan JSON per-objek): planet 6.344
(6.336 exoplanet + 8 planet tata surya), moon 459, dwarf_planet 1, star 466,
exoplanet_host_star 4.749, asteroid 26.529, deep_sky_object 107, multiple_system 293,
meteor_shower 113.

Catatan: angka-angka ini masing-masing satu lebih kecil dari build sebelum Fase 5, dan
itu koreksi, bukan kehilangan data. `master_index.json` dulu ikut menghitung file di
`_catalog/schema/` — nama file skema memang sengaja sama dengan file daun yang
divalidasinya (`moon.json`, `planet.json`, ...), jadi tiap tipe objek terhitung kelebihan
satu. Sekarang `_catalog/` dikecualikan dari pemindaian.

## 2. Total ukuran disk

| Folder | Ukuran |
|---|---:|
| `data/raw/` (mentah, apa adanya) | 664 MB |
| `data/exoplanets/` | 615 MB |
| `data/solar_system/` | 522 MB |
| `data/stars/` | 107 MB |
| `data/multiple_systems/` | 18 MB |
| `data/deep_sky/` | 11 MB |
| `data/_catalog/` | 6,3 MB |
| **Total `data/`** | **~1,9 GB** |

## 3. Sumber data + lisensi

41 dari 51 sumber terdaftar berhasil ditarik. Daftar lengkap dengan status pull ada di
`data/_catalog/sources.json`; atribusi gabungan di `data/ATTRIBUTION.md`, dan sejak
Fase 5 **tiap folder** di bawah `data/` menyalin baris atribusi sumbernya sendiri ke
README.md-nya (`astro verify` gagal kalau ada yang hilang — 33.062 folder tercek).

| Sumber | Lisensi/atribusi |
|---|---|
| NASA Exoplanet Archive TAP (pscomppars, ps, cumulative, toi, k2pandc, stellarhosts) | Public domain (NASA); atribusi diminta IPAC |
| JPL Horizons API (OBJ_DATA + ELEMENTS) | Public domain (NASA/JPL) |
| JPL Planetary Satellite Physical Parameters / Mean Elements / Discovery | Public domain (NASA/JPL) |
| JPL SBDB Query API (NEO, semua kelas lain, + HYP/PAR/HYA) | Public domain (NASA/JPL) |
| CNEOS Close Approach Data API, Sentry | Public domain (NASA/JPL) |
| CelesTrak GP data (11 grup) + SATCAT | CelesTrak — atribusi diminta |
| Minor Planet Center MPCORB, Comet Elements | Lihat kebijakan data MPC (perlu verifikasi ulang syaratnya) |
| HYG Database | CC BY-SA 4.0 |
| IAU Catalog of Star Names (IAU-CSN, via WGSN/Rochester) | CC BY (produk IAU) |
| **SIMBAD TAP** (tipe objek + tabel `ident`) | CDS — atribusi wajib |
| Washington Double Star Catalog, SB9, Multiple Star Catalog (via VizieR) | CDS — atribusi wajib per katalog |
| **ATNF Pulsar Catalogue** (VizieR B/psr) | CDS — atribusi wajib (Manchester et al. 2005) |
| **BlackCAT** (VizieR J/A+A/587/A61) | CDS — atribusi wajib (Corral-Santana et al. 2016) |
| **IAU Meteor Data Center** | IAU MDC — sitasi per header file |
| OpenNGC, Messier | CC BY-SA 4.0 |
| Kepler Eclipsing Binary Catalog | Perlu verifikasi syarat Villanova |
| exoplanet.eu catalog | Perlu verifikasi syarat exoplanet.eu |

(**tebal** = ditambahkan di Fase 5.)

## 4. Sumber yang tidak/belum ditarik, dan kenapa

| Sumber | Alasan |
|---|---|
| `spacetrack` | Butuh akun gratis; kredensial tidak tersedia di environment ini |
| `ucs_satellite_db` | Halaman lama tidak lagi menyediakan link download langsung — sekarang di-gate lewat form opt-in email |
| `open_exoplanet_catalogue` | Satu file XML per sistem (ribuan file kecil) di repo GitHub di luar scope akses repo sesi ini |
| `usgs_gazetteer` | Data-nya per-body GIS shapefile (~100+ file di S3), bukan tabel flat — butuh downloader khusus |
| `gaia_dr3_nss` (Tier 2) | Endpoint ESA TAP mengembalikan HTTP 503 saat probe |
| `gaia_dr3_tap` (Tier 3) | Sama; lagipula full Gaia DR3 (1,8 miliar baris) sengaja tidak ditarik penuh |
| `mpc_mpcorb`, `mpc_comet_els` (Tier 2) | Tidak dipakai builder mana pun — SBDB sudah memberi elemen orbit yang sama untuk seluruh 1,58 juta objek |
| `nssdc_planetary_factsheet` | Mati (lihat di bawah); diganti `jpl_horizons` |
| `vizier_tap` | Titik akses generik, bukan dataset tersendiri |

### Endpoint yang salah/mati dan sudah diperbaiki

- `hyg_database`: nama file yang benar `hygdata_v41.csv`, bukan `hyg_v42.csv`.
- `iau_star_names`: halaman `iau.org/public/themes/naming_stars/` 404 — diganti ke IAU-CSN resmi WGSN.
- `kepler_eb_catalog`: butuh `https://`, bukan `http://`.
- `msc_catalog`: nama tabel VizieR yang benar `J/ApJS/235/6/catalog`.
- `nssdc_planetary_factsheet`: HTTP 200 tapi seluruh path 307-redirect ke halaman generik
  `nasa.gov/nssdc/`. Fase 1 salah menandainya "hidup" karena hanya cek status code.
- `blackcat_bh_transients` (Fase 5): tabelnya `J/A+A/587/A61/tablea1` — tidak ada tabel
  bernama `blackcat` seperti yang ditebak pertama kali.
- `iau_meteor_data_center` (Fase 5): nama file membawa tahun edisi
  (`streamestablisheddata2026.txt`) — perlu dicek ulang tiap edisi baru.

## 5. Yang ditambahkan di Fase 5 (dulu tercatat "belum dibangun")

Delapan dari sembilan item yang REPORT versi Fase 4 daftarkan sebagai gap sekarang
terisi. Semua yang bersifat hitungan menyimpan `derived_from` dan
`classification_method` di `metadata.json`-nya; aturannya sendiri terkumpul di
`astro_datalake/build/classify.py` dengan tes yang menguji tiap aturan terhadap objek
yang klasifikasinya tidak diperdebatkan.

- **`exoplanets/by_type/`** — 12 kategori turunan dari radius/massa/periode. Sengaja
  tumpang tindih: hot Jupiter masuk `gas_giant` **dan** `hot_jupiter`. 4 planet tanpa
  radius maupun massa tidak diberi label ukuran sama sekali.
- **`exoplanets/habitable_zone/`** — batas fluks Kopparapu et al. (2013, erratum 2014)
  dihitung ulang per bintang dari `st_teff`, dibanding `pl_insol` (fallback: L/a²).
  184 konservatif, 275 optimis, 18 konservatif+berpotensi berbatu. Rumusnya hanya valid
  2600–7200 K, jadi 376 planet masuk `_unassessable/` lengkap dengan alasannya —
  termasuk seluruh sistem TRAPPIST-1 (Teff 2566 K, tepat di bawah lantai validitas).
  Ekstrapolasi ditolak; objeknya tetap didaftar supaya tidak terlihat hilang.
- **`stars/special/`** — tujuh subkategori yang dulu kosong sekarang terisi dari katalog
  yang menyimpan tipe objek sebagai data: SIMBAD `otypes` (katai coklat, bintang neutron,
  lubang hitam, maharaksasa), MK Ia+ untuk hipergiant, ATNF untuk pulsar dan magnetar
  (flag `Type`=AXP milik katalognya sendiri), BlackCAT untuk transien sinar-X lubang
  hitam. Potongan kelas luminositas dari HYG ditulis sebagai file terpisah
  (`hyg_luminosity_class.parquet`), tidak dilebur ke sensus katalognya.
- **`multiple_systems/binary/<nama>/`** — 293 sistem bernama, dari cross-match posisi
  WDS × HYG dengan toleransi 30 arcsec. Tiap `system.json` menyimpan separation yang
  diterima, jadi identifikasi yang marginal kelihatan. Alpha Centauri (A, B, dan Proxima
  sebagai komponen C) cocok ke WDS 14396-6050; Sirius, Albireo, Mizar, Polaris, Castor
  semuanya cocok di bawah 1 arcsec. Dump katalog mentah pindah ke `_catalogs/`.
- **`small_bodies/trojans/{l4,l5}`** — 10.403 vs 5.975 (rasio 1,74, sesuai asimetri L4/L5
  yang memang teramati). Ini geometri, bukan perkiraan: L = Ω + ω + M dibanding bujur
  rata-rata Jupiter dari JPL Horizons pada epoch yang sama. Diuji terhadap objek acuan —
  Achilles, Hektor, Agamemnon, Odysseus, Diomedes keluar L4; Patroclus dan Priamus L5.
- **`small_bodies/trans_neptunian/*`** — classical (cold 1.196 / hot 1.115), resonant
  (plutino 3:2 719, 7:4 406, 5:3 275, 2:1 235, 5:2 162, 4:3 84, 3:1 47), scattered 2.307,
  detached 308, inner_belt 431. **Perkiraan**, dan ditandai begitu di tiap `metadata.json`:
  keanggotaan resonansi yang sebenarnya butuh integrasi numerik argumen resonansi,
  sedangkan ini potongan (a, q, e, i) di sekitar lokasi resonansi nominal.
- **`small_bodies/comets/interstellar/`** — 1I/'Oumuamua, 2I/Borisov, 3I/ATLAS.
- **`small_bodies/meteor_showers/`** — 113 hujan established IAU, satu folder per hujan
  dengan seluruh solusi orbitnya di `solutions.csv`.
- **`_catalog/crosswalk.parquet`** — dari 6 kolom jadi 20. SIMBAD main_id/otype/sp_type
  terisi 117.951 baris, Gaia DR3 113.993, TIC 115.340, 2MASS 116.420, nama host exoplanet
  795. Semua di-join lewat nomor HIP dari tabel `ident` SIMBAD, bukan lewat posisi.
- **Atribusi otomatis** — `astro build` menstempel blok atribusi ke README tiap folder
  dari `source` di metadata.json-nya, plus `data/ATTRIBUTION.md` gabungan;
  `astro verify` menggagalkan build yang folder datanya kehilangan blok itu.

### Tiga hal yang ditemukan saat mengerjakannya

1. **SBDB tidak pernah memakai designation IAU `1I/2I/3I`.** 'Oumuamua tersimpan sebagai
   `'Oumuamua (A/2017 U1)` di kelas **HYA** — kelas yang bahkan tidak ikut ditarik di Fase 2 —
   Borisov sebagai `C/2019 Q4 (Borisov)`, ATLAS sebagai `C/2025 N1 (ATLAS)`. Pendekatan
   pertama (cari nama berawalan angka+I) menghasilkan nol objek. Sekarang jembatannya
   tabel tiga baris yang eksplisit di `build/small_bodies.py`.
2. **SIMBAD TAP memotong hasil di 50.000 baris tanpa bilang apa-apa.** Lima file crosswalk
   pertama "berhasil" dengan tepat 50.000 baris; angka bulat itu satu-satunya petunjuk.
   `tap_queries()` sekarang mengirim MAXREC eksplisit dan **error** kalau hasilnya persis
   sama dengan MAXREC, daripada menyimpan setengah katalog yang kelihatan valid.
3. **Ambang resonansi TNO tidak bisa datar.** Toleransi seragam 0,5 AU menaruh Albion —
   cubewano purba yang mendefinisikan kelas classical — ke dalam resonansi 7:4. Lebar
   jendela sekarang per resonansi dan menyempit untuk resonansi orde tinggi.

## 6. Yang masih belum lengkap

- **`asteroid_belt/_by_family/`** — satu-satunya item Fase 4 yang belum tertutup. Butuh
  proper elements dari katalog famili (AstDyS `all.famrec`, 104 MB, atau dataset Nesvorný
  di PDS). File AstDyS-nya bisa diakses dari sini, tapi format kolomnya tidak
  terdokumentasi di servernya; menebak kolom mana yang ID famili sama saja dengan
  mengarang keanggotaan famili, jadi sengaja tidak dikerjakan.
- **Cakupan crosswalk untuk bintang tanpa HIP** — kuncinya nomor HIP, jadi mayoritas host
  exoplanet TESS/Kepler (yang tidak punya HIP) belum punya baris. Menambah kunci kedua
  butuh cross-match posisi tersendiri. KIC sengaja tidak dimasukkan: irisannya dengan HIP
  cuma 347 objek, kolomnya akan hampir seluruhnya null.
- **Versi ATNF** — salinan VizieR beku di 2.536 pulsar sementara katalog aslinya sudah
  lewat 3.500. Sudah dikonfirmasi lewat `select count(*)` bahwa itu memang seluruh isi
  tabelnya (bukan query terpotong), dan dicatat di registry + README foldernya. Katalog
  yang hidup cuma punya antarmuka form HTML, tidak ada endpoint bulk yang stabil.
- **Sub-kelas TNO tetap perkiraan** sampai ada integrasi numerik atau katalog klasifikasi
  dinamis (mis. DES/Gladman) yang ditarik langsung.
- **`usgs_gazetteer`, `ucs_satellite_db`, `spacetrack`, `open_exoplanet_catalogue`,
  Gaia DR3 penuh** — alasannya tidak berubah dari §4.

## 7. Verifikasi (`astro verify`)

Semua cek lulus pada build terakhir:

| Cek | Hasil |
|---|---|
| Checksum raw/ | 78 file cocok, 0 bermasalah |
| `master_index.json` vs filesystem | cocok |
| Folder kosong | tidak ada |
| JSON vs JSON Schema (sampel) | 1.429 valid, 0 gagal |
| Atribusi di README tiap folder | 33.062 folder OK |
| Data turunan menyebut metodenya | semua |

Dua cek terakhir baru di Fase 5. Yang kedua adalah pagar untuk aturan dasar proyek ini:
folder yang isinya dihitung harus bilang bagaimana menghitungnya, kalau tidak build-nya
gagal.

Tes unit: 95 tes lulus (`uv run pytest`), termasuk pengujian tiap aturan klasifikasi
terhadap objek acuan dan pengujian parser format tetap (IAU MDC, Horizons ELEMENTS).

## 8. Saran langkah berikutnya

1. Tulis parser famili asteroid setelah format `all.famrec` diklarifikasi (email ke
   AstDyS, atau pakai dataset Nesvorný di PDS yang berlabel kolom) — itu menutup gap
   terakhir dari daftar Fase 4.
2. Tambahkan kunci kedua (posisi atau TIC) ke crosswalk supaya host exoplanet tanpa HIP
   ikut terjaring.
3. Kalau butuh Open Exoplanet Catalogue: tambahkan repo-nya via `add_repo` lalu
   `git clone` langsung, daripada fetch per-file lewat HTTP.
4. Minta akses Space-Track.org / file UCS Satellite Database secara manual kalau datanya
   benar-benar dibutuhkan (keduanya butuh registrasi manusia).
5. Cek ulang endpoint ESA Gaia TAP; kalau sudah hidup, `gaia_dr3_nss` (Tier 2) memberi
   orbit biner yang bisa dipakai memperkaya `multiple_systems/`.

## 9. Model 3D & tekstur (Fase 8, 2026-08-21)

Permintaan: tarik semua model 3D yang tersedia — satelit buatan manusia (Hubble, JWST,
dst.), komet, bintang, dll — berikut tekstur kalau ada.

### 9.1 Yang berhasil ditarik

| Sumber | Isi | Ukuran raw |
|---|---|---:|
| `nasa_3d_resources` (repo GitHub NASA, commit `11ebb4e`) | 1199 file: 227 model, 108 model cetak 3D, 50 set tekstur | 4,7 GB |
| `pds_sbn_shape_models` | 241 file untuk 64 objek: 5 komet, 36 asteroid, 23 satelit alami | 5,4 GB |
| `damit_shape_models` | 1 arsip export lengkap: 10.757 asteroid, 16.105 model bentuk | 1,4 GB |
| `nasa_science_3d` | 216 item katalog, 260 file (STL cetak + PNG + deskripsi resmi) | 829 MB |
| `nasa_svs_texture_kits` | 19 file CGI Moon Kit (peta warna LROC + displacement LOLA) | 1,7 GB |
| `nasa_blue_marble_textures` | 25 file tekstur Bumi (Blue Marble, land/ocean/cloud/night) | 55 MB |
| **Total `data/raw/`** | | **~14 GB** |

### 9.2 Hasil build: `data/models_3d/`

382 objek, 2192 file, 15,9 GB "logis" (aset di-hardlink dari `data/raw/`, jadi tidak
menggandakan disk), plus `asteroids/_damit/` berisi 80.511 file.

| Kategori | Objek | File | Contoh |
|---|---:|---:|---|
| `spacecraft` | 182 | 1316 | Hubble (A+B+STL cetak), JWST, Cassini, Voyager, Juno, Kepler, Chandra, Rosetta, Parker Solar Probe, ISS, Curiosity, Perseverance |
| `moons` | 47 | 192 | shape model Phobos/Deimos/Amalthea/Phoebe + tekstur Io, Europa, Titan, Triton, Charon |
| `ground_and_equipment` | 40 | 198 | antena DSN 34/70 m, spacesuit, tools ISS, Vehicle Assembly Building |
| `asteroids` | 37 | 157 | Bennu, Ryugu, Itokawa, Eros, Vesta, Ceres, Apophis, Arrokoth, Kleopatra (+ `_damit/`) |
| `surface_features` | 36 | 87 | situs pendaratan Apollo 11–17, Valles Marineris, kawah Tycho/Copernicus, Gale Crater |
| `deep_sky` | 17 | 100 | Pillars of Creation, Crab Nebula, Cassiopeia A, SN 1006/1987A, Whirlpool Galaxy, NGC 602/1566/3344 |
| `planets` | 8 | 52 | tekstur Bumi (+Blue Marble), Mars, Jupiter, Saturn, Neptune, Venus, Pluto |
| `comets` | 5 | 16 | 67P/Churyumov–Gerasimenko, 81P/Wild 2, 103P/Hartley 2, 9P/Tempel 1, 1P/Halley |
| `earth_science` | 4 | 70 | Hurricane Katrina/Sandy/Julio, Eclipse 2017 |
| `stars` | 3 | 7 | BP Tauri, DG Tau, U Scorpii |
| `sky_maps` | 3 | 9 | peta bintang seluruh langit: Hipparcos, Tycho, Yale Bright Star |

333 objek punya mesh, 368 punya tekstur. Format: 516 GLB, 484 STL, 421 PNG, 204 JPG,
127 TIF, 72 LWO, 57 OBJ, 56 TAB (PDS), 44 USDZ, 20 BDS, 14 BLEND, 12 TGA, 5 WRL, 4 3DS.

452 file di antaranya keluar dari 29 arsip `.7z` bawaan NASA yang dibongkar saat build
(scene LightWave/Maya/3ds Max + tekstur JPG/TIF/TGA-nya) — kalau dibiarkan terkompresi
tekstur-tekstur itu tidak terlihat sama sekali oleh apa pun yang membaca pohon ini.

### 9.3 Soal "bintang": apa yang sebenarnya ada

Tidak ada "model 3D bintang" dalam arti mesh bentuk permukaan — bintang itu bola gas,
tidak punya bentuk untuk dimodelkan seperti komet atau asteroid. Yang benar-benar
tersedia dan ditarik:

- **3 model dari NASA untuk sistem bintang muda dan nova** (BP Tauri — GLB, DG Tau
  dan U Scorpii — STL siap cetak). Yang dimodelkan struktur di sekitar bintangnya
  (piringan, jet, cangkang nova) hasil visualisasi ilmiah, bukan bentuk permukaan
  bintangnya.
- **3 peta bintang seluruh langit** (Hipparcos, Tycho, Yale Bright Star) sebagai
  tekstur bola langit — ini yang biasanya dipakai untuk merender langit berbintang.
- Untuk Matahari: tidak ada mesh maupun tekstur permukaan Matahari di sumber-sumber
  yang bisa diakses di sini (NASA 3D Resources tidak punya; Solar System Scope yang
  punya tekstur Matahari CC BY 4.0 diblokir captcha — lihat 9.4).

Data bintang yang sebenarnya (posisi, magnitudo, tipe spektral) tetap ada di
`data/stars/` dari HYG, bukan di sini.

### 9.4 Yang tidak bisa ditarik, dan kenapa

| Sumber | Alasan (diverifikasi 2026-08-21) |
|---|---|
| `solarsystemscope_textures` | Seluruh domain di balik captcha bot-gate: `/textures/` dan URL unduhan langsung sama-sama membalas HTTP 202 berisi redirect ke `/.well-known/sgcaptcha/`, dengan maupun tanpa User-Agent browser. Menembus captcha bukan cara yang benar untuk mengambil data. |
| `usgs_planetary_mosaics` | `/search/results` memang JSON (1643 entri), tapi tiap entri cuma memberi slug + halaman yang di-render JS; file mosaiknya ada di resource CKAN per-dataset dan satu mosaik global bisa puluhan–ratusan GB. Butuh downloader khusus + pilihan resolusi; di luar kuota disk sesi ini. |
| Shape model Ryugu (Hayabusa2, `darts.isas.jaxa.jp`) | Host diblokir network policy environment ini (proxy menolak CONNECT dengan 502). Bukan masalah endpoint. |
| 22 file di `science.nasa.gov` | Halaman NASA sendiri menaut file yang 404 di CDN-nya (mis. `Ben Franklin.lwo`, `Shuttle Carrier - *.3ds`). Sebagian besar tetap ada versinya di repo GitHub. |
| 6 file + 3 preview di `sbn.psi.edu` | Link mati di katalog upstream (404), plus satu typo di sumbernya (`'Hudson.basepath' + '…'` — nama variabel ikut masuk ke dalam kutip, jadi URL-nya rusak juga di situs aslinya). |
| 4 file tekstur SVS | Di atas batas 600 MB per file (`MAX_TEXTURE_BYTES`): peta warna Bulan versi EXR 943 MB dan TIF 2,4 GB. Versi 4k/8k/16k-nya tetap ditarik. |
| 6 halaman `science.nasa.gov` | Halaman model tanpa file unduhan sama sekali (hanya viewer). |

Semua di atas tercatat di `manifest.json` masing-masing sumber di `data/raw/`, bukan
dihilangkan diam-diam.

### 9.5 Catatan kejujuran soal kategori

Kategori objek (`spacecraft/`, `comets/`, `asteroids/`, …) punya dua asal-usul berbeda,
dan itu ditulis eksplisit di field `classified_by` tiap `model_3d.json`:

- `source:pds_sbn_type` — tipe comet/asteroid/satellite datang dari katalog PDS SBN.
- `rule:<kategori>` / `fallback:spacecraft` — katalog NASA hanya punya nama folder,
  jadi kategorinya **ditebak** dengan aturan regex di `astro_datalake/build/models_3d.py`.

Tebakan itu sudah dicek satu per satu terhadap 385 nama folder NASA dan kasus-kasus
jebakannya ditangani (mis. "Vesta - Rheasilvia" itu kawah di Vesta → `surface_features`,
bukan model asteroid Vesta; "Double Asteroid Redirection Test (DART)" itu wahana, bukan
asteroid; "Laser Interferometer Space Antenna" itu wahana, bukan antena darat), tapi
tetap tebakan, bukan klasifikasi resmi NASA.

### 9.6 Verifikasi

Tiap folder objek juga menulis `metadata.json` dan blok atribusi standar di README-nya
(konvensi yang sama dengan kategori lain, dari Fase 6), sehingga cek atribusi
`astro verify` ikut mencakup `models_3d/`: 403 folder terperiksa, naik dari 10.
Ini wajib khusus untuk DAMIT yang berlisensi CC BY.

`astro verify` lulus semua cek. Satu lubang cek ditutup di sini: sumber yang checksum-nya
disimpan di `manifest.json` — bukan sidecar `.sha256` per file, yang akan mengotori
working tree hasil `git clone` — sebelumnya tidak diperiksa sama sekali; sekarang ada cek
manifest tersampel. (Bug `master_index.json` yang menghitung file skema di
`_catalog/schema/` sebagai objek juga sempat muncul di cabang ini, tapi Fase 5 sudah
memperbaikinya lebih dulu lewat `object_folders()`; versi duplikat di cabang ini dibuang
saat merge.) Hasil akhir: 539 checksum sidecar cocok, 6 manifest × sampel 40 file cocok, `master_index.json`
sinkron dengan filesystem, tidak ada folder kosong, 210/210 sampel JSON valid terhadap
skema.
