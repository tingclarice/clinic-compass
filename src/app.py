"""Interactive Jupyter clinic finder built with ipyleaflet and ipywidgets."""

from datetime import datetime, time
from html import escape
import json

import geopandas as gpd
from shapely.geometry import Point

from src.routing import move_along_routes, move_to_reachable_road, navigation_state
from src.search import search_clinics
from src.spatial import CRS_METER


def _format_distance(meters):
    """Distance label for the route guide: metres below 1 km, otherwise kilometres."""
    if meters < 10:
        return f"{meters:.0f} m"
    if meters < 1000:
        return f"{int(round(meters / 10.0) * 10)} m"
    return f"{meters / 1000:.1f} km"


STATUS_COLOR = {"buka": "#15803d", "tutup": "#b45309", "tidak diketahui": "#64748b"}


def _route_guide_html(clinic, steps, active_index=None):
    """Route guide table: the step being travelled is highlighted, passed steps are dimmed."""
    rows = []
    for index, step in enumerate(steps):
        symbol = step["symbol"]
        row_style = ""
        marker_style = "border-left:3px solid transparent"
        if active_index is not None and index < active_index:
            symbol, row_style = "✓", "color:#94a3b8"
        elif index == active_index:
            row_style = "background:#dbeafe;font-weight:600"
            marker_style = "border-left:3px solid #2563eb"
        rows.append(
            f"<tr style='{row_style}'>"
            f"<td style='width:22px;text-align:center;padding:2px 4px;{marker_style}'>{escape(symbol)}</td>"
            f"<td style='padding:2px 4px'>{escape(step['instruction'])}</td>"
            f"<td style='text-align:right;white-space:nowrap;padding:2px 4px'>{_format_distance(step['distance_m'])}</td>"
            "</tr>"
        )
    return (
        "<div style='border:1px solid #cbd5e1;border-radius:6px;padding:6px 8px;margin:6px 0'>"
        f"<b>Petunjuk rute ke {escape(str(clinic['Nama_Klinik']))}</b><br>"
        f"<small>Total {clinic['jarak_rute_m'] / 1000:.2f} km · "
        f"{escape(str(clinic['status_buka']))}</small>"
        f"<table style='width:100%;margin-top:4px;border-collapse:collapse'>{''.join(rows)}</table>"
        "</div>"
    )


def _navigation_banner_html(state, steps, clinic_name):
    """Navigation banner shown over the map for a navigation_state() result."""
    box = (
        "<div style='background:{};color:#ffffff;border-radius:8px;padding:10px 14px;"
        "width:320px;box-sizing:border-box;box-shadow:0 2px 8px rgba(0,0,0,0.35);"
        "font-family:sans-serif'>{}</div>"
    )
    if state["off_route"]:
        return box.format(
            "#b45309",
            "<div style='font-size:16px;font-weight:600;line-height:1.3'>"
            "⚠ Anda keluar dari rute — klik <b>Cari klinik</b> untuk menghitung ulang</div>",
        )
    if state["arrived"]:
        return box.format(
            "#15803d",
            "<div style='font-size:18px;font-weight:700;line-height:1.3'>"
            f"🏁 Anda telah tiba di {escape(clinic_name)}</div>",
        )

    upcoming = steps[state["next_index"]]
    details = f"Sisa {_format_distance(state['remaining_m'])}"
    if state["then_index"] is not None:
        then = steps[state["then_index"]]
        details += f" · Lalu: {escape(then['symbol'])} {escape(then['instruction'])}"
    return box.format(
        "#15803d",
        "<div style='display:flex;align-items:center;gap:12px'>"
        f"<div style='font-size:34px;line-height:1'>{escape(upcoming['symbol'])}</div>"
        "<div>"
        f"<div style='font-size:18px;font-weight:700;line-height:1.25'>{escape(upcoming['instruction'])}</div>"
        f"<div style='font-size:15px;margin-top:2px'>dalam <b>{_format_distance(state['distance_to_next_m'])}</b></div>"
        "</div></div>"
        "<div style='border-top:1px solid rgba(255,255,255,0.35);margin-top:8px;"
        f"padding-top:6px;font-size:13px'>{details}</div>",
    )


def clinic_finder_app(clinics, boundaries, graph):
    """Build a map-based clinic search widget for use in a Jupyter notebook."""
    import ipywidgets as widgets
    from IPython.display import display
    from ipyleaflet import (
        AwesomeIcon,
        Circle,
        CircleMarker,
        GeoJSON,
        Map,
        Marker,
        Polyline,
        WidgetControl,
        basemaps,
    )

    if clinics.crs is None or clinics.crs.to_string() != CRS_METER:
        raise ValueError(f"clinics must use {CRS_METER}.")
    if boundaries.crs is None:
        raise ValueError("Boundary CRS is required.")
    movement_graph = graph.to_undirected()

    boundary_wgs84 = boundaries.to_crs("EPSG:4326")
    center = gpd.GeoSeries(
        [boundary_wgs84.geometry.union_all().centroid], crs="EPSG:4326"
    ).iloc[0]
    clinic_geojson = json.loads(clinics.to_crs("EPSG:4326").to_json())
    boundary_geojson = json.loads(boundary_wgs84.to_json())

    clinic_services = {
        service.strip()
        for value in clinics["Jenis_Layanan"].dropna()
        for service in str(value).split(",")
        if service.strip()
    }
    service_options = [("Semua layanan", None)] + [
        (service, service) for service in sorted(clinic_services, key=str.casefold)
    ]

    map_view = Map(
        basemap=basemaps.OpenStreetMap.Mapnik,
        center=(center.y, center.x),
        zoom=11,
        scroll_wheel_zoom=True,
        layout=widgets.Layout(width="70%", height="600px"),
    )
    map_height = widgets.IntSlider(
        value=600,
        min=400,
        max=1000,
        step=50,
        description="Tinggi peta (px):",
        continuous_update=True,
        layout=widgets.Layout(width="100%"),
    )

    map_height.observe(
        lambda change: setattr(map_view.layout, "height", f"{change['new']}px"),
        names="value",
    )

    map_view.add_layer(
        GeoJSON(
            data=boundary_geojson,
            name="Batas wilayah studi",
            style={"color": "#64748b", "fillOpacity": 0.06, "weight": 2},
        )
    )
    map_view.add_layer(
        GeoJSON(
            data=clinic_geojson,
            name="Klinik",
            point_style={"radius": 4, "color": "#1d4ed8", "fillOpacity": 0.7},
        )
    )

    service = widgets.Dropdown(
        options=service_options, description="Layanan:", layout=widgets.Layout(width="100%")
    )
    date_picker = widgets.DatePicker(
        description="Tanggal:", value=datetime.now().date(), layout=widgets.Layout(width="100%")
    )
    hour = widgets.Dropdown(
        options=[(f"{value:02d}:00", value) for value in range(24)],
        value=datetime.now().hour,
        description="Jam:", layout=widgets.Layout(width="100%"),
    )
    radius = widgets.Dropdown(
        options=[("1 km", 1000), ("3 km", 3000), ("5 km", 5000)],
        value=3000,
        description="Radius:", layout=widgets.Layout(width="100%"),
    )
    search_button = widgets.Button(
        description="Cari klinik", button_style="primary", disabled=True,
        layout=widgets.Layout(width="100%"),
    )
    result_html = widgets.HTML(
        value="<p>Klik peta untuk memilih lokasi awal.</p>"
    )
    move_status = widgets.HTML()
    route_guide = widgets.HTML()
    nav_banner = widgets.HTML()
    nav_control = WidgetControl(widget=nav_banner, position="topright")
    clinic_list = widgets.VBox(layout=widgets.Layout(width="100%"))
    user_location = None
    user_marker = None
    result_layers = []
    selection_layers = []
    active_routes = []
    navigation = None  # (clinic, steps) of the selected clinic route

    def clear_selection():
        nonlocal navigation
        while selection_layers:
            map_view.remove_layer(selection_layers.pop())
        route_guide.value = ""
        navigation = None
        if nav_control in map_view.controls:
            map_view.remove_control(nav_control)

    def update_navigation():
        """Refresh the banner and the highlighted route step from the user's position."""
        if navigation is None:
            return
        clinic, steps = navigation
        position = gpd.GeoSeries(
            [user_location], crs=CRS_METER
        ).to_crs(graph.graph["crs"]).iloc[0]
        state = navigation_state(clinic["rute"], steps, position)
        nav_banner.value = _navigation_banner_html(
            state, steps, str(clinic["Nama_Klinik"])
        )
        route_guide.value = _route_guide_html(clinic, steps, state["active_index"])
        if nav_control not in map_view.controls:
            map_view.add_control(nav_control)

    def clear_results():
        clear_selection()
        clinic_list.children = ()
        while result_layers:
            map_view.remove_layer(result_layers.pop())

    def show_user_location():
        nonlocal user_marker
        if user_marker is not None:
            map_view.remove_layer(user_marker)
        location_wgs84 = gpd.GeoSeries(
            [user_location], crs=CRS_METER
        ).to_crs("EPSG:4326").iloc[0]
        user_marker = CircleMarker(
            location=(location_wgs84.y, location_wgs84.x),
            title="Lokasi pencarian",
            radius=8,
            color="#ffffff",
            weight=2,
            fill_color="#dc2626",
            fill_opacity=1,
        )
        map_view.add_layer(user_marker)
        search_button.disabled = False
        for button in move_buttons:
            button.disabled = False

    def on_map_interaction(**event):
        nonlocal active_routes, user_location
        if event.get("type") != "click":
            return
        latitude, longitude = event["coordinates"]
        user_location = gpd.GeoSeries(
            [Point(longitude, latitude)], crs="EPSG:4326"
        ).to_crs(CRS_METER).iloc[0]
        clear_results()
        active_routes = []
        move_status.value = ""
        show_user_location()
        result_html.value = "<p>Lokasi dipilih. Pilih kriteria lalu cari.</p>"

    map_view.on_interaction(on_map_interaction)

    directions = [("Atas", "atas"), ("Bawah", "bawah"), ("Kiri", "kiri"), ("Kanan", "kanan")]
    move_buttons = []
    for label, direction in directions:
        button = widgets.Button(description=label, disabled=True)

        def move_user(_button, direction=direction):
            nonlocal user_location
            if active_routes:
                moved_location = move_along_routes(
                    active_routes,
                    user_location,
                    direction,
                    route_crs=graph.graph["crs"],
                )
            else:
                moved_location = move_to_reachable_road(
                    graph, movement_graph, user_location, direction
                )
            if moved_location is None:
                move_status.value = "<p>Tidak ada rute ke arah itu; lokasi tidak berubah.</p>"
                return
            user_location = moved_location
            move_status.value = ""
            show_user_location()
            update_navigation()
            location_wgs84 = gpd.GeoSeries(
                [user_location], crs=CRS_METER
            ).to_crs("EPSG:4326").iloc[0]
            map_view.center = (location_wgs84.y, location_wgs84.x)

        button.on_click(move_user)
        move_buttons.append(button)

    def run_search(_button):
        nonlocal active_routes
        clear_results()
        active_routes = []
        move_status.value = ""
        if date_picker.value is None:
            raise ValueError("Pilih tanggal pencarian.")
        search_time = datetime.combine(
            date_picker.value, time(hour.value, 0)
        )
        summary = search_clinics(
            clinics=clinics,
            graph=graph,
            user_location=user_location,
            search_time=search_time,
            service=service.value,
            radius_m=radius.value,
            max_radius_m=5000,
        )
        user_wgs84 = gpd.GeoSeries(
            [user_location], crs=CRS_METER
        ).to_crs("EPSG:4326").iloc[0]
        map_view.add_layer(
            Circle(
                location=(user_wgs84.y, user_wgs84.x),
                radius=summary.radius_used_m,
                color="#2563eb",
                fill_opacity=0.08,
                name="Radius pencarian",
            )
        )
        result_layers.append(map_view.layers[-1])

        if summary.clinics.empty:
            if summary.clinics_in_radius == 0:
                reason = "Tidak ada klinik di dalam radius pencarian."
            elif summary.service_matches == 0:
                reason = "Klinik ditemukan, tetapi tidak ada yang cocok dengan layanan pilihan."
            else:
                reason = "Klinik yang cocok tidak dapat dijangkau melalui jaringan jalan."
            result_html.value = (
                f"<p><strong>{escape(reason)}</strong></p>"
                f"<p>Radius akhir: {summary.radius_used_m / 1000:g} km"
                f"{' (diperluas otomatis)' if summary.expanded else ''}. "
                f"Klinik dalam radius: {summary.clinics_in_radius}; "
                f"sesuai layanan: {summary.service_matches}; "
                f"terverifikasi buka: {summary.verified_open}; "
                f"jam tidak diketahui: {summary.unknown_hours}; "
                f"tercatat tutup: {summary.closed_clinics}.</p>"
                "<p>Jam yang tidak tersedia tidak dianggap sebagai klinik buka.</p>"
            )
            return

        active_routes = [
            clinic["rute"]
            for _, clinic in summary.clinics.iterrows()
            if clinic["rute"] is not None
        ]
        items = []
        buttons = []
        for number, (_, clinic) in enumerate(summary.clinics.iterrows(), start=1):
            is_closed = clinic["status_buka"] == "tutup"
            point_wgs84 = gpd.GeoSeries(
                [clinic.geometry], crs=clinics.crs
            ).to_crs("EPSG:4326").iloc[0]
            route_wgs84 = gpd.GeoSeries(
                [clinic["rute"]], crs=graph.graph["crs"]
            ).to_crs("EPSG:4326").iloc[0]
            map_view.add_layer(
                Polyline(
                    locations=[(y, x) for x, y in route_wgs84.coords],
                    color="#f97316" if is_closed else "#2563eb",
                    weight=4,
                    opacity=0.75,
                )
            )
            result_layers.append(map_view.layers[-1])
            map_view.add_layer(
                Marker(
                    location=(point_wgs84.y, point_wgs84.x),
                    title=str(clinic["Nama_Klinik"]),
                    **(
                        {
                            "icon": AwesomeIcon(
                                name="map-marker",
                                marker_color="orange",
                                icon_color="white",
                            )
                        }
                        if is_closed
                        else {}
                    ),
                )
            )
            result_layers.append(map_view.layers[-1])

            status = str(clinic["status_buka"])
            button = widgets.Button(
                description=f"{number}. {clinic['Nama_Klinik']} — {clinic['jarak_rute_m'] / 1000:.2f} km",
                tooltip=f"{clinic['Nama_Klinik']} · {clinic['Jenis_Layanan']} · {status}",
                layout=widgets.Layout(width="100%"),
            )
            detail = widgets.HTML(
                f"<small style='color:{STATUS_COLOR.get(status, '#64748b')}'>"
                f"{escape(status)}</small><small> · {escape(str(clinic['Jenis_Layanan']))}"
                f" · {escape(str(clinic['Jadwal_Operasional']))}</small>"
            )
            button.on_click(
                lambda _b, clinic=clinic, route=route_wgs84, number=number: select_clinic(
                    clinic, route, number
                )
            )
            buttons.append(button)
            items.append(widgets.VBox([button, detail]))

        def select_clinic(clinic, route_wgs84, number):
            nonlocal active_routes, navigation
            clear_selection()
            for index, button in enumerate(buttons, start=1):
                button.button_style = "success" if index == number else ""
            active_routes = [clinic["rute"]]

            map_view.add_layer(
                Polyline(
                    locations=[(y, x) for x, y in route_wgs84.coords],
                    color="#16a34a",
                    weight=7,
                    opacity=0.95,
                )
            )
            selection_layers.append(map_view.layers[-1])
            steps = clinic["langkah_rute"] or []
            turn_points = [step["point"] for step in steps if step.get("point") is not None]
            if turn_points:
                turn_points_wgs84 = gpd.GeoSeries(
                    [Point(point) for point in turn_points], crs=graph.graph["crs"]
                ).to_crs("EPSG:4326")
                for point in turn_points_wgs84:
                    map_view.add_layer(
                        CircleMarker(
                            location=(point.y, point.x),
                            radius=5,
                            color="#16a34a",
                            weight=2,
                            fill_color="#ffffff",
                            fill_opacity=1,
                        )
                    )
                    selection_layers.append(map_view.layers[-1])
            min_x, min_y, max_x, max_y = route_wgs84.bounds
            map_view.fit_bounds([[min_y, min_x], [max_y, max_x]])

            if steps:
                navigation = (clinic, steps)
                update_navigation()
            else:
                route_guide.value = _route_guide_html(clinic, steps)

        clinic_list.children = tuple(items)
        result_html.value = (
            f"<p>{summary.verified_open} klinik terverifikasi buka; "
            f"{summary.unknown_hours} jam tidak diketahui; "
            f"{summary.closed_clinics} tercatat tutup. Hasil mencakup semua klinik "
            "yang cocok dan dapat dijangkau, diurutkan menurut jarak rute. "
            f"Radius pencarian: {summary.radius_used_m / 1000:g} km"
            f"{' (diperluas otomatis)' if summary.expanded else ''}.</p>"
            "<p><b>Pilih klinik</b> untuk menampilkan petunjuk rute dan jarak "
            "di setiap belokan.</p>"
        )

    search_button.on_click(run_search)

    controls = widgets.VBox(
        [
            widgets.HTML("<h3>Clinic Compass</h3><p>Klik peta untuk memilih lokasi.</p>"),
            service,
            date_picker,
            hour,
            radius,
            map_height,
            widgets.HTML("<b>Adjust location (50 m)</b>"),
            widgets.HBox(move_buttons),
            move_status,
            route_guide,
            search_button,
            result_html,
            clinic_list,
        ],
        layout=widgets.Layout(width="30%", padding="8px"),
    )
    display(widgets.HBox([map_view, controls]))
