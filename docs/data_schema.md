# Skema Data Klinik — Clinic Compass

Dataset klinik disusun melalui `notebooks/01_data_collection.ipynb`. Batas wilayah dan data klinik
bersumber dari OpenStreetMap (© kontributor OpenStreetMap, lisensi ODbL) yang diakses melalui
library OSMnx, kemudian dilengkapi secara manual untuk atribut yang belum tersedia. Cakupan data
adalah klinik dan praktik dokter; puskesmas tidak disertakan.

## Pemanggilan dataset

```python
from src import data_processing as dp
klinik = dp.muat_klinik()   # GeoDataFrame, EPSG:32749, dengan kolom tambahan 'jadwal'
batas  = dp.muat_batas()    # GeoDataFrame tujuh kecamatan, EPSG:32749
```

Berkas GeoJSON disimpan dalam EPSG:4326 sesuai standar GeoJSON. Fungsi `muat_klinik()` dan
`muat_batas()` mengonversinya ke EPSG:32749 (UTM zona 49S) untuk operasi Buffer dan perhitungan jarak.

## Berkas

| Berkas | Isi |
|---|---|
| `data/processed/klinik_surabaya_barat.geojson` | Dataset klinik final |
| `data/processed/klinik_surabaya_barat.csv` | Dataset klinik final dalam bentuk tabel, dengan kolom Latitude dan Longitude |
| `data/processed/batas_surabaya_barat.geojson` | Batas tujuh kecamatan Surabaya Barat |
| `data/raw/jadwal_manual.csv` | Data manual untuk melengkapi jam operasional dan jenis layanan |
| `data/raw/klinik_tambahan.csv` | Data manual klinik dari sumber publik; klinik yang sudah tercatat di OpenStreetMap (nama serupa dalam radius 150 m) digabungkan, bukan ditambahkan ulang |
| `data/raw/klinik_tambahan_surabaya_barat.xlsx` | Lembar kerja verifikasi data manual beserta daftar sumber |

## Struktur kolom

| Kolom | Tipe | Keterangan | Contoh |
|---|---|---|---|
| `Clinic_ID` | teks | Identitas unik klinik | `K001` |
| `ID_Sumber` | teks | Identitas pada sumber data: `osm:<n/w/r><id>` atau `manual:<n>` | `osm:n123456789` |
| `Nama_Klinik` | teks | Nama klinik | `Klinik Pratama Sehat` |
| `Alamat` | teks | Alamat klinik (dapat kosong) | `Jl. Raya Lontar No. 1` |
| `Kecamatan` | teks | Kecamatan lokasi klinik, atau `Luar wilayah` | `Sambikerep` |
| `Jenis_Layanan` | teks | Daftar layanan, dipisahkan koma | `Dokter umum, Dokter gigi` |
| `Jadwal_Operasional` | teks | Jam operasional; kosong berarti tidak diketahui | `Mo-Fr 08:00-21:00; Sa 08:00-14:00` |
| `Status_24_Jam` | boolean | `True` bila beroperasi 24 jam setiap hari | `False` |
| `Sumber_Data` | teks | `OSM` atau `Manual` | `OSM` |
| `Sumber_Jam` | teks | Sumber jam operasional, atau kosong | `OSM` |
| `Di_Wilayah` | boolean | `True` bila berada di dalam tujuh kecamatan; `False` untuk area margin 2 km | `True` |
| `geometry` | Point | Lokasi klinik | |

Kolom tambahan hasil `muat_klinik()`:

| Kolom | Keterangan |
|---|---|
| `jadwal` | Hasil `parse_jadwal()`: `{hari: [(buka, tutup), ...]}` dalam menit sejak pukul 00.00. Hari 0 = Senin, 6 = Minggu. `None` berarti tidak diketahui |

## Format penulisan

**Jenis_Layanan.** Istilah baku: `Dokter umum`, `Dokter gigi`, `Dokter anak`, `Dokter kandungan`,
`Dokter mata`, `Dokter kulit`, `Penyakit dalam`, `THT`. Beberapa layanan dipisahkan dengan koma.
Spesialisasi dari tag OSM `healthcare:speciality` dikonversi otomatis ke istilah tersebut.

**Jadwal_Operasional.** Mengikuti format `opening_hours` OpenStreetMap. Kode hari: `Mo Tu We Th Fr Sa Su`.

| Kondisi | Penulisan |
|---|---|
| Senin–Jumat 08.00–21.00, Sabtu 08.00–14.00 | `Mo-Fr 08:00-21:00; Sa 08:00-14:00` |
| Setiap hari dengan jeda siang | `Mo-Su 07:00-12:00,16:00-21:00` |
| Melewati tengah malam | `Mo-Su 18:00-02:00` |
| Minggu tutup | `Mo-Sa 08:00-20:00; Su off` |
| 24 jam | `24 jam` |

Nilai 24 jam ditulis sebagai `24 jam`, bukan `24/7`, karena aplikasi spreadsheet dapat mengonversi `24/7` menjadi tanggal.

## Fungsi pendukung

```python
dp.buka_pada(jadwal, hari, menit)   # True / False / None; contoh: Jumat 20.00 -> hari=4, menit=1200
dp.teks_jam(jadwal, hari)           # "08.00–21.00", "Tutup", "24 jam", atau "Tidak diketahui"
dp.daftar_layanan("Dokter umum, Dokter gigi")   # ['Dokter umum', 'Dokter gigi']
```
