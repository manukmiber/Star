# REPORT — Astro Data Lake

Dibuat: 2026-08-20. Mencakup Fase 0–5 (scaffold, probe, pull, build, verify, dan
penutupan gap). Semua data ditarik dari sumber publik resmi, disimpan mentah apa adanya
di `data/raw/`, lalu dinormalisasi ke `data/` sesuai struktur di brief. Tidak ada data
ilmiah yang dikarang — field yang tidak ada di sumber ditulis `null` dan bisa ditelusuri
lewat `metadata.json` di tiap folder objek.

Angka di bawah dari build terakhir (2026-08-20, setelah Fase 5).

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
