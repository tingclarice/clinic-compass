import geopandas as gpd
import pytest
from shapely.geometry import Point
from src.spatial import klinik_dalam_radius, cari_dengan_perluasan, muat_klinik, CRS_METER

def test_data_kosong_mengembalikan_kosong():
    kosong = gpd.GeoDataFrame({"nama": []}, geometry=[], crs=CRS_METER)
    hasil = klinik_dalam_radius(kosong, (0, 0), 3000)
    assert len(hasil) == 0

def test_crs_belum_ditetapkan_ditolak():
    tanpa_crs = gpd.GeoDataFrame({"nama": ["A"]}, geometry=[Point(0, 0)])
    with pytest.raises(ValueError):
        klinik_dalam_radius(tanpa_crs, (0, 0), 3000)

def test_geometri_kosong_tidak_menyebabkan_error():
    klinik = gpd.GeoDataFrame({"nama": ["A", "B"]},
        geometry=[Point(0, 0), None], crs=CRS_METER)
    hasil = klinik_dalam_radius(klinik, (0, 0), 3000)
    assert hasil["nama"].tolist() == ["A"]

def test_cari_dengan_perluasan_data_kosong():
    kosong = gpd.GeoDataFrame({"nama": []}, geometry=[], crs=CRS_METER)
    assert len(cari_dengan_perluasan(kosong, (0, 0))) == 0

def test_muat_klinik_csv_tanpa_kolom_koordinat(tmp_path):
    csv = tmp_path / "x.csv"
    csv.write_text("nama,lon,lat\nA,112.7,-7.3\n")
    with pytest.raises(KeyError):
        muat_klinik(str(csv))