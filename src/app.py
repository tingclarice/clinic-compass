"""Interactive Jupyter clinic finder built with ipyleaflet and ipywidgets."""

from datetime import datetime, time
from html import escape
import json

import geopandas as gpd
from shapely.geometry import Point

from src.lokasi import geser
from src.search import search_clinics
from src.spatial import CRS_METER


def clinic_finder_app(clinics, boundaries, graph):
    """Build a map-based clinic search widget for use in a Jupyter notebook."""
    import ipywidgets as widgets
    from IPython.display import display
    from ipyleaflet import Circle, GeoJSON, Map, Marker, Polyline, basemaps

    if clinics.crs is None or clinics.crs.to_string() != CRS_METER:
        raise ValueError(f"clinics must use {CRS_METER}.")
    if boundaries.crs is None:
        raise ValueError("Boundary CRS is required.")

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
    user_location = None
    user_marker = None
    result_layers = []

    def clear_results():
        while result_layers:
            map_view.remove_layer(result_layers.pop())

    def show_user_location():
        nonlocal user_marker
        if user_marker is not None:
            map_view.remove_layer(user_marker)
        location_wgs84 = gpd.GeoSeries(
            [user_location], crs=CRS_METER
        ).to_crs("EPSG:4326").iloc[0]
        user_marker = Marker(
            location=(location_wgs84.y, location_wgs84.x),
            title="Lokasi pencarian",
            draggable=False,
        )
        map_view.add_layer(user_marker)
        search_button.disabled = False
        for button in move_buttons:
            button.disabled = False

    def on_map_interaction(**event):
        nonlocal user_location
        if event.get("type") != "click":
            return
        latitude, longitude = event["coordinates"]
        user_location = gpd.GeoSeries(
            [Point(longitude, latitude)], crs="EPSG:4326"
        ).to_crs(CRS_METER).iloc[0]
        clear_results()
        show_user_location()
        result_html.value = "<p>Lokasi dipilih. Pilih kriteria lalu cari.</p>"

    map_view.on_interaction(on_map_interaction)

    directions = [("Atas", "atas"), ("Bawah", "bawah"), ("Kiri", "kiri"), ("Kanan", "kanan")]
    move_buttons = []
    for label, direction in directions:
        button = widgets.Button(description=label, disabled=True)

        def move_user(_button, direction=direction):
            nonlocal user_location
            user_location = geser(user_location, direction)
            clear_results()
            show_user_location()
            location_wgs84 = gpd.GeoSeries(
                [user_location], crs=CRS_METER
            ).to_crs("EPSG:4326").iloc[0]
            map_view.center = (location_wgs84.y, location_wgs84.x)
            result_html.value = "<p>Lokasi diperbarui. Jalankan pencarian lagi.</p>"

        button.on_click(move_user)
        move_buttons.append(button)

    def run_search(_button):
        clear_results()
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

        rows = []
        for _, clinic in summary.clinics.iterrows():
            point_wgs84 = gpd.GeoSeries(
                [clinic.geometry], crs=clinics.crs
            ).to_crs("EPSG:4326").iloc[0]
            route_wgs84 = gpd.GeoSeries(
                [clinic["rute"]], crs=graph.graph["crs"]
            ).to_crs("EPSG:4326").iloc[0]
            map_view.add_layer(
                Polyline(
                    locations=[(y, x) for x, y in route_wgs84.coords],
                    color="#2563eb",
                    weight=4,
                    opacity=0.75,
                )
            )
            result_layers.append(map_view.layers[-1])
            rows.append(
                "<tr>"
                f"<td>{escape(str(clinic['Nama_Klinik']))}</td>"
                f"<td>{escape(str(clinic['Jenis_Layanan']))}</td>"
                f"<td>{clinic['jarak_rute_m'] / 1000:.2f} km</td>"
                f"<td>{escape(str(clinic['status_buka']))}</td>"
                f"<td>{escape(str(clinic['Jadwal_Operasional']))}</td>"
                "</tr>"
            )
            map_view.add_layer(
                Marker(
                    location=(point_wgs84.y, point_wgs84.x),
                    title=str(clinic["Nama_Klinik"]),
                )
            )
            result_layers.append(map_view.layers[-1])

        result_html.value = (
            f"<p>{summary.verified_open} klinik terverifikasi buka; "
            f"{summary.unknown_hours} jam tidak diketahui; "
            f"{summary.closed_clinics} tercatat tutup. Hasil mencakup semua klinik "
            "yang cocok dan dapat dijangkau, diurutkan menurut jarak rute. "
            f"Radius pencarian: {summary.radius_used_m / 1000:g} km"
            f"{' (diperluas otomatis)' if summary.expanded else ''}.</p>"
            "<table><thead><tr><th>Klinik</th><th>Layanan</th>"
            "<th>Jarak rute</th><th>Status jam</th><th>Jam terdaftar</th></tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table>"
        )

    search_button.on_click(run_search)

    controls = widgets.VBox(
        [
            widgets.HTML("<h3>Clinic Compass</h3><p>Klik peta untuk memilih lokasi.</p>"),
            service,
            date_picker,
            hour,
            radius,
            widgets.HTML("<b>Adjust location (50 m)</b>"),
            widgets.HBox(move_buttons),
            search_button,
            result_html,
        ],
        layout=widgets.Layout(width="30%", padding="8px"),
    )
    display(widgets.HBox([map_view, controls]))
