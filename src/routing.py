"""Road-network routing for Clinic Compass."""

from pathlib import Path

import geopandas as gpd
import networkx as nx
import osmnx as ox
from shapely.geometry import LineString, Point

from src.lokasi import ARAH_PANAH, geser
from src.spatial import CRS_METER

ROOT = Path(__file__).resolve().parents[1]
ROAD_GRAPH_CACHE = ROOT / ".cache" / "west_surabaya_drive.graphml"


def snap_to_nearest_road(graph, position, position_crs=CRS_METER):
    """Snap a point to the nearest road edge and return it in its original CRS."""
    if not isinstance(position, Point):
        raise TypeError("position must be a Shapely Point.")
    graph_crs = graph.graph.get("crs")
    if graph_crs is None:
        raise ValueError("Road graph CRS is missing.")

    projected_position = gpd.GeoSeries([position], crs=position_crs).to_crs(
        graph_crs
    ).iloc[0]
    edge_id = ox.distance.nearest_edges(
        graph, X=projected_position.x, Y=projected_position.y
    )
    edge_data = graph.get_edge_data(*edge_id)
    geometry = edge_data.get("geometry")
    if geometry is None:
        start = graph.nodes[edge_id[0]]
        end = graph.nodes[edge_id[1]]
        geometry = LineString([(start["x"], start["y"]), (end["x"], end["y"])])

    snapped_position = geometry.interpolate(geometry.project(projected_position))
    return gpd.GeoSeries([snapped_position], crs=graph_crs).to_crs(
        position_crs
    ).iloc[0]


def move_to_reachable_road(
    graph,
    movement_graph,
    position,
    direction,
    step_m=50,
    max_travel_m=75,
    position_crs=CRS_METER,
):
    """Move one step only when the snapped destination is locally road-reachable."""
    if not isinstance(position, Point):
        raise TypeError("position must be a Shapely Point.")
    if direction not in ARAH_PANAH:
        raise ValueError(f"Unknown direction: {direction}.")
    if step_m <= 0 or max_travel_m <= 0:
        raise ValueError("Movement distances must be positive.")
    graph_crs = graph.graph.get("crs")
    if graph_crs is None:
        raise ValueError("Road graph CRS is missing.")

    projected_position = gpd.GeoSeries([position], crs=position_crs).to_crs(
        graph_crs
    ).iloc[0]
    target_position = gpd.GeoSeries(
        [geser(position, direction, step_m)], crs=position_crs
    ).to_crs(graph_crs).iloc[0]

    def nearest_edge_projection(point):
        edge_id = ox.distance.nearest_edges(graph, X=point.x, Y=point.y)
        edge_data = graph.get_edge_data(*edge_id)
        geometry = edge_data.get("geometry")
        if geometry is None:
            start = graph.nodes[edge_id[0]]
            end = graph.nodes[edge_id[1]]
            geometry = LineString([(start["x"], start["y"]), (end["x"], end["y"])])
        else:
            start = graph.nodes[edge_id[0]]
            start_point = Point(start["x"], start["y"])
            if Point(geometry.coords[-1]).distance(start_point) < Point(
                geometry.coords[0]
            ).distance(start_point):
                geometry = LineString(list(geometry.coords)[::-1])
        distance_along = geometry.project(point)
        snapped = geometry.interpolate(distance_along)
        edge_length = float(edge_data.get("length", geometry.length))
        if geometry.length == 0:
            raise ValueError("Road graph contains a zero-length edge.")
        distance_to_start = edge_length * distance_along / geometry.length
        return (
            snapped,
            edge_id,
            edge_length,
            distance_to_start,
            point.distance(snapped),
        )

    current_snap = nearest_edge_projection(projected_position)
    target_snap = nearest_edge_projection(target_position)
    current_point, current_edge, current_length, current_offset, current_gap = current_snap
    target_point, target_edge, target_length, target_offset, target_gap = target_snap

    dx, dy = ARAH_PANAH[direction]
    if (target_point.x - current_point.x) * dx + (
        target_point.y - current_point.y
    ) * dy <= 0:
        return None

    current_endpoints = (
        (current_edge[0], current_offset),
        (current_edge[1], current_length - current_offset),
    )
    target_endpoints = (
        (target_edge[0], target_offset),
        (target_edge[1], target_length - target_offset),
    )
    shortest_travel = float("inf")
    if set(current_edge[:2]) == set(target_edge[:2]):
        canonical_node = current_edge[0]
        current_distance = (
            current_offset
            if current_edge[0] == canonical_node
            else current_length - current_offset
        )
        target_distance = (
            target_offset
            if target_edge[0] == canonical_node
            else target_length - target_offset
        )
        shortest_travel = current_gap + abs(
            current_distance - target_distance
        ) + target_gap

    for current_node, current_offset_to_node in current_endpoints:
        for target_node, target_offset_to_node in target_endpoints:
            try:
                network_distance = nx.shortest_path_length(
                    movement_graph,
                    source=current_node,
                    target=target_node,
                    weight="length",
                )
            except nx.NetworkXNoPath:
                continue
            shortest_travel = min(
                shortest_travel,
                current_gap
                + current_offset_to_node
                + network_distance
                + target_offset_to_node
                + target_gap,
            )

    if shortest_travel > max_travel_m:
        return None

    return gpd.GeoSeries([target_point], crs=graph_crs).to_crs(
        position_crs
    ).iloc[0]


def move_along_route(
    route,
    position,
    direction,
    route_crs,
    step_m=50,
    position_crs=CRS_METER,
):
    """Move a point up to one step along a displayed route in the chosen direction."""
    if not isinstance(route, LineString):
        raise TypeError("route must be a Shapely LineString.")
    if not isinstance(position, Point):
        raise TypeError("position must be a Shapely Point.")
    if direction not in ARAH_PANAH:
        raise ValueError(f"Unknown direction: {direction}.")
    if step_m <= 0:
        raise ValueError("step_m must be positive.")
    if route.is_empty or route.length == 0:
        raise ValueError("route must have non-zero length.")

    projected_position = gpd.GeoSeries([position], crs=position_crs).to_crs(
        route_crs
    ).iloc[0]
    current_measure = route.project(projected_position)
    current_point = route.interpolate(current_measure)
    candidates = []

    for measure in (
        max(0, current_measure - step_m),
        min(route.length, current_measure + step_m),
    ):
        if measure == current_measure:
            continue
        candidate = route.interpolate(measure)
        dx, dy = ARAH_PANAH[direction]
        directional_progress = (
            (candidate.x - current_point.x) * dx
            + (candidate.y - current_point.y) * dy
        )
        if directional_progress > 0:
            candidates.append((directional_progress, candidate))

    if not candidates:
        return None

    _, next_point = max(candidates, key=lambda candidate: candidate[0])
    return gpd.GeoSeries([next_point], crs=route_crs).to_crs(
        position_crs
    ).iloc[0]


def move_along_routes(
    routes,
    position,
    direction,
    route_crs,
    step_m=50,
    position_crs=CRS_METER,
):
    """Choose the most direction-aligned move among all displayed routes."""
    routes = list(routes)
    if not routes:
        raise ValueError("At least one route is required.")

    dx, dy = ARAH_PANAH[direction] if direction in ARAH_PANAH else (0, 0)
    if not (dx or dy):
        raise ValueError(f"Unknown direction: {direction}.")

    candidates = []
    for route in routes:
        moved = move_along_route(
            route,
            position,
            direction,
            route_crs=route_crs,
            step_m=step_m,
            position_crs=position_crs,
        )
        if moved is None:
            continue
        movement = gpd.GeoSeries(
            [moved, position], crs=position_crs
        ).to_crs(route_crs)
        candidate, current = movement.iloc[0], movement.iloc[1]
        directional_progress = (
            (candidate.x - current.x) * dx + (candidate.y - current.y) * dy
        )
        candidates.append((directional_progress, moved))

    if not candidates:
        return None

    return max(candidates, key=lambda candidate: candidate[0])[1]


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
