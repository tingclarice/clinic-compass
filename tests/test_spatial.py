import geopandas as gpd
from shapely.geometry import Point
from src.spatial import klinik_dalam_radius, cari_dengan_perluasan, CRS_METER

klinik = gpd.GeoDataFrame(
    {"nama": ["A", "B", "C"], "layanan": ["Dokter Umum", "Dokter Gigi", "Dokter Anak"]},
    geometry=[Point(0, 0), Point(2000, 0), Point(4000, 0)],
    crs=CRS_METER,
)

def test_radius_3km():
    hasil = klinik_dalam_radius(klinik, (0, 0), 3000)
    assert hasil["nama"].tolist() == ["A", "B"]

def test_jarak_urut():
    hasil = klinik_dalam_radius(klinik, (0, 0), 3000)
    assert hasil["jarak_garis_lurus"].tolist() == [0.0, 2000.0]

def test_perluasan_radius():
    jauh = gpd.GeoDataFrame({"nama": ["C"]}, geometry=[Point(4500, 0)], crs=CRS_METER)
    hasil = cari_dengan_perluasan(jauh, (0, 0), 3000, 5000)
    assert hasil["nama"].tolist() == ["C"]

def test_tanpa_hasil():
    hasil = cari_dengan_perluasan(klinik, (100000, 0), 3000, 5000)
    assert len(hasil) == 0