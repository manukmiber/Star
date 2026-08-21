# Atribusi sumber data

Setiap folder di bawah `data/` punya blok atribusi sendiri di README.md-nya, dihasilkan dari `source` di metadata.json folder itu. Daftar di bawah adalah gabungan seluruh sumber yang benar-benar terpakai di build terakhir.

<!-- attribution:begin -->
## Sumber & atribusi

- **JPL Horizons API (ephemeris & physical parameters)** (`jpl_horizons`)
  - URL: https://ssd.jpl.nasa.gov/api/horizons.api
  - Lisensi/atribusi: Public domain (NASA/JPL)
- **NASA 3D Resources (model, tekstur, model cetak 3D)** (`nasa_3d_resources`)
  - URL: https://github.com/nasa/NASA-3D-Resources
  - Lisensi/atribusi: Public domain / NASA Open Source Agreement v1.3 (lihat meta.json + usage guidelines repo)
- **NASA Earth Observatory — koleksi Blue Marble** (`nasa_blue_marble_textures`)
  - URL: https://science.nasa.gov/earth/earth-observatory/collections/blue-marble/
  - Lisensi/atribusi: Public domain (NASA Earth Observatory), atribusi diminta
- **NASA Science 3D Resources (halaman per-model + aset STL/GLB)** (`nasa_science_3d`)
  - URL: https://science.nasa.gov/3d-resources/
  - Lisensi/atribusi: Public domain (NASA), lihat NASA media usage guidelines
- **NASA Scientific Visualization Studio — CGI texture kit** (`nasa_svs_texture_kits`)
  - URL: https://svs.gsfc.nasa.gov/
  - Lisensi/atribusi: Public domain (NASA/GSFC SVS), atribusi diminta
- **PDS Small Bodies Node — shape model komet, asteroid, satelit** (`pds_sbn_shape_models`)
  - URL: https://sbn.psi.edu/pds/shape-models/
  - Lisensi/atribusi: Public domain (NASA PDS); tiap dataset punya referensi/atribusi sendiri di dataset.html-nya

<!-- attribution:end -->

Catatan: CDS/VizieR (WDS, SB9, MSC, ATNF, BlackCAT), SIMBAD, CelesTrak, dan MPC secara eksplisit meminta atribusi di setiap karya turunan. Kalau kamu menerbitkan apa pun dari data lake ini, sertakan baris-baris di atas.
