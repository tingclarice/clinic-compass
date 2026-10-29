"""Modul analisis spasial (Tugas B): Buffer dan Spatial Join.

Semua perhitungan jarak dilakukan dalam meter (EPSG:32749, UTM zona 49S).
"""
import geopandas as gpd
from shapely.geometry import Point

CRS_METER = "EPSG:32749"   # UTM zona 49 Selatan, untuk Surabaya
CRS_DERAJAT = "EPSG:4326"  # format asli data OSM


def ke_meter(gdf):
    """Ubah data dari derajat (OSM) ke meter. Jika sudah meter, dibiarkan."""
    if gdf.crs is None:
        raise ValueError("CRS data belum diketahui, tetapkan dulu dengan .set_crs()")
    if gdf.crs.to_string() == CRS_METER:
        return gdf
    return gdf.to_crs(CRS_METER)


def buat_radius(posisi_xy, radius_meter):
    """Buat area radius (Buffer) di sekitar posisi pengguna.

    posisi_xy: tuple (x, y) dalam meter.
    radius_meter: jarak pencarian, misalnya 3000 untuk 3 km.
    """
    titik = Point(posisi_xy)
    return gpd.GeoDataFrame(geometry=[titik.buffer(radius_meter)], crs=CRS_METER)


def klinik_dalam_radius(klinik, posisi_xy, radius_meter):
    """Spatial Join: ambil klinik yang berada di dalam radius pencarian.

    klinik: GeoDataFrame titik klinik.
    Mengembalikan klinik yang masuk radius, dengan kolom 'jarak_garis_lurus' (meter).
    """
    klinik = ke_meter(klinik)
    radius = buat_radius(posisi_xy, radius_meter)
    hasil = gpd.sjoin(klinik, radius, how="inner", predicate="intersects")
    hasil = hasil.drop(columns=["index_right"])
    hasil["jarak_garis_lurus"] = hasil.geometry.distance(Point(posisi_xy)).round(1)
    return hasil.sort_values("jarak_garis_lurus").reset_index(drop=True)


def cari_dengan_perluasan(klinik, posisi_xy, radius_awal=3000, radius_maks=5000):
    """Automatic Radius Expansion: coba 3 km, lalu 5 km jika kosong."""
    hasil = klinik_dalam_radius(klinik, posisi_xy, radius_awal)
    if len(hasil) == 0 and radius_maks > radius_awal:
        hasil = klinik_dalam_radius(klinik, posisi_xy, radius_maks)
    return hasil