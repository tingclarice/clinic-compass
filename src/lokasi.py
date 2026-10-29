"""Lokasi pengguna (Tugas B): titik awal dari klik peta dan gerak dengan tombol panah.

Semua koordinat dalam meter (EPSG:32749). Peta tidak diputar, jadi arah panah
langsung sama dengan arah pada peta.
"""
import math
from shapely.geometry import Point

ARAH_PANAH = {
    "kanan": (1, 0),
    "kiri": (-1, 0),
    "atas": (0, 1),
    "bawah": (0, -1),
}
JARAK_LANGKAH = 50  # meter per tekan tombol


def posisi_dari_klik(x, y):
    """Ubah hasil klik peta (xdata, ydata) menjadi posisi pengguna."""
    if x is None or y is None:
        raise ValueError("klik di luar peta, titik awal tidak berubah")
    if not (math.isfinite(x) and math.isfinite(y)):
        raise ValueError("koordinat klik tidak valid")
    return Point(float(x), float(y))


def geser(posisi, arah, jarak=JARAK_LANGKAH):
    """Geser posisi satu langkah ke arah panah yang diberikan."""
    arah = arah.lower()
    if arah not in ARAH_PANAH:
        raise ValueError(f"arah '{arah}' tidak dikenal, pilih: {', '.join(ARAH_PANAH)}")
    if jarak <= 0:
        raise ValueError("jarak harus lebih dari 0")
    dx, dy = ARAH_PANAH[arah]
    return Point(posisi.x + dx * jarak, posisi.y + dy * jarak)