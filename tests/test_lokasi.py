import pytest
from shapely.geometry import Point
from src.lokasi import posisi_dari_klik, geser, JARAK_LANGKAH

def test_klik_jadi_titik():
    assert posisi_dari_klik(500.0, 300.0) == Point(500, 300)

def test_klik_di_luar_peta():
    with pytest.raises(ValueError):
        posisi_dari_klik(None, 300)

def test_klik_nan():
    with pytest.raises(ValueError):
        posisi_dari_klik(float("nan"), 300)

def test_geser_keempat_arah():
    p = Point(0, 0)
    assert geser(p, "atas") == Point(0, JARAK_LANGKAH)
    assert geser(p, "bawah") == Point(0, -JARAK_LANGKAH)
    assert geser(p, "kanan") == Point(JARAK_LANGKAH, 0)
    assert geser(p, "kiri") == Point(-JARAK_LANGKAH, 0)

def test_geser_huruf_besar_diterima():
    assert geser(Point(0, 0), "KANAN", 100) == Point(100, 0)

def test_arah_tidak_dikenal():
    with pytest.raises(ValueError):
        geser(Point(0, 0), "utara")

def test_jarak_nol_ditolak():
    with pytest.raises(ValueError):
        geser(Point(0, 0), "atas", 0)