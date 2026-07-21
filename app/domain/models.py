"""Internal domain objects used by the planner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Point:
    latitude: float
    longitude: float
    label: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"latitude": self.latitude, "longitude": self.longitude, "label": self.label}


@dataclass
class Station:
    station_id: str
    name: str
    latitude: float
    longitude: float
    address: str = ""
    city: str = ""
    state: str = ""
    operator_name: str = ""
    network_name: str = ""
    access_type: str = "public"
    status: str = "unknown"
    connector_types: set[str] = field(default_factory=set)
    power_kw: float | None = None
    connector_count: int | None = None
    confidence_score: float = 0
    source_name: str = ""
    source_external_id: str = ""
    source_license: str = ""
    last_verified_at: str = ""


@dataclass(frozen=True)
class Route:
    points: tuple[Point, ...]
    distance_km: float
    duration_minutes: float | None
    source: str
