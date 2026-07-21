"""Charging-station CSV repository."""

from __future__ import annotations

import csv
import math
from collections import Counter
from pathlib import Path
from typing import Any

from app.domain.models import Point, Station
from app.domain.planner import haversine_km


def _float(value: Any) -> float | None:
    try:
        return float(value) if value not in {None, ""} else None
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    parsed = _float(value)
    return int(parsed) if parsed is not None else None


class StationRepository:
    """Read-only in-memory view of the station seed data."""

    def __init__(self, stations: list[Station], source_path: Path) -> None:
        self.stations = stations
        self.source_path = source_path

    @classmethod
    def from_csv(cls, path: Path) -> StationRepository:
        grouped: dict[str, Station] = {}
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                station_id = (row.get("station_id") or "").strip()
                latitude = _float(row.get("latitude"))
                longitude = _float(row.get("longitude"))
                if not station_id or latitude is None or longitude is None:
                    continue

                connector = (row.get("connector_type") or "unknown").strip().lower()
                if station_id not in grouped:
                    grouped[station_id] = Station(
                        station_id=station_id,
                        name=(row.get("name") or "EV charging station").strip(),
                        latitude=latitude,
                        longitude=longitude,
                        address=(row.get("address") or "").strip(),
                        city=(row.get("city") or "").strip(),
                        state=(row.get("state") or "").strip(),
                        operator_name=(row.get("operator_name") or "").strip(),
                        network_name=(row.get("network_name") or "").strip(),
                        access_type=(row.get("access_type") or "public").strip().lower(),
                        status=(row.get("status") or "unknown").strip().lower(),
                        connector_count=_integer(row.get("connector_count")),
                        confidence_score=_float(row.get("confidence_score")) or 0,
                        source_name=(row.get("source_name") or "").strip(),
                        source_external_id=(row.get("source_external_id") or "").strip(),
                        source_license=(row.get("source_license") or "").strip(),
                        last_verified_at=(row.get("last_verified_at") or "").strip(),
                    )
                station = grouped[station_id]
                station.connector_types.add(connector)
                power = _float(row.get("power_kw"))
                if power is not None and (station.power_kw is None or power > station.power_kw):
                    station.power_kw = power

        # Merge OSM nodes that represent bays at the same physical site.
        sites: dict[tuple[str, float, float], Station] = {}
        for station in grouped.values():
            site_key = (station.name.casefold(), round(station.latitude, 4), round(station.longitude, 4))
            existing = sites.get(site_key)
            if existing is None:
                sites[site_key] = station
                continue
            existing.connector_types.update(station.connector_types)
            existing.confidence_score = max(existing.confidence_score, station.confidence_score)
            if station.power_kw is not None and (existing.power_kw is None or station.power_kw > existing.power_kw):
                existing.power_kw = station.power_kw

        return cls(list(sites.values()), path)

    def statistics(self) -> dict[str, Any]:
        source_counts = Counter(station.source_name or "unknown" for station in self.stations)
        with_connector = sum(bool(station.connector_types - {"", "unknown"}) for station in self.stations)
        with_power = sum(station.power_kw is not None for station in self.stations)
        return {
            "total_stations": len(self.stations),
            "with_connector_data": with_connector,
            "with_power_data": with_power,
            "sources": dict(source_counts),
        }

    def nearby(self, latitude: float, longitude: float, radius_km: float, limit: int) -> list[dict[str, Any]]:
        point = Point(latitude, longitude)
        results: list[tuple[float, Station]] = []
        latitude_pad = radius_km / 111.0
        longitude_pad = radius_km / max(20.0, 111.0 * math.cos(math.radians(latitude)))
        for station in self.stations:
            if abs(station.latitude - latitude) > latitude_pad or abs(station.longitude - longitude) > longitude_pad:
                continue
            distance = haversine_km(point, Point(station.latitude, station.longitude))
            if distance <= radius_km:
                results.append((distance, station))
        results.sort(key=lambda item: item[0])
        return [self.serialize(station, distance) for distance, station in results[:limit]]

    @staticmethod
    def serialize(station: Station, distance_km: float | None = None) -> dict[str, Any]:
        return {
            "station_id": station.station_id,
            "name": station.name,
            "latitude": station.latitude,
            "longitude": station.longitude,
            "address": station.address or None,
            "city": station.city or None,
            "state": station.state or None,
            "operator_name": station.operator_name or None,
            "status": station.status,
            "access_type": station.access_type,
            "connectors": sorted(station.connector_types - {""}) or ["unknown"],
            "power_kw": station.power_kw,
            "confidence_score": station.confidence_score,
            "distance_km": round(distance_km, 2) if distance_km is not None else None,
            "source_name": station.source_name or None,
            "source_external_id": station.source_external_id or None,
        }
