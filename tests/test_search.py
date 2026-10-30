from datetime import datetime

import geopandas as gpd
import networkx as nx
from shapely.geometry import Point

from src.search import search_clinics

CRS = "EPSG:32749"


def _graph():
    graph = nx.MultiDiGraph(crs=CRS)
    graph.add_node(1, x=0, y=0)
    graph.add_node(2, x=1000, y=0)
    graph.add_node(3, x=4500, y=0)
    graph.add_edge(1, 2, length=1000)
    graph.add_edge(2, 1, length=1000)
    graph.add_edge(2, 3, length=3500)
    graph.add_edge(3, 2, length=3500)
    return graph


def _clinics():
    return gpd.GeoDataFrame(
        {
            "Nama_Klinik": ["Tutups", "Jadwal belum diketahui", "Buka jauh"],
            "Jenis_Layanan": ["Dokter umum", "Dokter umum", "Dokter umum"],
            "Jadwal_Operasional": [
                "Mo-Su 00:00-01:00",
                "",
                "Mo-Su 09:00-17:00",
            ],
        },
        geometry=[Point(1000, 0), Point(1500, 0), Point(4500, 0)],
        crs=CRS,
    )


def test_expands_when_initial_radius_has_no_verified_open_match():
    result = search_clinics(
        clinics=_clinics(),
        graph=_graph(),
        user_location=Point(0, 0),
        search_time=datetime(2026, 10, 26, 10, 0),
        service="Dokter umum",
        radius_m=3000,
        max_radius_m=5000,
    )

    assert result.expanded is True
    assert result.radius_used_m == 5000
    assert result.clinics["Nama_Klinik"].tolist() == [
        "Tutups",
        "Jadwal belum diketahui",
        "Buka jauh",
    ]
    assert result.clinics["status_buka"].tolist() == [
        "tutup",
        "tidak diketahui",
        "buka",
    ]
    assert result.verified_open == 1
    assert result.clinics_in_radius == 3
    assert result.service_matches == 3
    assert result.unknown_hours == 1
    assert result.closed_clinics == 1


def test_filters_by_selected_service():
    clinics = _clinics()
    clinics.loc[2, "Jenis_Layanan"] = "Dokter gigi"

    result = search_clinics(
        clinics=clinics,
        graph=_graph(),
        user_location=Point(0, 0),
        search_time=datetime(2026, 10, 26, 10, 0),
        service="Dokter gigi",
        radius_m=5000,
        max_radius_m=5000,
    )

    assert result.clinics["Nama_Klinik"].tolist() == ["Buka jauh"]
    assert result.clinics["status_buka"].tolist() == ["buka"]
    assert result.verified_open == 1
    assert result.service_matches == 1
    assert result.unknown_hours == 0
    assert result.closed_clinics == 0


def test_unknown_hours_are_not_treated_as_open():
    clinics = _clinics().iloc[[1]].copy()
    result = search_clinics(
        clinics=clinics,
        graph=_graph(),
        user_location=Point(0, 0),
        search_time=datetime(2026, 10, 26, 10, 0),
        radius_m=3000,
        max_radius_m=3000,
    )

    assert result.clinics["Nama_Klinik"].tolist() == ["Jadwal belum diketahui"]
    assert result.clinics["status_buka"].tolist() == ["tidak diketahui"]
    assert result.verified_open == 0
    assert result.unknown_hours == 1
