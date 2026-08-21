# crosswalk.parquet

119626 baris, satu per bintang HYG.

## Asal tiap kolom

- `hyg_id`, `hip`, `hd`, `hr`, `gliese`, `common_name` — dari HYG sendiri.
- `simbad_main_id`, `simbad_otype`, `simbad_sp_type`, `gaia_dr3_id`, `tic_id`, `twomass_id`, `simbad_hd_id` — dari tabel `ident`/`basic` SIMBAD, di-join lewat nomor HIP (bukan lewat posisi).
- `exoplanet_hostname`, `exoplanet_archive_tic_id`, `gaia_dr2_id` — dari pscomppars NASA Exoplanet Archive, juga lewat nomor HIP.
- Kolom `*_count` = berapa identifier yang SIMBAD punya untuk HIP itu; nilai yang disimpan adalah yang pertama. Kalau `> 1`, jangan pakai nilainya buta-buta.

## Cakupan (jumlah baris yang terisi)

| kolom | terisi |
|---|---:|
| `hip` | 117951 |
| `hd` | 98885 |
| `hr` | 9041 |
| `gliese` | 3801 |
| `common_name` | 465 |
| `simbad_main_id` | 117951 |
| `simbad_otype` | 117951 |
| `simbad_sp_type` | 114299 |
| `gaia_dr3_id` | 113993 |
| `gaia_dr3_id_count` | 113993 |
| `tic_id` | 115340 |
| `tic_id_count` | 115340 |
| `twomass_id` | 116420 |
| `twomass_id_count` | 116420 |
| `simbad_hd_id` | 98960 |
| `simbad_hd_id_count` | 98960 |
| `exoplanet_hostname` | 795 |
| `exoplanet_archive_tic_id` | 794 |
| `gaia_dr2_id` | 782 |

## Yang masih kosong

KIC (Kepler Input Catalog) tidak dimasukkan: SIMBAD cuma punya 347 identifier KIC yang beririsan dengan HIP, jadi kolomnya akan hampir seluruhnya null. Bintang tanpa nomor HIP (mayoritas host exoplanet TESS/Kepler) belum punya baris di sini — kuncinya HIP, dan menambahkan kunci kedua butuh crossmatch posisi tersendiri.

<!-- attribution:begin -->
## Sumber & atribusi

- **HYG Database (120k stars, common + Bayer/Flamsteed names)** (`hyg_database`)
  - URL: https://github.com/astronexus/HYG-Database
  - Lisensi/atribusi: CC BY-SA 4.0 (per repo)
- **SIMBAD TAP (identifiers, object types, cross-match)** (`simbad_tap`)
  - URL: https://simbad.cds.unistra.fr/simbad/sim-tap/sync
  - Lisensi/atribusi: CDS — attribution required
- **NASA Exoplanet Archive TAP — pscomppars** (`exoplanet_archive_pscomppars`)
  - URL: https://exoplanetarchive.ipac.caltech.edu/TAP/sync
  - Lisensi/atribusi: Public domain (NASA); attribution requested by IPAC

<!-- attribution:end -->
