"""Jam operasional per hari (Tugas B), membaca tag opening_hours dari OSM.

Hasil status: "buka", "tutup", atau "tidak diketahui".
Klinik tanpa tag, atau tag yang tidak bisa dibaca, TIDAK dianggap buka.
"""
import math
from datetime import datetime

from opening_hours import OpeningHours

STATUS_BUKA = "buka"
STATUS_TUTUP = "tutup"
STATUS_TIDAK_DIKETAHUI = "tidak diketahui"


def _tag_kosong(tag):
    if tag is None:
        return True
    if isinstance(tag, float) and math.isnan(tag):
        return True
    return str(tag).strip() == ""


def cek_buka(tag, waktu):
    """Kembalikan status klinik pada waktu tertentu (datetime)."""
    if _tag_kosong(tag):
        return STATUS_TIDAK_DIKETAHUI
    try:
        jadwal = OpeningHours(str(tag).strip())
    except Exception:
        return STATUS_TIDAK_DIKETAHUI
    return STATUS_BUKA if jadwal.is_open(waktu) else STATUS_TUTUP


def tambah_status_buka(klinik, waktu, kolom_jadwal="Jadwal_Operasional"):
    """Tambahkan kolom 'status_buka' untuk setiap klinik pada waktu pencarian."""
    if not isinstance(waktu, datetime):
        raise TypeError("waktu harus berupa datetime, misalnya datetime(2026, 10, 31, 21, 0)")
    hasil = klinik.copy()
    hasil["status_buka"] = [cek_buka(t, waktu) for t in hasil[kolom_jadwal]]
    return hasil


def hanya_yang_buka(klinik, waktu, kolom_jadwal="Jadwal_Operasional"):
    """Ambil klinik yang status_buka-nya 'buka' pada waktu pencarian."""
    hasil = tambah_status_buka(klinik, waktu, kolom_jadwal)
    return hasil[hasil["status_buka"] == STATUS_BUKA].reset_index(drop=True)