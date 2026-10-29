import os
import pytest
import itertools
import pytest
import geopandas as gpd
from src.spatial import muat_klinik, muat_wilayah, tandai_wilayah

ADA_DATA = os.path.exists("data/processed/klinik_surabaya_barat.geojson") 

KLINIK = "data/processed/klinik_surabaya_barat.geojson"
WILAYAH = "data/processed/batas_surabaya_barat.geojson"

def test_jumlah_klinik_tetap():
    klinik = tandai_wilayah(muat_klinik(KLINIK), muat_wilayah(WILAYAH))
    assert len(klinik) == 93

def test_satu_baris_per_klinik():
    klinik = tandai_wilayah(muat_klinik(KLINIK), muat_wilayah(WILAYAH))
    assert klinik.index.is_unique

@pytest.mark.xfail(reason="batas Pakal dan Benowo tumpang tindih sekitar 2,06 km2, menunggu perbaikan data tim A")
def test_batas_tidak_tumpang_tindih():
    w = muat_wilayah(WILAYAH)
    for i, j in itertools.combinations(w.index, 2):
        assert w.geometry[i].intersection(w.geometry[j]).area < 1.0