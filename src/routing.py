"""Road-network routing for Clinic Compass."""

import ast
import math
from bisect import bisect_right
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


def _edge_data(graph, start, end):
    """Return the attributes of the shortest edge between two nodes."""
    edge_data = graph.get_edge_data(start, end)
    if graph.is_multigraph():
        edge_data = min(
            edge_data.values(), key=lambda data: data.get("length", float("inf"))
        )
    return edge_data


def _edge_coordinates(graph, start, end, edge_data):
    """Return edge coordinates ordered from the start node to the end node."""
    geometry = edge_data.get("geometry")
    start_xy = (graph.nodes[start]["x"], graph.nodes[start]["y"])
    if geometry is None:
        return [start_xy, (graph.nodes[end]["x"], graph.nodes[end]["y"])]
    coordinates = list(geometry.coords)
    if Point(coordinates[-1]).distance(Point(start_xy)) < Point(coordinates[0]).distance(
        Point(start_xy)
    ):
        coordinates.reverse()
    return coordinates


def _street_name(edge_data):
    """Readable street name of an edge; OSM may store several names as a list."""
    name = edge_data.get("name")
    if isinstance(name, str) and name.startswith("["):
        try:
            name = ast.literal_eval(name)
        except (ValueError, SyntaxError):
            pass
    if isinstance(name, (list, tuple)):
        name = next((str(item) for item in name if str(item).strip()), None)
    if name is None or (isinstance(name, float) and math.isnan(name)) or not str(name).strip():
        return "jalan tanpa nama"
    return str(name).strip()


def _bearing(start, end):
    """Compass bearing in degrees (0 = north, 90 = east) from start to end."""
    return math.degrees(math.atan2(end[0] - start[0], end[1] - start[1])) % 360


def _turn_angle(bearing_in, bearing_out):
    """Signed change of heading in degrees: positive turns right, negative turns left."""
    return (bearing_out - bearing_in + 540) % 360 - 180


def _turn_instruction(angle):
    """Indonesian turn instruction and arrow symbol for a heading change."""
    size = abs(angle)
    side = "kanan" if angle > 0 else "kiri"
    if size < 20:
        return "Lurus", "⬆"
    if size < 45:
        return f"Serong {side}", "↗" if angle > 0 else "↖"
    if size < 150:
        return f"Belok {side}", "➡" if angle > 0 else "⬅"
    return "Putar balik", "↩"


def route_steps(graph, road_path, start_connector_m=0.0, end_connector_m=0.0,
                destination_name="klinik", turn_threshold=45, min_segment_m=15):
    """Turn-by-turn guidance for a road path found by Dijkstra.

    Consecutive edges on the same street without a sharp turn are merged into
    one segment. Each step stores its instruction, the distance travelled in
    that step (metres), the arrow symbol, the point where the step starts
    (graph CRS) and ``offset_m``: how far along the route_clinics() route
    geometry the step starts. Offsets use geometry lengths rather than the OSM
    ``length`` attribute so they can be compared with ``route.project()``.
    """
    segments = []
    for start, end in zip(road_path, road_path[1:]):
        edge_data = _edge_data(graph, start, end)
        coordinates = _edge_coordinates(graph, start, end, edge_data)
        if len(coordinates) < 2:
            continue
        name = _street_name(edge_data)
        geometry_length = LineString(coordinates).length
        length = float(edge_data.get("length", geometry_length))
        bearing_in = _bearing(coordinates[0], coordinates[1])
        bearing_out = _bearing(coordinates[-2], coordinates[-1])
        if segments:
            previous = segments[-1]
            angle = _turn_angle(previous["bearing_out"], bearing_in)
            if previous["name"] == name and abs(angle) < turn_threshold:
                previous["length"] += length
                previous["geometry_length"] += geometry_length
                previous["bearing_out"] = bearing_out
                continue
        segments.append({
            "name": name,
            "length": length,
            "geometry_length": geometry_length,
            "bearing_in": bearing_in,
            "bearing_out": bearing_out,
            "point": coordinates[0],
        })

    merged = []
    for segment in segments:
        if merged and segment["length"] < min_segment_m:
            merged[-1]["length"] += segment["length"]
            merged[-1]["geometry_length"] += segment["geometry_length"]
            merged[-1]["bearing_out"] = segment["bearing_out"]
        else:
            merged.append(segment)

    steps = []
    offset = start_connector_m
    if merged:
        first = merged[0]
        steps.append({
            "instruction": f"Menuju {first['name']}",
            "distance_m": round(start_connector_m, 1),
            "symbol": "📍",
            "point": None,
            "offset_m": 0.0,
        })
        steps.append({
            "instruction": f"Ikuti {first['name']}",
            "distance_m": round(first["length"], 1),
            "symbol": "⬆",
            "point": first["point"],
            "offset_m": offset,
        })
        offset += first["geometry_length"]
        for previous, segment in zip(merged, merged[1:]):
            action, symbol = _turn_instruction(
                _turn_angle(previous["bearing_out"], segment["bearing_in"])
            )
            steps.append({
                "instruction": f"{action} ke {segment['name']}",
                "distance_m": round(segment["length"], 1),
                "symbol": symbol,
                "point": segment["point"],
                "offset_m": offset,
            })
            offset += segment["geometry_length"]
    steps.append({
        "instruction": f"Tiba di {destination_name}",
        "distance_m": round(end_connector_m, 1),
        "symbol": "🏁",
        "point": None,
        "offset_m": offset,
    })
    return steps


def navigation_state(route, steps, position, arrive_m=15, off_route_m=30):
    """Live turn-by-turn state for a user on a selected clinic route.

    ``route`` is the route_clinics() LineString, which starts at the search
    location; ``steps`` are its route_steps() guidance and ``position`` must
    use the route's CRS. The active step is the one being travelled: it moves
    to the next step as soon as the user passes that step's starting point.
    The next instruction is the manoeuvre that ends the active step. Arriving
    is the final manoeuvre, so its distance is the remaining route distance.
    Off route, no step is active.
    """
    if not isinstance(route, LineString):
        raise TypeError("route must be a Shapely LineString.")
    if not isinstance(position, Point):
        raise TypeError("position must be a Shapely Point.")
    if not steps or any("offset_m" not in step for step in steps):
        raise ValueError("steps must be route_steps() output with offsets.")

    distance_from_route = route.distance(position)
    state = {
        "active_index": None,
        "next_index": None,
        "then_index": None,
        "distance_to_next_m": None,
        "remaining_m": None,
        "arrived": False,
        "off_route": distance_from_route > off_route_m,
        "distance_from_route_m": round(distance_from_route, 1),
    }
    if state["off_route"]:
        return state

    progress = route.project(position)
    remaining = max(route.length - progress, 0.0)
    last = len(steps) - 1
    state["remaining_m"] = round(remaining, 1)
    if remaining < arrive_m:
        state.update(active_index=last, arrived=True)
        return state

    offsets = [step["offset_m"] for step in steps]
    active = max(bisect_right(offsets, progress) - 1, 0)
    next_index = min(active + 1, last)
    to_next = remaining if next_index == last else offsets[next_index] - progress
    state.update(
        active_index=active,
        next_index=next_index,
        then_index=next_index + 1 if next_index < last else None,
        distance_to_next_m=round(to_next, 1),
    )
    return state


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
    result["langkah_rute"] = None
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
    steps_by_clinic = {}
    for index, row in clinic_points.iterrows():
        clinic_point = row.geometry
        destination_node = ox.distance.nearest_nodes(
            graph, X=clinic_point.x, Y=clinic_point.y
        )
        if destination_node not in distances:
            continue

        road_path = paths[destination_node]
        start_connector = user_point.distance(
            Point(graph.nodes[origin_node]["x"], graph.nodes[origin_node]["y"])
        )
        end_connector = clinic_point.distance(
            Point(graph.nodes[destination_node]["x"], graph.nodes[destination_node]["y"])
        )
        total_distance = distances[destination_node] + start_connector + end_connector
        origin_point = Point(
            graph.nodes[origin_node]["x"], graph.nodes[origin_node]["y"]
        )
        destination_point = Point(
            graph.nodes[destination_node]["x"], graph.nodes[destination_node]["y"]
        )
        route_coordinates = [(user_point.x, user_point.y), (origin_point.x, origin_point.y)]
        for start, end in zip(road_path, road_path[1:]):
            segment = _edge_coordinates(graph, start, end, _edge_data(graph, start, end))
            route_coordinates.extend(segment[1:])
        route_coordinates.extend(
            [(destination_point.x, destination_point.y), (clinic_point.x, clinic_point.y)]
        )
        route = LineString(route_coordinates)
        result.at[index, "jarak_rute_m"] = round(total_distance, 1)
        result.at[index, "rute"] = route
        destination_name = next(
            (str(row[column]) for column in ("Nama_Klinik", "name")
             if column in row.index and str(row[column]).strip()),
            "klinik",
        )
        steps_by_clinic[index] = route_steps(
            graph, road_path, start_connector, end_connector, destination_name
        )
        reachable.append(index)

    result["langkah_rute"] = [steps_by_clinic.get(index) for index in result.index]
    result = result.loc[reachable].copy()
    result["jarak_rute_m"] = result["jarak_rute_m"].astype(float)
    return result.sort_values("jarak_rute_m").reset_index(drop=True)
