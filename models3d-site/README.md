# Star 3D Models — Cloudflare Pages site

Situs statis (tanpa backend, tanpa build step) untuk menjelajah dan mengunduh
model 3D resmi satelit buatan manusia, komet, asteroid, dan Matahari,
langsung dari server NASA / ESA / JAXA.

- `index.html` — halaman katalog (vanilla HTML/CSS/JS, preview 3D via
  [`<model-viewer>`](https://modelviewer.dev/) untuk file `.glb`).
- `catalog.json` — daftar model + link download, diedit manual (lihat
  bagian "Menambah model" di bawah).

Setiap tombol download adalah link langsung (`<a href download>`) ke file
aslinya di server badan antariksa terkait — situs ini **tidak menyimpan
ulang (mirror)** file model, jadi tidak perlu R2/storage tambahan di
Cloudflare.

## Deploy ke Cloudflare Pages

**Opsi A — Dashboard (drag & drop, paling cepat):**
1. Buka [Cloudflare dashboard → Workers & Pages → Create → Pages → Upload assets](https://dash.cloudflare.com/).
2. Upload folder `models3d-site/` ini (isinya, bukan foldernya) sebagai project baru.
3. Deploy — selesai, dapat URL `*.pages.dev`.

**Opsi B — Wrangler CLI:**
```bash
npm install -g wrangler
cd models3d-site
wrangler pages deploy . --project-name=star-3d-models
```

**Opsi C — Git integration:** hubungkan repo GitHub ini ke Cloudflare
Pages, set *build output directory* ke `models3d-site` (tidak perlu build
command, langsung serve static).

## Menambah model baru

Tambahkan objek baru ke array `items` di `catalog.json`:

```json
{
  "id": "nama-unik",
  "name": "Nama Tampilan",
  "category": "satellite | comet | asteroid | star",
  "agency": "NASA | ESA | JAXA | ...",
  "summary_id": "Deskripsi singkat.",
  "source_page": "https://... (halaman resmi tempat model ini didapat)",
  "license": "Public domain (NASA) / atau ketentuan lisensi sumbernya",
  "files": [
    { "format": "glb", "url": "https://...", "size_mb": 12.3 }
  ]
}
```

**Penting — jangan menebak URL file.** Selalu verifikasi link download
langsung dengan membuka halaman resmi sumbernya dulu (science.nasa.gov,
sci.esa.int, asteroidmission.org, data.darts.isas.jaxa.jp, dll), supaya
tidak ada link yang mati atau salah.

## Sumber & lisensi

- **NASA** (`science.nasa.gov/3d-resources`, `assets.science.nasa.gov`):
  materi pemerintah AS, umumnya domain publik — bebas dipakai, atribusi
  dianjurkan tapi umumnya tidak wajib.
- **ESA** (komet 67P, `sci.esa.int`): wajib mencantumkan kredit sesuai yang
  tertulis di halaman sumber (mis. *"Credits: ESA/Rosetta/MPS for OSIRIS
  Team..."*).
- **JAXA** (asteroid Ryugu, `data.darts.isas.jaxa.jp`): wajib atribusi,
  lihat `README.html` pada folder data resminya.

Model bentuk (*shape model*) untuk komet/asteroid (67P, Bennu, Ryugu) adalah
mesh geometris hasil rekonstruksi ilmiah — **tidak bertekstur foto**,
berbeda dari model wahana antariksa (Hubble, JWST, dll.) yang sudah punya
tekstur/material di dalam file `.glb`/`.usdz`-nya.

## Kenapa tidak semua ~378 model NASA ada di sini?

Katalog ini adalah pilihan terkurasi (20 objek) yang linknya sudah
diverifikasi satu per satu agar tidak ada yang menebak atau mati. Untuk
menjelajah seluruh katalog NASA, ESA, atau katalog shape-model
asteroid/komet lainnya, lihat kotak "Ingin lebih banyak?" di bagian bawah
halaman (`more_links` di `catalog.json`).
