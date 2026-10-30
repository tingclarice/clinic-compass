"""Road-network routing for Clinic Compass."""

from pathlib import Path

import geopandas as gpd
import networkx as nx
import osmnx as ox
from shapely.geometry import LineString, Point

ROOT = Path(__file__).resolve().parents[1]
ROAD_GRAPH_CACHE = ROOT / ".cache" / "west_surabaya_drive.graphml"


def load_road_graph(boundaries, cache_path=ROAD_GRAPH_CACHE):
    """Load a cached OSM drive graph or download and cache one for the study area."""
    cache_path = Path(cache_path)
    if cache_path.exists():
        return ox.load_graphml(filepath=cache_path)

    if boundaries.crs is None:
        raise ValueError("Boundary CRS is required to download the road network.")

    polygon = (
        boundaries.to_crs("EPSG:32749")
        .geometry.union_all()
        .buffer(5000)
    )
    polygon = gpd.GeoSeries([polygon], crs="EPSG:32749").to_crs("EPSG:4326").iloc[0]
    graph = ox.graph_from_polygon(
        polygon,
        network_type="drive",
        simplify=True,
        retain_all=True,
    )
    graph = ox.project_graph(graph)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(graph, filepath=cache_path)
    return graph


def route_clinics(graph, user_location, clinics):
    """Rank clinic candidates by shortest drivable distance from the user.

    Distances include the straight-line connectors from the user's location and
    each clinic to its nearest road node. Unreachable clinics are omitted.
    """
    graph_crs = graph.graph.get("crs")
    if graph_crs is None:
        raise ValueError("Road graph CRS is missing.")
    if not any("length" in data for _, _, data in graph.edges(data=True)):
        raise ValueError("Road graph edges must include length weights.")
    if clinics.crs is None:
        raise ValueError("Clinic CRS is required for routing.")
    if not isinstance(user_location, Point):
        raise TypeError("user_location must be a Shapely Point.")

    result = clinics.copy()
    result["jarak_rute_m"] = None
    result["rute"] = None
    if result.empty:
        return result

    clinic_points = result.to_crs(graph_crs)
    user_point = gpd.GeoSeries([user_location], crs=clinics.crs).to_crs(graph_crs).iloc[0]
    origin_node = ox.distance.nearest_nodes(
        graph, X=user_point.x, Y=user_point.y
    )
    distances, paths = nx.single_source_dijkstra(
        graph, origin_node, weight="length"
    )

    reachable = []
    for index, row in clinic_points.iterrows():
        clinic_point = row.geometry
        destination_node = ox.distance.nearest_nodes(
            graph, X=clinic_point.x, Y=clinic_point.y
        )
        if destination_node not in distances:
            continue

        road_path = paths[destination_node]
        snap_distance = user_point.distance(
            Point(graph.nodes[origin_node]["x"], graph.nodes[origin_node]["y"])
        ) + clinic_point.distance(
            Point(graph.nodes[destination_node]["x"], graph.nodes[destination_node]["y"])
        )
        total_distance = distances[destination_node] + snap_distance
        origin_point = Point(
            graph.nodes[origin_node]["x"], graph.nodes[origin_node]["y"]
        )
        destination_point = Point(
            graph.nodes[destination_node]["x"], graph.nodes[destination_node]["y"]
        )
        route_coordinates = [(user_point.x, user_point.y), (origin_point.x, origin_point.y)]
        for start, end in zip(road_path, road_path[1:]):
            edge_data = graph.get_edge_data(start, end)
            if graph.is_multigraph():
                edge_data = min(
                    edge_data.values(), key=lambda data: data.get("length", float("inf"))
                )
            geometry = edge_data.get("geometry")
            if geometry is None:
                segment = [
                    (graph.nodes[start]["x"], graph.nodes[start]["y"]),
                    (graph.nodes[end]["x"], graph.nodes[end]["y"]),
                ]
            else:
                segment = list(geometry.coords)
                start_xy = (graph.nodes[start]["x"], graph.nodes[start]["y"])
                if Point(segment[-1]).distance(Point(start_xy)) < Point(segment[0]).distance(Point(start_xy)):
                    segment.reverse()
            route_coordinates.extend(segment[1:])
        route_coordinates.extend(
            [(destination_point.x, destination_point.y), (clinic_point.x, clinic_point.y)]
        )
        route = LineString(route_coordinates)
        result.at[index, "jarak_rute_m"] = round(total_distance, 1)
        result.at[index, "rute"] = route
        reachable.append(index)

    result = result.loc[reachable].copy()
    result["jarak_rute_m"] = result["jarak_rute_m"].astype(float)
    return result.sort_values("jarak_rute_m").reset_index(drop=True)
