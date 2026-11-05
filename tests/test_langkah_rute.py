import geopandas as gpd
import networkx as nx
import pytest
from shapely.geometry import LineString, Point

from src.app import _navigation_banner_html, _route_guide_html
from src.routing import navigation_state, route_clinics, route_steps

CRS = "EPSG:32749"


@pytest.fixture
def street_grid():
    """Jalan A ke timur (2 ruas, 300 m), lalu Jalan B ke utara (200 m), lalu Jalan C ke timur (100 m)."""
    graph = nx.MultiDiGraph(crs=CRS)
    for node, (x, y) in {1: (0, 0), 2: (150, 0), 3: (300, 0), 4: (300, 200), 5: (400, 200)}.items():
        graph.add_node(node, x=x, y=y)
    graph.add_edge(1, 2, length=150, name="Jalan A")
    graph.add_edge(2, 3, length=150, name="Jalan A")
    graph.add_edge(3, 4, length=200, name="Jalan B")
    graph.add_edge(4, 5, length=100, name="Jalan C")
    return graph


def test_steps_merge_same_street_and_detect_turns(street_grid):
    steps = route_steps(street_grid, [1, 2, 3, 4, 5], 40, 25, "Klinik Uji")

    assert [s["instruction"] for s in steps] == [
        "Menuju Jalan A",
        "Ikuti Jalan A",
        "Belok kiri ke Jalan B",
        "Belok kanan ke Jalan C",
        "Tiba di Klinik Uji",
    ]
    assert [s["distance_m"] for s in steps] == [40, 300, 200, 100, 25]


def test_step_distances_add_up_to_route_distance(street_grid):
    clinics = gpd.GeoDataFrame({"Nama_Klinik": ["Klinik Uji"]}, geometry=[Point(400, 220)], crs=CRS)

    result = route_clinics(street_grid, Point(0, -30), clinics)
    steps = result["langkah_rute"].iloc[0]

    assert sum(s["distance_m"] for s in steps) == pytest.approx(result["jarak_rute_m"].iloc[0], abs=0.2)
    assert steps[-1]["instruction"] == "Tiba di Klinik Uji"


def test_same_street_with_sharp_turn_is_a_new_step():
    graph = nx.MultiDiGraph(crs=CRS)
    graph.add_node(1, x=0, y=0)
    graph.add_node(2, x=0, y=200)
    graph.add_node(3, x=-200, y=200)
    graph.add_edge(1, 2, length=200, name="Jalan A")
    graph.add_edge(2, 3, length=200, name="Jalan A")

    steps = route_steps(graph, [1, 2, 3])

    assert steps[2]["instruction"] == "Belok kiri ke Jalan A"


def test_gentle_curve_on_same_street_is_one_step():
    graph = nx.MultiDiGraph(crs=CRS)
    graph.add_node(1, x=0, y=0)
    graph.add_node(2, x=100, y=0)
    graph.add_node(3, x=200, y=30)
    graph.add_edge(1, 2, length=100, name="Jalan A")
    graph.add_edge(2, 3, length=104, name="Jalan A")

    steps = route_steps(graph, [1, 2, 3])

    assert [s["instruction"] for s in steps[1:-1]] == ["Ikuti Jalan A"]
    assert steps[1]["distance_m"] == 204


def test_street_name_lists_and_missing_names():
    graph = nx.MultiDiGraph(crs=CRS)
    graph.add_node(1, x=0, y=0)
    graph.add_node(2, x=100, y=0)
    graph.add_node(3, x=100, y=-100)
    graph.add_edge(1, 2, length=100, name="['Jalan Raya Lontar', 'Jalan Lontar']")
    graph.add_edge(2, 3, length=100)

    steps = route_steps(graph, [1, 2, 3])

    assert steps[1]["instruction"] == "Ikuti Jalan Raya Lontar"
    assert steps[2]["instruction"] == "Belok kanan ke jalan tanpa nama"


def test_turn_direction_uses_curved_edge_geometry():
    graph = nx.MultiDiGraph(crs=CRS)
    graph.add_node(1, x=0, y=0)
    graph.add_node(2, x=100, y=100)
    graph.add_node(3, x=200, y=100)
    graph.add_edge(1, 2, length=150, name="Jalan A",
                   geometry=LineString([(0, 0), (0, 100), (100, 100)]))
    graph.add_edge(2, 3, length=100, name="Jalan B")

    steps = route_steps(graph, [1, 2, 3])

    assert steps[2]["instruction"] == "Lurus ke Jalan B"


@pytest.fixture
def navigasi(street_grid):
    """Rute dari (0, -30) ke Klinik Uji di (400, 220): 30 + 300 + 200 + 100 + 20 = 650 m."""
    clinics = gpd.GeoDataFrame({"Nama_Klinik": ["Klinik Uji"]}, geometry=[Point(400, 220)], crs=CRS)
    result = route_clinics(street_grid, Point(0, -30), clinics)
    return result["rute"].iloc[0], result["langkah_rute"].iloc[0]


def test_step_offsets_follow_route_geometry(navigasi):
    route, steps = navigasi

    assert [s["offset_m"] for s in steps] == pytest.approx([0, 30, 330, 530, 630])
    for step in steps:
        if step["point"] is not None:
            assert route.project(Point(step["point"])) == pytest.approx(step["offset_m"])


@pytest.mark.parametrize(
    "position, active, upcoming, then, to_next, remaining",
    [
        # di awal rute (lokasi pencarian), belum masuk Jalan A
        ((0, -30), 0, "Ikuti Jalan A", "Belok kiri ke Jalan B", 30, 650),
        # di tengah Jalan A
        ((100, 0), 1, "Belok kiri ke Jalan B", "Belok kanan ke Jalan C", 200, 520),
        # 1 m sebelum belokan ke Jalan B: masih di langkah Jalan A
        ((299, 0), 1, "Belok kiri ke Jalan B", "Belok kanan ke Jalan C", 1, 321),
        # 1 m setelah melewati belokan: langkah aktif pindah ke Jalan B
        ((300, 1), 2, "Belok kanan ke Jalan C", "Tiba di Klinik Uji", 199, 319),
        # di jalan terakhir: instruksi berikutnya tiba, jaraknya = sisa rute
        ((350, 200), 3, "Tiba di Klinik Uji", None, 70, 70),
        # di penghubung ke klinik, belum cukup dekat untuk dianggap tiba
        ((400, 202), 4, "Tiba di Klinik Uji", None, 18, 18),
    ],
)
def test_navigation_state_follows_position(navigasi, position, active, upcoming, then, to_next, remaining):
    route, steps = navigasi

    state = navigation_state(route, steps, Point(position))

    assert state["active_index"] == active
    assert steps[state["next_index"]]["instruction"] == upcoming
    assert (steps[state["then_index"]]["instruction"] if state["then_index"] is not None else None) == then
    assert state["distance_to_next_m"] == pytest.approx(to_next)
    assert state["remaining_m"] == pytest.approx(remaining)
    assert not state["arrived"] and not state["off_route"]


def test_navigation_state_arrives_near_clinic(navigasi):
    route, steps = navigasi

    state = navigation_state(route, steps, Point(400, 210))

    assert state["arrived"]
    assert state["active_index"] == len(steps) - 1
    assert state["next_index"] is None
    assert state["remaining_m"] == pytest.approx(10)


def test_navigation_state_off_route(navigasi):
    route, steps = navigasi

    far = navigation_state(route, steps, Point(150, 100))
    near = navigation_state(route, steps, Point(150, 25))

    assert far["off_route"]
    assert far["active_index"] is None and far["next_index"] is None
    assert not far["arrived"]
    assert not near["off_route"] and near["active_index"] == 1


def test_route_guide_highlights_active_step_and_dims_passed_steps(navigasi):
    route, steps = navigasi
    clinic = {"Nama_Klinik": "Klinik Uji", "jarak_rute_m": 650.0, "status_buka": "buka"}
    active = navigation_state(route, steps, Point(300, 1))["active_index"]

    rows = _route_guide_html(clinic, steps, active).split("<tr")[1:]
    off_route_rows = _route_guide_html(clinic, steps, None).split("<tr")[1:]

    assert ["#dbeafe" in row for row in rows] == [False, False, True, False, False]
    assert ["✓" in row for row in rows] == [True, True, False, False, False]
    assert not any("#dbeafe" in row or "✓" in row for row in off_route_rows)


def test_navigation_banner_text(navigasi):
    route, steps = navigasi

    def banner(position):
        return _navigation_banner_html(navigation_state(route, steps, Point(position)), steps, "Klinik Uji")

    on_route = banner((100, 0))
    assert "Belok kiri ke Jalan B" in on_route and "200 m" in on_route
    assert "Sisa 520 m" in on_route and "Lalu: ➡ Belok kanan ke Jalan C" in on_route
    assert "Anda telah tiba di Klinik Uji" in banner((400, 210))
    assert "Anda keluar dari rute" in banner((150, 100))
