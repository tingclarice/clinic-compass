from datetime import datetime
import geopandas as gpd
from shapely.geometry import Point
from src.jam_buka import cek_buka, tambah_status_buka, hanya_yang_buka

SENIN_SORE = datetime(2026, 10, 27, 17, 0)   # Selasa
SABTU_PAGI = datetime(2026, 10, 31, 10, 0)   # Sabtu
MINGGU_PAGI = datetime(2026, 11, 1, 10, 0)   # Minggu

def test_senin_jumat_sabtu_minggu_tutup():
    tag = "Mo-Fr 08:00-21:00"
    assert cek_buka(tag, SENIN_SORE) == "buka"
    assert cek_buka(tag, SABTU_PAGI) == "tutup"
    assert cek_buka(tag, MINGGU_PAGI) == "tutup"

def test_jam_tutup_tidak_termasuk():
    assert cek_buka("Mo-Fr 08:00-21:00", datetime(2026, 10, 27, 21, 0)) == "tutup"

def test_buka_lewat_tengah_malam():
    assert cek_buka("Mo-Su 22:00-02:00", datetime(2026, 10, 28, 1, 0)) == "buka"

def test_24_jam():
    assert cek_buka("24/7", MINGGU_PAGI) == "buka"

def test_tag_kosong_tidak_diketahui():
    assert cek_buka("", SENIN_SORE) == "tidak diketahui"
    assert cek_buka("   ", SENIN_SORE) == "tidak diketahui"
    assert cek_buka(None, SENIN_SORE) == "tidak diketahui"
    assert cek_buka(float("nan"), SENIN_SORE) == "tidak diketahui"

def test_tag_rusak_tidak_diketahui():
    assert cek_buka("tidak valid ;;", SENIN_SORE) == "tidak diketahui"

def test_filter_hanya_yang_buka():
    klinik = gpd.GeoDataFrame(
        {"nama": ["A", "B", "C"],
         "Jadwal_Operasional": ["Mo-Fr 08:00-21:00", "", "Mo-Su 00:00-24:00"]},
        geometry=[Point(0, 0)] * 3, crs="EPSG:32749")
    hasil = hanya_yang_buka(klinik, SENIN_SORE)
    assert hasil["nama"].tolist() == ["A", "C"]

def test_status_kolom_ditambahkan_tanpa_mengubah_asal():
    klinik = gpd.GeoDataFrame(
        {"nama": ["A"], "Jadwal_Operasional": ["Mo-Fr 08:00-21:00"]},
        geometry=[Point(0, 0)], crs="EPSG:32749")
    hasil = tambah_status_buka(klinik, SABTU_PAGI)
    assert hasil["status_buka"].tolist() == ["tutup"]
    assert "status_buka" not in klinik.columns