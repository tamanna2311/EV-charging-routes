"""Battery-aware, route-aware EV charging recommendation engine."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from app.domain.models import Point, Route, Station

EARTH_RADIUS_KM = 6371.0088
KNOWN_CONNECTORS = {"ccs2", "type2", "chademo", "gbt", "tesla", "bharat_ac_001", "bharat_dc_001"}
DC_CONNECTORS = {"ccs2", "chademo", "gbt", "bharat_dc_001"}


class InputError(ValueError):
    """Raised when a trip cannot be planned from the supplied input."""


def _number(value: Any, name: str, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise InputError(f"{name} must be a number") from exc
    if not minimum <= parsed <= maximum:
        raise InputError(f"{name} must be between {minimum:g} and {maximum:g}")
    return parsed


def parse_point(raw: Any, name: str) -> Point:
    if not isinstance(raw, dict):
        raise InputError(f"{name} is required")
    return Point(
        _number(raw.get("latitude"), f"{name} latitude", -90, 90),
        _number(raw.get("longitude"), f"{name} longitude", -180, 180),
        str(raw.get("label") or name.title()),
    )


def haversine_km(a: Point, b: Point) -> float:
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlat = lat2 - lat1
    dlon = math.radians(b.longitude - a.longitude)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def _project_to_segment(point: Point, start: Point, end: Point) -> tuple[float, float]:
    mean_lat = math.radians((start.latitude + end.latitude + point.latitude) / 3)

    def xy(item: Point) -> tuple[float, float]:
        return (
            EARTH_RADIUS_KM * math.radians(item.longitude) * math.cos(mean_lat),
            EARTH_RADIUS_KM * math.radians(item.latitude),
        )

    x1, y1 = xy(start)
    x2, y2 = xy(end)
    xp, yp = xy(point)
    dx, dy = x2 - x1, y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return haversine_km(point, start), 0.0
    ratio = max(0.0, min(1.0, ((xp - x1) * dx + (yp - y1) * dy) / length_sq))
    return math.hypot(xp - (x1 + ratio * dx), yp - (y1 + ratio * dy)), ratio


def _thin_points(points: tuple[Point, ...], maximum: int = 240) -> tuple[Point, ...]:
    if len(points) <= maximum:
        return points
    step = (len(points) - 1) / (maximum - 1)
    indices = sorted({round(index * step) for index in range(maximum)})
    return tuple(points[index] for index in indices)


def _cumulative_distances(points: tuple[Point, ...]) -> tuple[list[float], float]:
    cumulative = [0.0]
    for start, end in zip(points, points[1:], strict=False):
        cumulative.append(cumulative[-1] + haversine_km(start, end))
    return cumulative, cumulative[-1]


def project_to_route(point: Point, route: Route) -> tuple[float, float, float]:
    points = _thin_points(route.points)
    cumulative, geometry_length = _cumulative_distances(points)
    best: tuple[float, float] | None = None
    for index, (start, end) in enumerate(zip(points, points[1:], strict=False)):
        distance, segment_ratio = _project_to_segment(point, start, end)
        segment_length = cumulative[index + 1] - cumulative[index]
        geometry_km = cumulative[index] + segment_length * segment_ratio
        if best is None or distance < best[0]:
            best = (distance, geometry_km)
    if best is None:
        return haversine_km(point, points[0]), 0.0, 0.0
    progress = best[1] / geometry_length if geometry_length else 0.0
    return best[0], progress, route.distance_km * progress


def build_route(
    origin: Point,
    destination: Point,
    route_points: Iterable[dict[str, Any]] | None = None,
    distance_km: float | None = None,
    duration_minutes: float | None = None,
    source: str = "estimated",
) -> Route:
    points = tuple(parse_point(item, "route point") for item in (route_points or []))
    if len(points) < 2:
        points = (origin, destination)
    if distance_km is None:
        distance_km = haversine_km(origin, destination) * 1.25
        source = "estimated"
    duration = None
    if duration_minutes is not None:
        duration = _number(duration_minutes, "route duration", 0.1, 20000)
    return Route(points, _number(distance_km, "route distance", 0.05, 10000), duration, source)


def _display_connector(connector: str) -> str:
    return {
        "ccs2": "CCS2",
        "type2": "Type 2",
        "chademo": "CHAdeMO",
        "gbt": "GB/T",
        "tesla": "Tesla",
        "bharat_ac_001": "Bharat AC-001",
        "bharat_dc_001": "Bharat DC-001",
        "unknown": "Unverified",
    }.get(connector, connector.upper())


def _route_bbox(route: Route, padding_km: float) -> tuple[float, float, float, float]:
    latitudes = [point.latitude for point in route.points]
    longitudes = [point.longitude for point in route.points]
    middle_latitude = sum(latitudes) / len(latitudes)
    latitude_pad = padding_km / 111.0
    longitude_pad = padding_km / max(20.0, 111.0 * math.cos(math.radians(middle_latitude)))
    return (
        min(latitudes) - latitude_pad,
        min(longitudes) - longitude_pad,
        max(latitudes) + latitude_pad,
        max(longitudes) + longitude_pad,
    )


def _reason_labels(
    verified: bool,
    deviation_km: float,
    arrival_soc: float,
    reserve_soc: float,
    power_kw: float | None,
    confidence: float,
) -> list[str]:
    reasons = ["Compatible connector" if verified else "Connector needs confirmation"]
    reasons.append("Under 1 km from your route" if deviation_km <= 1 else "Low route deviation")
    reasons.append("Comfortable arrival battery" if arrival_soc >= reserve_soc + 5 else "Reachable above your reserve")
    if power_kw and power_kw >= 25:
        reasons.append("Fast charging listed")
    if confidence >= 60:
        reasons.append("Higher-confidence station record")
    return reasons


def recommend_stations(
    payload: dict[str, Any], stations: list[Station], route_data: dict[str, Any] | None = None
) -> dict[str, Any]:
    origin = parse_point(payload.get("origin"), "origin")
    destination = parse_point(payload.get("destination"), "destination")
    vehicle = payload.get("vehicle") if isinstance(payload.get("vehicle"), dict) else {}
    preferences = payload.get("preferences") if isinstance(payload.get("preferences"), dict) else {}

    capacity = _number(vehicle.get("battery_capacity_kwh"), "battery capacity", 5, 250)
    current_soc = _number(vehicle.get("current_soc_percent"), "current battery", 0, 100)
    reserve_soc = _number(vehicle.get("reserve_soc_percent", 15), "reserve battery", 0, 50)
    consumption = _number(vehicle.get("consumption_wh_per_km"), "energy consumption", 60, 500)
    safety_buffer = _number(vehicle.get("safety_buffer_percent", 10), "safety buffer", 0, 40)
    max_ac_kw = _number(vehicle.get("max_ac_kw", 7.2), "maximum AC rate", 1, 50)
    max_dc_kw = _number(vehicle.get("max_dc_kw", 50), "maximum DC rate", 1, 500)
    connectors = {str(item).strip().lower() for item in vehicle.get("connector_types", []) if str(item).strip()}
    if not connectors:
        raise InputError("select at least one connector supported by the vehicle")

    max_detour_km = _number(preferences.get("max_detour_km", 12), "maximum detour", 0.5, 80)
    maximum_results = int(_number(preferences.get("maximum_results", 5), "maximum results", 1, 10))
    minimum_confidence = _number(preferences.get("minimum_station_confidence", 40), "minimum confidence", 0, 100)
    allow_unverified = bool(preferences.get("allow_unverified_connectors", True))
    mode = str(preferences.get("mode", "balanced")).lower()
    if mode not in {"balanced", "fastest", "shortest_detour", "safest"}:
        raise InputError("preference mode is not supported")

    route_data = route_data or {}
    supplied_route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
    route = build_route(
        origin,
        destination,
        route_data.get("points") or supplied_route.get("points"),
        route_data.get("distance_km") or supplied_route.get("distance_km"),
        route_data.get("duration_minutes") or supplied_route.get("duration_minutes"),
        str(route_data.get("source") or supplied_route.get("source") or "estimated"),
    )

    adjusted_consumption = consumption * (1 + safety_buffer / 100)
    energy_now_kwh = capacity * current_soc / 100
    reserve_kwh = capacity * reserve_soc / 100
    safe_available_kwh = max(0.0, energy_now_kwh - reserve_kwh)
    energy_needed_kwh = route.distance_km * adjusted_consumption / 1000
    direct_arrival_soc = max(0.0, (energy_now_kwh - energy_needed_kwh) / capacity * 100)
    charging_required = energy_needed_kwh > safe_available_kwh
    safe_range_km = safe_available_kwh * 1000 / adjusted_consumption

    rejected = {
        "outside_route_corridor": 0,
        "incompatible_connector": 0,
        "unreachable_before_reserve": 0,
        "unverified_or_low_confidence": 0,
        "not_public_or_closed": 0,
    }
    candidates: list[dict[str, Any]] = []
    min_lat, min_lon, max_lat, max_lon = _route_bbox(route, max_detour_km / 2 + 2)

    for station in stations:
        if not (min_lat <= station.latitude <= max_lat and min_lon <= station.longitude <= max_lon):
            rejected["outside_route_corridor"] += 1
            continue
        if station.access_type not in {"", "public", "public_paid"} or station.status in {"closed", "unavailable"}:
            rejected["not_public_or_closed"] += 1
            continue
        if station.confidence_score < minimum_confidence:
            rejected["unverified_or_low_confidence"] += 1
            continue

        station_point = Point(station.latitude, station.longitude, station.name)
        corridor_distance, progress, route_km = project_to_route(station_point, route)
        total_detour = corridor_distance * 2.4
        if total_detour > max_detour_km:
            rejected["outside_route_corridor"] += 1
            continue

        known_connectors = station.connector_types - {"unknown", ""}
        matching_connectors = connectors & known_connectors
        verified = bool(matching_connectors)
        if not verified and not (not known_connectors and allow_unverified):
            rejected["incompatible_connector"] += 1
            continue

        distance_to_station = route_km + corridor_distance * 1.2
        arrival_energy = energy_now_kwh - distance_to_station * adjusted_consumption / 1000
        arrival_soc = arrival_energy / capacity * 100
        if arrival_soc + 0.05 < reserve_soc:
            rejected["unreachable_before_reserve"] += 1
            continue

        remaining_distance = max(0.0, route.distance_km - route_km) + corridor_distance * 1.2
        energy_for_finish = remaining_distance * adjusted_consumption / 1000 + reserve_kwh
        charge_needed = max(0.0, energy_for_finish - max(0.0, arrival_energy))
        target_soc = min(100.0, (max(0.0, arrival_energy) + charge_needed) / capacity * 100)
        can_finish = energy_for_finish <= capacity + 1e-6

        assumed_power = station.power_kw or min(max_ac_kw, 7.2)
        vehicle_limit = max_dc_kw if matching_connectors & DC_CONNECTORS else max_ac_kw
        effective_power = max(1.0, min(assumed_power, vehicle_limit))
        charge_minutes = charge_needed / (effective_power * 0.90) * 60 if charge_needed else 0

        detour_score = max(0.0, 1 - total_detour / max_detour_km)
        connector_score = 1.0 if verified else 0.35
        confidence_score = station.confidence_score / 100
        power_score = min(effective_power / max(max_dc_kw, 1), 1.0)
        arrival_score = min(max((arrival_soc - reserve_soc) / 15, 0.0), 1.0)
        ideal_progress = (
            min(0.65, max(0.12, safe_range_km / max(route.distance_km, 0.1) * 0.72)) if charging_required else 0.75
        )
        placement_score = max(0.0, 1 - abs(progress - ideal_progress))
        weights = {
            "balanced": (0.24, 0.20, 0.16, 0.13, 0.15, 0.12),
            "fastest": (0.23, 0.12, 0.13, 0.30, 0.12, 0.10),
            "shortest_detour": (0.22, 0.36, 0.13, 0.08, 0.11, 0.10),
            "safest": (0.24, 0.12, 0.21, 0.08, 0.25, 0.10),
        }[mode]
        score = 100 * sum(
            value * weight
            for value, weight in zip(
                (connector_score, detour_score, confidence_score, power_score, arrival_score, placement_score),
                weights,
                strict=False,
            )
        )
        if not can_finish:
            score *= 0.75

        available = sorted(known_connectors) or ["unknown"]
        candidates.append(
            {
                "station_id": station.station_id,
                "name": station.name,
                "operator_name": station.operator_name or station.network_name or "Operator not listed",
                "address": station.address or None,
                "location": {"latitude": station.latitude, "longitude": station.longitude},
                "connectors": [_display_connector(item) for item in available],
                "matching_connectors": [_display_connector(item) for item in sorted(matching_connectors)],
                "connector_verified": verified,
                "power_kw": station.power_kw,
                "route_progress_percent": round(progress * 100, 1),
                "distance_from_start_km": round(distance_to_station, 1),
                "route_deviation_km": round(corridor_distance, 1),
                "estimated_total_detour_km": round(total_detour, 1),
                "arrival_soc_percent": round(arrival_soc, 1),
                "suggested_target_soc_percent": round(target_soc, 1),
                "energy_to_add_kwh": round(charge_needed, 1),
                "estimated_charge_minutes": round(charge_minutes) if station.power_kw is not None else None,
                "can_finish_after_charge": can_finish,
                "score": round(score, 1),
                "confidence_score": station.confidence_score,
                "reasons": _reason_labels(
                    verified, corridor_distance, arrival_soc, reserve_soc, station.power_kw, station.confidence_score
                ),
                "verification_note": (
                    "The connector is listed in the source data. Confirm live availability before arrival."
                    if verified
                    else "The source does not list a connector. Confirm compatibility before relying on this stop."
                ),
                "navigation_url": f"https://www.google.com/maps/dir/?api=1&destination={station.latitude},{station.longitude}",
                "source": {
                    "name": station.source_name or None,
                    "external_id": station.source_external_id or None,
                    "last_verified_at": station.last_verified_at or None,
                },
            }
        )

    candidates.sort(
        key=lambda item: (
            item["connector_verified"],
            item["can_finish_after_charge"],
            item["score"],
            -item["estimated_total_detour_km"],
        ),
        reverse=True,
    )
    recommendations = candidates[:maximum_results]

    if charging_required and recommendations:
        status, title = "stop_required", "Add a charging stop"
        summary = (
            f"This route needs about {energy_needed_kwh:.1f} kWh. "
            f"Your usable energy before reserve is {safe_available_kwh:.1f} kWh."
        )
    elif charging_required:
        status, title = "charge_before_departure", "Charge before you leave"
        summary = "No compatible, reachable station was found inside your detour limit for this route."
    else:
        status, title = "no_stop_needed", "You can reach without charging"
        summary = (
            f"You should arrive with about {direct_arrival_soc:.0f}% battery, "
            f"including your {safety_buffer:.0f}% driving buffer."
        )

    warnings: list[str] = []
    if route.source != "osrm":
        warnings.append("Road distance is estimated because live routing was unavailable.")
    if any(not item["connector_verified"] for item in recommendations):
        warnings.append("Some backup stations have incomplete connector data; verify them before leaving.")
    if not charging_required:
        warnings.append("Recommended stations are optional backups for this route.")

    return {
        "decision": {"status": status, "title": title, "summary": summary},
        "origin": origin.as_dict(),
        "destination": destination.as_dict(),
        "route": {
            "distance_km": round(route.distance_km, 1),
            "duration_minutes": round(route.duration_minutes) if route.duration_minutes else None,
            "source": route.source,
            "geometry": [[point.latitude, point.longitude] for point in route.points],
        },
        "battery": {
            "capacity_kwh": capacity,
            "current_soc_percent": current_soc,
            "reserve_soc_percent": reserve_soc,
            "adjusted_consumption_wh_per_km": round(adjusted_consumption),
            "energy_needed_kwh": round(energy_needed_kwh, 1),
            "safe_available_energy_kwh": round(safe_available_kwh, 1),
            "safe_range_km": round(safe_range_km, 1),
            "estimated_direct_arrival_soc_percent": round(direct_arrival_soc, 1),
            "energy_shortfall_kwh": round(max(0.0, energy_needed_kwh - safe_available_kwh), 1),
        },
        "recommendations": recommendations,
        "candidate_count": len(candidates),
        "station_count": len(stations),
        "rejected_counts": rejected,
        "warnings": warnings,
        "assumptions": [
            "Energy use includes the selected driving-condition buffer.",
            "Detour and charging time are estimates, not live navigation or charger availability.",
            "The current planner ranks a single charging stop per route option.",
        ],
    }
