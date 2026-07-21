"""Public API request and response contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PointInput(APIModel):
    latitude: float = Field(ge=-90, le=90, examples=[28.6129])
    longitude: float = Field(ge=-180, le=180, examples=[77.2295])
    label: str | None = Field(default=None, max_length=300, examples=["India Gate, New Delhi"])


class VehicleInput(APIModel):
    battery_capacity_kwh: float = Field(gt=0, le=250, examples=[40.5])
    current_soc_percent: float = Field(ge=0, le=100, examples=[28])
    reserve_soc_percent: float = Field(default=15, ge=0, le=50, examples=[15])
    consumption_wh_per_km: float = Field(default=150, ge=60, le=500, examples=[150])
    safety_buffer_percent: float = Field(default=10, ge=0, le=40, examples=[10])
    connector_types: list[str] = Field(default_factory=lambda: ["ccs2", "type2"], min_length=1)
    max_ac_kw: float = Field(default=7.2, gt=0, le=50)
    max_dc_kw: float = Field(default=50, gt=0, le=500)

    @model_validator(mode="after")
    def reserve_must_not_exceed_current_charge(self) -> VehicleInput:
        if self.reserve_soc_percent > self.current_soc_percent:
            raise ValueError("reserve battery cannot be higher than the current battery")
        return self


class PreferencesInput(APIModel):
    mode: Literal["balanced", "fastest", "shortest_detour", "safest"] = "balanced"
    max_detour_km: float = Field(default=12, ge=0.5, le=80)
    minimum_station_confidence: float = Field(default=40, ge=0, le=100)
    allow_unverified_connectors: bool = True
    maximum_results: int = Field(default=5, ge=1, le=10)


class RouteInput(APIModel):
    points: list[PointInput] = Field(default_factory=list)
    distance_km: float | None = Field(default=None, gt=0, le=10000)
    duration_minutes: float | None = Field(default=None, gt=0, le=20000)
    source: str | None = Field(default=None, max_length=50)


class TripPlanRequest(APIModel):
    origin: PointInput
    destination: PointInput
    vehicle: VehicleInput
    preferences: PreferencesInput = Field(default_factory=PreferencesInput)
    route: RouteInput | None = None


class DecisionResponse(BaseModel):
    status: Literal["no_stop_needed", "stop_required", "charge_before_departure"]
    title: str
    summary: str


class PointResponse(BaseModel):
    latitude: float
    longitude: float
    label: str


class RouteResponse(BaseModel):
    distance_km: float
    duration_minutes: int | None
    source: str
    geometry: list[list[float]]
    option_index: int | None = None
    label: str | None = None


class BatteryResponse(BaseModel):
    capacity_kwh: float
    current_soc_percent: float
    reserve_soc_percent: float
    adjusted_consumption_wh_per_km: int
    energy_needed_kwh: float
    safe_available_energy_kwh: float
    safe_range_km: float
    estimated_direct_arrival_soc_percent: float
    energy_shortfall_kwh: float


class LocationResponse(BaseModel):
    latitude: float
    longitude: float


class RecommendationResponse(BaseModel):
    station_id: str
    name: str
    operator_name: str
    address: str | None
    location: LocationResponse
    connectors: list[str]
    matching_connectors: list[str]
    connector_verified: bool
    power_kw: float | None
    route_progress_percent: float
    distance_from_start_km: float
    route_deviation_km: float
    estimated_total_detour_km: float
    arrival_soc_percent: float
    suggested_target_soc_percent: float
    energy_to_add_kwh: float
    estimated_charge_minutes: int | None
    can_finish_after_charge: bool
    score: float
    confidence_score: float
    reasons: list[str]
    verification_note: str
    navigation_url: str
    source: dict[str, Any]


class RoutePlanResponse(BaseModel):
    decision: DecisionResponse
    origin: PointResponse
    destination: PointResponse
    route: RouteResponse
    battery: BatteryResponse
    recommendations: list[RecommendationResponse]
    candidate_count: int
    station_count: int
    rejected_counts: dict[str, int]
    warnings: list[str]
    assumptions: list[str]


class TripPlanResponse(RoutePlanResponse):
    route_options: list[RoutePlanResponse]


class GeocodeResult(BaseModel):
    label: str
    latitude: float
    longitude: float
    type: str


class GeocodeResponse(BaseModel):
    results: list[GeocodeResult]


class StationSummary(BaseModel):
    station_id: str
    name: str
    latitude: float
    longitude: float
    address: str | None
    city: str | None
    state: str | None
    operator_name: str | None
    status: str
    access_type: str
    connectors: list[str]
    power_kw: float | None
    confidence_score: float
    distance_km: float | None
    source_name: str | None
    source_external_id: str | None


class StationsResponse(BaseModel):
    results: list[StationSummary]
    returned: int
    total_stations: int


TRIP_PLAN_EXAMPLE: dict[str, Any] = {
    "origin": {"latitude": 28.6129, "longitude": 77.2295, "label": "India Gate, New Delhi"},
    "destination": {"latitude": 27.1767, "longitude": 78.0081, "label": "Taj Mahal, Agra"},
    "vehicle": {
        "battery_capacity_kwh": 40.5,
        "current_soc_percent": 35,
        "reserve_soc_percent": 15,
        "consumption_wh_per_km": 150,
        "safety_buffer_percent": 10,
        "connector_types": ["ccs2", "type2"],
        "max_ac_kw": 7.2,
        "max_dc_kw": 50,
    },
    "preferences": {
        "mode": "balanced",
        "max_detour_km": 12,
        "minimum_station_confidence": 40,
        "allow_unverified_connectors": True,
        "maximum_results": 5,
    },
}
