"""
Clinic Compass — modul pengumpulan dan pengolahan data klinik.

Tahapan:
1. Mengambil batas tujuh kecamatan Surabaya Barat dari OpenStreetMap (OSM).
2. Mengambil data klinik dari OSM beserta atribut nama, alamat, spesialisasi,
   dan jam operasional.
3. Melengkapi atribut yang belum tersedia melalui data manual (CSV).
4. Menyimpan dataset akhir ke data/processed/.

Contoh pemanggilan dataset:
    from src import data_processing as dp
    klinik = dp.muat_klinik()    # GeoDataFrame klinik, EPSG:32749
    batas = dp.muat_batas()      # GeoDataFrame batas kecamatan, EPSG:32749
"""
from pathlib import Path
import re

import numpy as np
import pandas as pd
import geopandas as gpd
import osmnx as ox

# ============================================================
# Konfigurasi
# ============================================================
KECAMATAN = ["Asemrowo", "Benowo", "Lakarsantri", "Pakal",
             "Sambikerep", "Sukomanunggal", "Tandes"]
CRS_UTM = "EPSG:32749"       # UTM zona 49S (meter), digunakan untuk seluruh perhitungan
CRS_WGS84 = "EPSG:4326"      # lintang/bujur, digunakan untuk penyimpanan GeoJSON
MARGIN_M = 2000              # area pengambilan data diperluas 2 km dari batas wilayah
TAGS_KLINIK = {"amenity": ["clinic", "doctors", "dentist"],
               "healthcare": ["clinic", "doctor", "dentist"]}
KATA_DIKECUALIKAN = ("puskesmas", "pustu")     # cakupan data: klinik, tidak termasuk puskesmas

ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
FILE_BATAS = DATA_PROCESSED / "batas_surabaya_barat.geojson"
FILE_KLINIK = DATA_PROCESSED / "klinik_surabaya_barat.geojson"
FILE_KLINIK_CSV = DATA_PROCESSED / "klinik_surabaya_barat.csv"
FILE_JADWAL_MANUAL = DATA_RAW / "jadwal_manual.csv"
FILE_KLINIK_TAMBAHAN = DATA_RAW / "klinik_tambahan.csv"

KOLOM_FINAL = ["Clinic_ID", "ID_Sumber", "Nama_Klinik", "Alamat", "Kecamatan", "Jenis_Layanan",
               "Jadwal_Operasional", "Status_24_Jam", "Sumber_Data", "Sumber_Jam",
               "Di_Wilayah", "geometry"]

ox.settings.use_cache = True
ox.settings.cache_folder = str(ROOT / "cache")
ox.settings.http_user_agent = "ClinicCompass/1.0 (proyek mata kuliah Computer Graphics, Universitas Ciputra)"

# Server Overpass API: server utama dan instance publik alternatif
OVERPASS_SERVER = [
    "https://overpass-api.de/api",
    "https://overpass.kumi.systems/api",
    "https://overpass.private.coffee/api",
    "https://maps.mail.ru/osm/tools/overpass/api",
]


def _overpass(fungsi, *args, **kwargs):
    """Menjalankan query OSMnx ke server Overpass secara berurutan hingga berhasil."""
    galat = None
    for url in OVERPASS_SERVER:
        ox.settings.overpass_url = url
        ox.settings.overpass_rate_limit = url == OVERPASS_SERVER[0]
        try:
            return fungsi(*args, **kwargs)
        except ox._errors.InsufficientResponseError:
            raise
        except Exception as e:
            print(f"Server {url} tidak dapat digunakan ({type(e).__name__}); mencoba server berikutnya.")
            galat = e
    raise RuntimeError("Seluruh server Overpass tidak dapat diakses.") from galat


# ============================================================
# 1. Batas wilayah
# ============================================================
def ambil_batas():
    """Batas tujuh kecamatan Surabaya Barat (kolom: kec, geometry) dalam EPSG:32749."""
    try:
        b = _overpass(ox.features_from_place, "Surabaya, Jawa Timur, Indonesia",
                      tags={"boundary": "administrative", "admin_level": "6"})
        b = b[b.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
        b["kec"] = b["name"].str.replace(r"^(Kecamatan|Kec\.)\s*", "", regex=True).str.strip()
        b = b[b["kec"].isin(KECAMATAN)].drop_duplicates("kec")
        if b["kec"].nunique() < len(KECAMATAN):
            raise ValueError(f"kecamatan tidak lengkap: {sorted(set(KECAMATAN) - set(b['kec']))}")
    except Exception as e:
        print(f"Pengambilan batas administratif gagal ({e}); menggunakan geocoding per kecamatan.")
        b = ox.geocode_to_gdf([f"Kecamatan {k}, Surabaya, Jawa Timur, Indonesia" for k in KECAMATAN])
        b["kec"] = KECAMATAN
    return b[["kec", "geometry"]].to_crs(CRS_UTM).reset_index(drop=True)


def area_pengambilan(batas):
    """Polygon wilayah ditambah margin, dalam lintang/bujur sesuai kebutuhan query OSM."""
    wilayah = batas.union_all()
    return gpd.GeoSeries([wilayah.buffer(MARGIN_M)], crs=CRS_UTM).to_crs(CRS_WGS84).iloc[0]


# ============================================================
# 2. Data klinik dari OSM
# ============================================================
PETA_SPESIALISASI = {
    "general": "Dokter umum",
    "dentistry": "Dokter gigi", "orthodontics": "Dokter gigi",
    "dental_oral_maxillo_facial_surgery": "Dokter gigi",
    "paediatrics": "Dokter anak", "pediatrics": "Dokter anak",
    "gynaecology": "Dokter kandungan", "obstetrics": "Dokter kandungan",
    "internal": "Penyakit dalam",
    "ophthalmology": "Dokter mata",
    "otolaryngology": "THT",
    "dermatology": "Dokter kulit",
    "cardiology": "Dokter jantung",
    "orthopaedics": "Ortopedi",
    "psychiatry": "Psikiatri",
    "physiotherapy": "Fisioterapi",
}


def _nilai(r, kolom):
    v = r.get(kolom, "")
    return "" if pd.isna(v) else str(v)


def _alamat_osm(r):
    if _nilai(r, "addr:full"):
        return _nilai(r, "addr:full")
    return " ".join(x for x in [_nilai(r, "addr:street"), _nilai(r, "addr:housenumber")] if x)


def tebak_layanan(r):
    """Jenis layanan berdasarkan tag healthcare:speciality; bila kosong,
    ditentukan dari jenis fasilitas dan nama klinik."""
    nama = _nilai(r, "name").lower()
    spes = [x.strip().lower() for x in re.split(r"[;,]", _nilai(r, "healthcare:speciality")) if x.strip()]
    gigi = (_nilai(r, "amenity") == "dentist" or _nilai(r, "healthcare") == "dentist"
            or "gigi" in nama or "dental" in nama or "drg" in nama)
    layanan = []
    for x in spes:
        nama_layanan = PETA_SPESIALISASI.get(x, x.replace("_", " ").capitalize())
        if nama_layanan not in layanan:
            layanan.append(nama_layanan)
    if not layanan:
        layanan.append("Dokter gigi" if gigi else "Dokter umum")
    elif gigi and "Dokter gigi" not in layanan:
        layanan.append("Dokter gigi")
    return ", ".join(layanan)


def hapus_duplikat(gdf, jarak_m=60):
    """Menghapus klinik yang tercatat lebih dari sekali (misalnya sebagai titik dan bangunan):
    klinik bernama sama dalam radius 60 m dianggap satu. Data dengan jam operasional diutamakan."""
    gdf = gdf.sort_values("Jadwal_Operasional", ascending=False)
    simpan = []
    for nama, grp in gdf.groupby("Nama_Klinik", sort=False):
        if nama == "Klinik tanpa nama":
            simpan += list(grp.index)
            continue
        dipilih = []
        for i, g in grp.geometry.items():
            if all(g.distance(gdf.geometry[j]) > jarak_m for j in dipilih):
                dipilih.append(i)
        simpan += dipilih
    return gdf.loc[sorted(simpan)].reset_index(drop=True)


def bukan_puskesmas(nama):
    return not any(k in str(nama).lower() for k in KATA_DIKECUALIKAN)


def tandai_kecamatan(klinik, batas):
    """Menambahkan kolom Kecamatan dan Di_Wilayah melalui Spatial Join (within)."""
    k = klinik.drop(columns=["Kecamatan", "Di_Wilayah"], errors="ignore")
    j = gpd.sjoin(k, batas[["kec", "geometry"]], how="left", predicate="within")
    j = j[~j.index.duplicated()].drop(columns="index_right")
    j["Di_Wilayah"] = j["kec"].notna()
    j["Kecamatan"] = j["kec"].fillna("Luar wilayah")
    return j.drop(columns="kec")


def ambil_klinik_osm(batas):
    """Mengambil klinik dari OSM dan menyusunnya sesuai skema data (EPSG:32749)."""
    raw = _overpass(ox.features_from_polygon, area_pengambilan(batas), tags=TAGS_KLINIK)
    raw = raw.to_crs(CRS_UTM).reset_index()
    el = raw["element"] if "element" in raw.columns else raw["element_type"]
    oid = raw["id"] if "id" in raw.columns else raw["osmid"]
    klinik = gpd.GeoDataFrame({
        "ID_Sumber": ("osm:" + el.astype(str).str[0] + oid.astype(str)).values,
        "Nama_Klinik": [_nilai(r, "name") or "Klinik tanpa nama" for _, r in raw.iterrows()],
        "Alamat": [_alamat_osm(r) for _, r in raw.iterrows()],
        "Jenis_Layanan": [tebak_layanan(r) for _, r in raw.iterrows()],
        "Jadwal_Operasional": [_nilai(r, "opening_hours") for _, r in raw.iterrows()],
    }, geometry=raw.geometry.centroid.values, crs=CRS_UTM)      # bangunan direpresentasikan sebagai titik pusat
    klinik["Sumber_Data"] = "OSM"
    klinik["Sumber_Jam"] = np.where(klinik["Jadwal_Operasional"] != "", "OSM", "")
    filter_klinik = klinik["Nama_Klinik"].apply(bukan_puskesmas)
    if (~filter_klinik).any():
        print(f"Puskesmas tidak disertakan: {int((~filter_klinik).sum())} data")
    klinik = hapus_duplikat(klinik[filter_klinik])
    return tandai_kecamatan(klinik, batas)


# ============================================================
# 3. Jam operasional (format opening_hours OSM)
#    Contoh: "Mo-Fr 08:00-21:00; Sa 08:00-14:00", "Mo-Su 07:00-12:00,16:00-21:00", "24 jam"
# ============================================================
HARI = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
NAMA_HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
_H = r"(?:Mo|Tu|We|Th|Fr|Sa|Su)"
_POLA_ATURAN = re.compile(rf"^({_H}(?:\s*[-,]\s*{_H})*)?\s*(.*)$")
_PENUH = ("24/7", "24jam")


def _menit(t):
    j, m = t.strip().split(":")
    return int(j) * 60 + int(m)


def _daftar_hari(teks):
    hasil = []
    for bag in teks.replace(" ", "").split(","):
        if "-" in bag:
            a, b = (HARI.index(x) for x in bag.split("-"))
            hasil += [(a + k) % 7 for k in range((b - a) % 7 + 1)]
        else:
            hasil.append(HARI.index(bag))
    return hasil


def parse_jadwal(teks):
    """Mengubah teks jam operasional menjadi {indeks_hari: [(buka, tutup), ...]} dalam menit
    sejak pukul 00.00 (0 = Senin, ..., 6 = Minggu). Bernilai None bila kosong atau tidak terbaca."""
    if not isinstance(teks, str) or not teks.strip():
        return None
    s = re.sub(r"(\d{1,2})\.(\d{2})", r"\1:\2", teks.strip())      # 08.00 -> 08:00
    s = re.sub(rf"(?<=\d)\s*,\s*(?={_H})", ";", s)                   # pemisah antaraturan
    if s.replace(" ", "").lower() in _PENUH:
        return {d: [(0, 1440)] for d in range(7)}
    jadwal = {d: [] for d in range(7)}
    try:
        for aturan in s.split(";"):
            aturan = aturan.strip()
            if not aturan or aturan.startswith(("PH", "SH")):        # aturan hari libur tidak digunakan
                continue
            hari_txt, waktu = _POLA_ATURAN.match(aturan).groups()
            hari = _daftar_hari(hari_txt) if hari_txt else list(range(7))
            waktu = waktu.strip()
            if waktu.lower() in ("off", "closed", "tutup"):
                rentang = []
            elif waktu.replace(" ", "").lower() in _PENUH:
                rentang = [(0, 1440)]
            else:
                rentang = [tuple(_menit(x) for x in bag.split("-")) for bag in waktu.split(",")]
                if any(len(r) != 2 for r in rentang):
                    return None
            for d in hari:
                jadwal[d] = rentang                                    # aturan berikutnya menggantikan aturan sebelumnya
    except (ValueError, AttributeError):
        return None
    return jadwal


def buka_pada(jadwal, hari, menit):
    """True/False sesuai status buka pada hari dan menit tertentu; None bila jadwal tidak diketahui.
    Jadwal yang melewati tengah malam ikut diperhitungkan."""
    if jadwal is None:
        return None
    for a, b in jadwal[hari]:
        if b <= a:
            b += 1440
        if a <= menit < b:
            return True
    for a, b in jadwal[(hari - 1) % 7]:
        if b <= a:
            b += 1440
        if b > 1440 and menit < b - 1440:
            return True
    return False


def teks_jam(jadwal, hari):
    """Jam operasional pada satu hari dalam bentuk teks."""
    if jadwal is None:
        return "Tidak diketahui"
    r = jadwal[hari]
    if not r:
        return "Tutup"
    if r == [(0, 1440)]:
        return "24 jam"
    f = lambda m: f"{(m // 60) % 24:02d}.{m % 60:02d}"
    return ", ".join(f"{f(a)}–{f(b)}" for a, b in r)


def is_24_jam(jadwal):
    return jadwal is not None and all(jadwal[d] == [(0, 1440)] for d in range(7))


def daftar_layanan(teks):
    """'dokter umum, THT' -> ['Dokter umum', 'THT']"""
    hasil = []
    for x in re.split(r"[,;]", str(teks)):
        x = x.strip()
        if x:
            hasil.append(x if x.isupper() else x.capitalize())
    return hasil


# ============================================================
# 4. Data manual (CSV)
# ============================================================
_KOLOM_JADWAL = ["ID_Sumber", "Nama_Klinik", "Alamat", "Kecamatan", "Jenis_Layanan", "Jadwal_Operasional", "Sumber_Jam"]
_KOLOM_TAMBAHAN = ["Nama_Klinik", "Alamat", "Latitude", "Longitude", "Jenis_Layanan", "Jadwal_Operasional", "Sumber_Jam"]


def siapkan_template_jadwal(klinik, path=FILE_JADWAL_MANUAL):
    """Membuat atau memperbarui templat data manual. Isian yang sudah ada dipertahankan;
    klinik baru ditambahkan di akhir berkas."""
    baru = pd.DataFrame(klinik[_KOLOM_JADWAL])
    baru = baru[klinik["Di_Wilayah"].values]
    if path.exists():
        lama = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
        baru = pd.concat([lama, baru[~baru["ID_Sumber"].isin(lama["ID_Sumber"])]], ignore_index=True)
    baru.to_csv(path, index=False, encoding="utf-8-sig")
    kosong = int((baru["Jadwal_Operasional"] == "").sum())
    print(f"Templat: {path.relative_to(ROOT)} ({len(baru)} klinik, {kosong} tanpa jam operasional)")


def gabung_jadwal_manual(klinik, path=FILE_JADWAL_MANUAL):
    """Menggabungkan isian manual ke data klinik berdasarkan ID_Sumber.
    Nilai manual yang tidak kosong menggantikan nilai dari OSM."""
    if not path.exists():
        print("Berkas jadwal_manual.csv belum tersedia; penggabungan dilewati.")
        return klinik
    isi = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("").set_index("ID_Sumber")
    k = klinik.set_index("ID_Sumber")
    diubah = 0
    for kolom in ["Nama_Klinik", "Alamat", "Jenis_Layanan", "Jadwal_Operasional", "Sumber_Jam"]:
        if kolom not in isi.columns:
            continue
        baru = isi[kolom].reindex(k.index).fillna("")
        ganti = (baru != "") & (baru != k[kolom])
        k.loc[ganti, kolom] = baru[ganti]
        diubah += int(ganti.sum())
    print(f"Data manual digabungkan: {diubah} nilai diperbarui.")
    return k.reset_index()


_KATA_UMUM = {"klinik", "clinic", "pratama", "utama", "surabaya", "praktik", "praktek", "the"}


def _nama_normal(nama):
    kata = re.sub(r"[^a-z0-9 ]", " ", str(nama).lower()).split()
    return " ".join(k for k in kata if k not in _KATA_UMUM)


def _nama_mirip(a, b):
    from difflib import SequenceMatcher
    a, b = _nama_normal(a), _nama_normal(b)
    if not a or not b:
        return False
    return a == b or a in b or b in a or SequenceMatcher(None, a, b).ratio() >= 0.8


def tambah_klinik_manual(klinik, batas, path=FILE_KLINIK_TAMBAHAN, jarak_m=150):
    """Menambahkan klinik dari berkas klinik_tambahan.csv. Baris tanpa koordinat dilewati.
    Klinik yang sudah ada di data OSM (nama serupa dalam radius 150 m) tidak ditambahkan ulang;
    atribut manual yang tidak kosong digunakan untuk melengkapi data OSM tersebut."""
    if not path.exists():
        pd.DataFrame(columns=_KOLOM_TAMBAHAN).to_csv(path, index=False, encoding="utf-8-sig")
        print(f"Berkas kosong dibuat: {path.relative_to(ROOT)}")
        return klinik
    t = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    for kolom in _KOLOM_TAMBAHAN:
        if kolom not in t.columns:
            t[kolom] = ""
    t = t[(t["Latitude"].str.strip() != "") & (t["Longitude"].str.strip() != "")]
    t = t[t["Nama_Klinik"].apply(bukan_puskesmas)]
    if t.empty:
        print("Tidak ada klinik tambahan dengan koordinat.")
        return klinik
    g = gpd.GeoDataFrame(
        {"Nama_Klinik": t["Nama_Klinik"].values,
         "Alamat": t["Alamat"].values,
         "Jenis_Layanan": t["Jenis_Layanan"].values,
         "Jadwal_Operasional": t["Jadwal_Operasional"].values,
         "Sumber_Jam": t["Sumber_Jam"].values},
        geometry=gpd.points_from_xy(t["Longitude"].str.replace(",", ".").astype(float),
                                    t["Latitude"].str.replace(",", ".").astype(float)),
        crs=CRS_WGS84).to_crs(CRS_UTM)
    klinik = gpd.GeoDataFrame(klinik, geometry="geometry", crs=CRS_UTM).reset_index(drop=True)
    baru, digabung = [], 0
    for _, r in g.iterrows():
        dekat = klinik[klinik.geometry.distance(r.geometry) <= jarak_m]
        cocok = [i for i, k in dekat.iterrows() if _nama_mirip(k["Nama_Klinik"], r["Nama_Klinik"])]
        if cocok:
            i = cocok[0]
            for kolom in ["Alamat", "Jenis_Layanan", "Jadwal_Operasional", "Sumber_Jam"]:
                if str(r[kolom]).strip():
                    klinik.at[i, kolom] = r[kolom]
            digabung += 1
        else:
            baru.append(r)
    if baru:
        g_baru = gpd.GeoDataFrame(baru, geometry="geometry", crs=CRS_UTM).reset_index(drop=True)
        g_baru.insert(0, "ID_Sumber", [f"manual:{i + 1}" for i in range(len(g_baru))])
        g_baru["Sumber_Data"] = "Manual"
        g_baru = tandai_kecamatan(g_baru, batas)
        klinik = pd.concat([klinik, g_baru], ignore_index=True)
    print(f"Klinik tambahan: {len(baru)} ditambahkan, {digabung} digabungkan dengan data OSM.")
    return klinik


# ============================================================
# 5. Finalisasi, penyimpanan, dan pemanggilan dataset
# ============================================================
def finalisasi(klinik, batas):
    """Menyusun kolom sesuai skema data (docs/data_schema.md) dan memberi Clinic_ID."""
    k = tandai_kecamatan(gpd.GeoDataFrame(klinik, geometry="geometry", crs=CRS_UTM), batas)
    for kolom in ["Alamat", "Jenis_Layanan", "Jadwal_Operasional", "Sumber_Jam"]:
        k[kolom] = k[kolom].fillna("") if kolom in k.columns else ""
    k["Jenis_Layanan"] = k["Jenis_Layanan"].apply(lambda t: ", ".join(daftar_layanan(t)))
    k["Status_24_Jam"] = k["Jadwal_Operasional"].apply(lambda t: is_24_jam(parse_jadwal(t)))
    k = k.sort_values(["Di_Wilayah", "Kecamatan", "Nama_Klinik"], ascending=[False, True, True])
    k["Clinic_ID"] = [f"K{i + 1:03d}" for i in range(len(k))]
    salah = k[(k["Jadwal_Operasional"] != "") & k["Jadwal_Operasional"].apply(lambda t: parse_jadwal(t) is None)]
    if len(salah):
        print(f"Peringatan: {len(salah)} jadwal tidak dapat dibaca dan dianggap tidak diketahui.")
        print(salah[["Clinic_ID", "ID_Sumber", "Nama_Klinik", "Jadwal_Operasional"]].to_string(index=False))
    return k[KOLOM_FINAL].reset_index(drop=True)


def simpan_dataset(klinik, batas):
    """Menyimpan dataset ke data/processed/ dalam format GeoJSON (EPSG:4326) dan CSV."""
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    batas.to_crs(CRS_WGS84).to_file(FILE_BATAS, driver="GeoJSON")
    klinik.to_crs(CRS_WGS84).to_file(FILE_KLINIK, driver="GeoJSON")
    tabel = pd.DataFrame(klinik.drop(columns="geometry"))
    ll = klinik.to_crs(CRS_WGS84).geometry
    tabel["Latitude"], tabel["Longitude"] = ll.y.round(6).values, ll.x.round(6).values
    tabel.to_csv(FILE_KLINIK_CSV, index=False, encoding="utf-8-sig")
    for f in (FILE_BATAS, FILE_KLINIK, FILE_KLINIK_CSV):
        print("Tersimpan:", f.relative_to(ROOT))


def muat_batas():
    """Batas wilayah dalam EPSG:32749."""
    return gpd.read_file(FILE_BATAS).to_crs(CRS_UTM)


def muat_klinik():
    """Dataset klinik dalam EPSG:32749 beserta kolom 'jadwal' hasil parse_jadwal()."""
    k = gpd.read_file(FILE_KLINIK).to_crs(CRS_UTM)
    for kolom in ["Alamat", "Jenis_Layanan", "Jadwal_Operasional", "Sumber_Jam"]:
        k[kolom] = k[kolom].fillna("")
    k["jadwal"] = k["Jadwal_Operasional"].apply(parse_jadwal)
    return k


def ringkasan_data(klinik):
    """Jumlah klinik dan kelengkapan jam operasional per kecamatan."""
    k = klinik[klinik["Di_Wilayah"]].copy()
    k["Punya_Jam"] = k["Jadwal_Operasional"].apply(lambda t: parse_jadwal(t) is not None)
    r = k.groupby("Kecamatan").agg(Jumlah_Klinik=("Clinic_ID", "count"),
                                   Punya_Jam=("Punya_Jam", "sum"))
    r.loc["TOTAL"] = r.sum()
    r["Persen_Lengkap"] = (100 * r["Punya_Jam"] / r["Jumlah_Klinik"]).round(1)
    return r
