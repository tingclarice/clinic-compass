import geopandas as gpd
import networkx as nx
import pytest
from shapely.geometry import Point
from shapely.geometry import LineString

from src.routing import route_clinics

CRS = "EPSG:32749"


@pytest.fixture
def road_graph():
    graph = nx.MultiDiGraph(crs=CRS)
    graph.add_node(1, x=0, y=0)
    graph.add_node(2, x=1000, y=0)
    graph.add_node(3, x=2000, y=0)
    graph.add_node(4, x=1000, y=1000)
    graph.add_node(5, x=2000, y=1000)
    graph.add_edge(1, 2, length=1000)
    graph.add_edge(2, 3, length=1000)
    graph.add_edge(1, 4, length=1200)
    graph.add_edge(4, 5, length=1200)
    return graph


def test_routes_and_sorts_by_shortest_road_distance(road_graph):
    clinics = gpd.GeoDataFrame(
        {"name": ["via-short-road", "via-long-road"]},
        geometry=[Point(2000, 0), Point(2000, 1000)],
        crs=CRS,
    )

    result = route_clinics(road_graph, Point(0, 0), clinics)

    assert result["name"].tolist() == ["via-short-road", "via-long-road"]
    assert result["jarak_rute_m"].tolist() == [2000.0, 2400.0]
    assert result["rute"].iloc[0].geom_type == "LineString"


def test_route_geometry_follows_street_edge_geometry(road_graph):
    road_graph[1][2][0]["geometry"] = LineString(
        [(0, 0), (500, 300), (1000, 0)]
    )
    clinics = gpd.GeoDataFrame(
        {"name": ["clinic"]},
        geometry=[Point(2000, 0)],
        crs=CRS,
    )

    route = route_clinics(road_graph, Point(0, 0), clinics)["rute"].iloc[0]

    assert (500, 300) in list(route.coords)


def test_omits_clinic_disconnected_from_road_graph(road_graph):
    road_graph.add_node(6, x=5000, y=5000)
    clinics = gpd.GeoDataFrame(
        {"name": ["connected", "disconnected"]},
        geometry=[Point(2000, 0), Point(5000, 5000)],
        crs=CRS,
    )

    result = route_clinics(road_graph, Point(0, 0), clinics)

    assert result["name"].tolist() == ["connected"]


def test_empty_candidates_returns_empty_with_route_columns(road_graph):
    clinics = gpd.GeoDataFrame(
        {"name": []}, geometry=gpd.GeoSeries([], crs=CRS), crs=CRS
    )

    result = route_clinics(road_graph, Point(0, 0), clinics)

    assert result.empty
    assert {"jarak_rute_m", "rute"}.issubset(result.columns)


def test_rejects_graph_without_crs():
    graph = nx.MultiDiGraph()
    with pytest.raises(ValueError, match="CRS"):
        route_clinics(graph, Point(0, 0), gpd.GeoDataFrame())
