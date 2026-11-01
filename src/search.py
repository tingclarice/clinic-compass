"""Clinic search that combines spatial, service, hours, and route filters."""

from dataclasses import dataclass
from datetime import datetime

import geopandas as gpd
from shapely.geometry import Point

from src.data_processing import buka_pada, daftar_layanan, parse_jadwal
from src.routing import route_clinics
from src.spatial import CRS_METER, klinik_dalam_radius


@dataclass
class ClinicSearchResult:
    clinics: gpd.GeoDataFrame
    radius_used_m: int
    expanded: bool
    clinics_in_radius: int
    service_matches: int
    verified_open: int
    unknown_hours: int
    closed_clinics: int


def _matches_service(services, selected_service):
    if not selected_service:
        return True
    selected = selected_service.strip().casefold()
    return any(service.strip().casefold() == selected for service in daftar_layanan(services))


def search_clinics(
    clinics,
    graph,
    user_location,
    search_time,
    service=None,
    radius_m=3000,
    max_radius_m=5000,
):
    """Find reachable clinics that match a service and report their hours status.

    Clinics with unknown or closed hours remain visible in the results but are
    never represented as open. If no known-open, reachable clinic is found at
    the requested radius, the search retries at the maximum radius.
    ``user_location`` and clinic geometries must use EPSG:32749.
    """
    if not isinstance(search_time, datetime):
        raise TypeError("search_time must be a datetime.")
    if not isinstance(user_location, Point):
        raise TypeError("user_location must be a Shapely Point.")
    if clinics.crs is None or clinics.crs.to_string() != CRS_METER:
        raise ValueError(f"clinics must use {CRS_METER}.")
    if radius_m <= 0 or max_radius_m < radius_m:
        raise ValueError("Radii must be positive and max_radius_m >= radius_m.")
    if "Jenis_Layanan" not in clinics.columns:
        raise ValueError("Clinic data must include the Jenis_Layanan column.")
    if "Jadwal_Operasional" not in clinics.columns:
        raise ValueError("Clinic data must include the Jadwal_Operasional column.")

    radii = [radius_m]
    if max_radius_m > radius_m:
        radii.append(max_radius_m)

    latest = None
    for radius in radii:
        candidates = klinik_dalam_radius(
            clinics, (user_location.x, user_location.y), radius
        )
        service_candidates = candidates[
            candidates["Jenis_Layanan"].apply(
                lambda services: _matches_service(services, service)
            )
        ].copy()

        minute_of_day = search_time.hour * 60 + search_time.minute
        statuses = service_candidates["Jadwal_Operasional"].apply(
            lambda schedule: buka_pada(
                parse_jadwal(schedule), search_time.weekday(), minute_of_day
            )
        )
        service_candidates["status_buka"] = statuses.map(
            {True: "buka", False: "tutup"}
        ).fillna("tidak diketahui")
        routed = route_clinics(graph, user_location, service_candidates)
        verified_open = int((routed["status_buka"] == "buka").sum())

        latest = ClinicSearchResult(
            clinics=routed,
            radius_used_m=radius,
            expanded=radius != radius_m,
            clinics_in_radius=len(candidates),
            service_matches=len(service_candidates),
            verified_open=verified_open,
            unknown_hours=int((statuses.isna()).sum()),
            closed_clinics=int(statuses.isin([False]).sum()),
        )
        if verified_open:
            return latest

    return latest
