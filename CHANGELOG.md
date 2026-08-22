# Changelog

## 2026-08-21 — Fase 9: Verifikasi link, Space-Track sesuai dokumentasi, TUI, Termux

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

Dua bug lagi ketahuan setelah merge, saat checker dijalankan ke endpoint asli:

- Target POST dicek pakai GET. USGS Gazetteer itu form POST-only, jadi
  jawabannya 500 dan dilaporkan sebagai link rusak — salah kita, bukan
  endpoint-nya. Sekarang method asli target yang dipakai.
- Permalink yang redirect ke file aslinya (`ucs.org/media/11492` →
  `.xlsx`) ikut kena aturan "redirect ganti path". Sekarang path yang
  berubah hanya jadi masalah kalau cek isi juga gagal; kasus landing-page
  yang jadi alasan aturan itu sudah ditangkap status RETIRED di registry.

Selain itu `gaia_dr3_tap` punya 182 target yang isinya satu query ADQL
dipotong per `random_index` — 66% dari seluruh target. Sekarang potongan
seragam seperti itu dicek sebagai sampel merata (4 dari 182) dan laporannya
menyebutkan itu; sumber yang target-nya memang beda-beda (10 benda
`jpl_horizons`, 11 kelas `sbdb_query_full`) tetap dicek semua. `--full`
untuk mengecek semuanya.

Hasil run penuh tanpa sampling 2026-08-22 (52 sumber / **276 target, semuanya
dicek**): **276/276 link berfungsi — 50 siap didownload**, 1 pensiun
(`nssdc_planetary_factsheet`), 1 butuh kredensial (Space-Track).

Run itu sekaligus jadi bukti dua hal. Pertama, semua 182 potongan Gaia lolos,
jadi sampel 4-slice memang tidak menyembunyikan potongan rusak. Kedua, tiga
sumber CDS/VizieR (`wds`, `sb9`, `msc`) yang di run sebelumnya ditandai
"gangguan sisi server" ternyata lolos apa adanya saat dicek ulang — persis
seperti yang diklaim klasifikasi itu. Angkanya bergerak antar-run karena CDS
yang hilang-timbul, bukan karena link-nya.

### Digabung dengan registry link dari Fase 8

Cabang ini awalnya menambah lapisan deklarasi URL sendiri di
`downloaders.py`. Fase 8 di `main` sudah menyelesaikan masalah yang sama
dengan lebih rapi — `sources/links.py` sebagai data murni yang dikonsumsi
downloader, `astro manifest`, dan frontend Cloudflare sekaligus. Saat merge,
lapisan duplikat itu **dibuang**; `astro links` sekarang membaca `LINKS`,
jadi tetap satu sumber kebenaran untuk semua konsumen.

Fetcher TAP async (UWS) dan mirror `oec_gzip` yang sempat ditambah di sini
ikut dibuang: `links.py` sudah menangani Gaia lewat potongan sync ber-MAXREC
dengan deteksi pemotongan, yang lebih teruji daripada versi async saya.

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
## 2026-08-21 — Fase 8: lengkapi semua link download + frontend Cloudflare

### Link registry (`astro_datalake/sources/links.py`)

Semua URL download sekarang jadi **data**, bukan kode: satu `DownloadTarget`
per file (URL, method, params, form body, header, timeout, perkiraan ukuran).
52 sumber, 130 target, dan satu definisi itu dipakai bareng oleh downloader,
generator manifest, situs statis, dan Worker — jadi link tidak bisa beda-beda
antar tempat. (Lima sumber Fase 5 — ATNF pulsar, BlackCAT, IAU MDC, Horizons
elements, SBDB hiperbolik — ikut dipindah ke registry ini waktu merge dengan
main.)

`downloaders.py` ditulis ulang di atas registry itu. Yang tadinya
**38 dari 46 sumber** bisa ditarik, sekarang **50 dari 52**.

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

### Hasil TAP yang dipotong diam-diam sekarang ditolak

Ditemukan waktu merge dengan main, dan ini bug beneran di kerjaan sebelumnya:
server TAP memotong hasil di MAXREC default mereka sendiri lalu mengembalikan
CSV yang bentuknya sempurna, **tanpa peringatan apa pun**. Query SIMBAD
`V < 10` yang benar-benar cocok dengan **362.857 baris** balik cuma
**50.000 baris** — dan lolos verifikasi link karena responsnya HTTP 200 dengan
konten yang kelihatan valid.

Kasus kedua ditemukan di Gaia dan bentuknya beda: potongan `random_index`
selebar 50 juta cocok dengan 99.309 baris tapi endpoint sync-nya cuma
mengembalikan **90.113**, berulang kali, tanpa peringatan — header VOTable
tetap `QUERY_STATUS="OK"` karena INFO itu ditulis sebelum baris mengalir, dan
`MAXREC` eksplisit tidak mengubah angkanya. Jadi ini pemotongan pada hasil
besar, bukan batas baris. Di lebar 5 juta dan 10 juta, jumlah baris yang
kembali **persis sama** dengan jumlah di katalog. Lebar potongan diturunkan
dari 50 juta ke 10 juta (37 → 182 potongan, ~20 ribu baris / ~3 MB per
potongan) dan dicek ulang di potongan 0, 90, dan 181: semuanya cocok persis.
Lebar potongan sekarang urusan kebenaran data, bukan kecepatan.

Sekarang setiap target TAP mengirim `MAXREC` secara eksplisit, dan
`downloaders._reject_truncated()` menolak hasil yang jumlah barisnya persis
menyentuh limit. Lebih baik gagal keras daripada meng-cache setengah katalog
yang kelihatan utuh. Pendekatan ini diambil dari `tap_queries()` milik Fase 5
di main dan diterapkan ke semua target TAP.

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

## 2026-08-20 — Fase 5: Menutup gap yang tercatat di REPORT.md §5

Fokusnya satu: bagian yang Fase 3-4 tinggalkan sebagai "belum dibangun".
Delapan dari sembilan item di REPORT.md §5 sekarang terisi; satu (famili
asteroid) tetap terbuka dengan alasan yang sama seperti sebelumnya.

**Sumber baru (6, semua diprobe hidup 2026-08-20)**

- `simbad_tap` — dulu terdaftar tapi `DOWNLOAD_PLAN`-nya `None`. Sekarang
  menarik sembilan query ADQL terbatas: lima irisan tipe objek (`otypes`
  BD*/N*/BH/sg*, plus kelas luminositas Ia+ untuk hipergiant) dan empat
  join tabel `ident` (HIP -> main_id/Gaia DR3/TIC/2MASS/HD). Tetap bukan
  dump: `basic` sendiri >15 juta baris.
- `atnf_pulsar_catalog` (VizieR B/psr/psr) — pulsar + magnetar.
- `blackcat_bh_transients` (VizieR J/A+A/587/A61/tablea1) — nama tabel
  `blackcat` yang ditebak pertama kali tidak ada; `tablea1` yang benar.
- `iau_meteor_data_center` — daftar hujan meteor resmi IAU.
- `sbdb_query_hyperbolic` — kelas orbit HYP/PAR/**HYA**.
- `jpl_horizons_elements` — elemen osculating Jupiter & Neptunus pada
  JD 2461200.5 (epoch yang dipakai mayoritas solusi orbit SBDB).

**Yang dibangun**

- `exoplanets/by_type/` — 12 kategori turunan (terrestrial, super_earth,
  sub_neptune, neptune_like, gas_giant, hot/warm/cold jupiter & neptune,
  ultra_short_period). Sengaja tumpang tindih: hot Jupiter masuk
  `gas_giant` dan `hot_jupiter` sekaligus.
- `exoplanets/habitable_zone/` — batas fluks Kopparapu et al. (2013,
  erratum 2014) dihitung ulang per bintang: 184 planet di zona
  konservatif, 18 di antaranya berpotensi berbatu. Plus `_unassessable/`
  untuk 376 planet yang Teff-nya hilang atau di luar rentang validitas
  2600-7200 K — termasuk seluruh sistem TRAPPIST-1 (Teff 2566 K).
  Ekstrapolasi ditolak, tapi objeknya didaftar lengkap dengan alasannya.
- `stars/special/` — tujuh subkategori yang dulu kosong sekarang terisi:
  pulsars (2536), magnetars (24, dari flag `Type`=AXP milik ATNF sendiri),
  neutron_stars (86), black_holes (5 + tabel BlackCAT), brown_dwarfs
  (3903), supergiants (538), hypergiants (104). Potongan kelas luminositas
  dari HYG ditulis sebagai file terpisah, tidak dilebur ke sensus katalog.
- `multiple_systems/binary/<nama>/` — 293 sistem bernama hasil cross-match
  posisi WDS x HYG. Dump katalog mentah pindah ke `multiple_systems/_catalogs/`
  supaya `binary/` isinya sistem saja.
- `solar_system/small_bodies/trojans/{l4,l5}` — 10403 vs 5975 (rasio 1,74,
  sesuai asimetri L4/L5 yang memang diamati). Ini geometri murni:
  L = Omega + omega + M dibanding bujur rata-rata Jupiter.
- `solar_system/small_bodies/trans_neptunian/{classical,resonant,scattered,
  detached,inner_belt}` — 2311/1928/2307/308/431. **Perkiraan**, dan
  ditandai begitu di tiap metadata.json.
- `solar_system/small_bodies/comets/interstellar/` — 1I/'Oumuamua,
  2I/Borisov, 3I/ATLAS.
- `solar_system/small_bodies/meteor_showers/` — 113 hujan established IAU.
- `_catalog/crosswalk.parquet` — dari 6 kolom jadi 20: SIMBAD main_id/otype/
  sp_type (117951 baris terisi), Gaia DR3 (113993), TIC (115340), 2MASS
  (116420), nama host exoplanet (795).
- Atribusi otomatis: `astro build` sekarang menstempel blok atribusi ke
  README tiap folder dari `source` di metadata.json-nya, plus
  `data/ATTRIBUTION.md` gabungan. `astro verify` menolak build yang folder
  datanya kehilangan blok itu.

**Yang ditemukan waktu mengerjakan**

- SBDB **tidak pernah** memakai designation IAU `1I/2I/3I` di field mana
  pun: 'Oumuamua tersimpan sebagai `'Oumuamua (A/2017 U1)` di kelas HYA
  (kelas yang tidak ikut ditarik di Fase 2), Borisov sebagai
  `C/2019 Q4 (Borisov)`, ATLAS sebagai `C/2025 N1 (ATLAS)`. Jadi
  "cari yang namanya berawalan angka+I" — pendekatan pertama — menghasilkan
  nol objek. Sekarang jembatannya tabel tiga baris yang eksplisit.
- Orbit hiperbolik saja bukan bukti antarbintang: 515 dari 520 komet HYP
  ada di bawah e=1,01, dan bahkan di antara yang e>=1,05 ada C/1980 E1 dan
  C/1954 O1 yang komet tata surya kena tendang Jupiter. Mereka disimpan di
  file terpisah, bukan dilabeli antarbintang.
- SIMBAD TAP sync diam-diam memotong hasil di 50000 baris. Query crosswalk
  yang pertama "berhasil" dengan tepat 50000 baris di lima file berbeda —
  angka bulat yang mencurigakan itu satu-satunya petunjuk. Sekarang
  `tap_queries()` mengirim MAXREC eksplisit dan **error** kalau hasilnya
  pas sama dengan MAXREC.
- Salinan ATNF Pulsar Catalogue di VizieR beku di 2536 pulsar sementara
  katalog aslinya sudah lewat 3500. Dikonfirmasi lewat `select count(*)`
  bahwa itu memang seluruh isi tabel, bukan query terpotong — dicatat di
  registry dan di README foldernya.
- `_load_class_file()` punya bug laten: `pl.DataFrame(...)` tanpa
  `infer_schema_length=None` menebak tipe kolom dari baris awal saja, dan
  meledak begitu ketemu nilai teks ("Great comet") di kolom yang tadinya
  terlihat numerik. Kelas HYP yang memicunya.
- `master_index.json` ternyata ikut menghitung file di `_catalog/schema/`
  sebagai objek: nama file skema memang sengaja sama dengan file daun yang
  divalidasinya (`moon.json`, `planet.json`, ...), jadi tiap tipe objek
  kelebihan satu sejak Fase 3. `astro verify` tidak menangkapnya karena
  cek "index vs live" memakai rglob yang sama persis, jadi dua-duanya salah
  dengan cara yang sama dan tetap "cocok". Angka di REPORT sekarang
  masing-masing turun satu — itu koreksi, bukan data hilang.
- Atribusi per-folder awalnya cuma kena 6510 folder dari ~33 ribu, karena
  builder small-bodies menulis `source: "jpl_sbdb_query"` — string yang
  bukan key registry mana pun — untuk 26 ribu folder asteroid bernama.
  Sekarang tiap kelas orbit membawa key sumbernya sendiri
  (`sbdb_query_neo`/`sbdb_query_full`), dan `source_keys_of()` mengerti
  string multi-sumber seperti `"jpl_sat_elem + jpl_sat_phys_par"`.
  Setelah diperbaiki: 33062 folder terstempel.
- Jendela cross-match nama: 5 arcsec dapat 274 bintang, 30 arcsec dapat
  293, 120 arcsec tetap 294. Dipakai 30 — posisi WDS Alpha Centauri
  16 arcsec dari HYG (gerak diri tinggi), dan di atas 30 tidak ada
  tambahan selain risiko salah pasang.
- Ambang toleransi resonansi TNO tidak bisa datar: 0,5 AU seragam menaruh
  Albion (cubewano purba) di resonansi 7:4. Sekarang lebarnya per
  resonansi, menyempit untuk resonansi orde tinggi.

**Masih belum dibangun**

- `asteroid_belt/_by_family/` — tetap butuh proper elements dari katalog
  famili (AstDyS `all.famrec` 104MB atau Nesvorny/PDS). File AstDyS-nya
  memang bisa diakses, tapi format kolomnya tidak terdokumentasi di
  servernya; menebak kolom mana yang ID famili sama saja dengan mengarang
  keanggotaan famili, jadi tidak dikerjakan.
- `usgs_gazetteer`, `ucs_satellite_db`, `spacetrack`, `open_exoplanet_catalogue`,
  Gaia DR3 penuh — alasannya tidak berubah dari REPORT.md §4.

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
