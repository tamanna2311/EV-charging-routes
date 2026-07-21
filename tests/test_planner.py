from app.domain.models import Station
from app.domain.planner import recommend_stations


def trip(current_soc: float = 30, connector: str = "ccs2") -> dict:
    return {
        "origin": {"label": "Start", "latitude": 28.60, "longitude": 77.20},
        "destination": {"label": "End", "latitude": 28.60, "longitude": 77.50},
        "vehicle": {
            "battery_capacity_kwh": 40,
            "current_soc_percent": current_soc,
            "reserve_soc_percent": 10,
            "consumption_wh_per_km": 150,
            "safety_buffer_percent": 0,
            "connector_types": [connector],
            "max_ac_kw": 7.2,
            "max_dc_kw": 50,
        },
        "preferences": {
            "max_detour_km": 10,
            "maximum_results": 5,
            "minimum_station_confidence": 40,
            "allow_unverified_connectors": False,
            "mode": "balanced",
        },
        "route": {
            "points": [
                {"latitude": 28.60, "longitude": 77.20},
                {"latitude": 28.60, "longitude": 77.50},
            ],
            "distance_km": 30,
            "duration_minutes": 45,
            "source": "osrm",
        },
    }


def station(station_id: str, longitude: float, connectors: set[str] | None = None, power: float | None = 50) -> Station:
    return Station(
        station_id=station_id,
        name=f"Station {station_id}",
        latitude=28.60,
        longitude=longitude,
        connector_types=connectors or {"ccs2"},
        power_kw=power,
        confidence_score=80,
        access_type="public",
        status="operational",
        source_name="test",
    )


def test_direct_trip_does_not_require_a_stop() -> None:
    result = recommend_stations(trip(current_soc=40), [station("one", 77.35)])
    assert result["decision"]["status"] == "no_stop_needed"
    assert result["battery"]["estimated_direct_arrival_soc_percent"] > 10


def test_reachable_station_has_actionable_charge_target() -> None:
    result = recommend_stations(trip(current_soc=20), [station("early", 77.25)])
    recommendation = result["recommendations"][0]
    assert result["decision"]["status"] == "stop_required"
    assert recommendation["connector_verified"] is True
    assert recommendation["arrival_soc_percent"] >= 10
    assert recommendation["suggested_target_soc_percent"] > recommendation["arrival_soc_percent"]
    assert recommendation["navigation_url"].startswith("https://www.google.com/maps/dir/")


def test_station_below_reserve_is_not_recommended() -> None:
    result = recommend_stations(trip(current_soc=15), [station("late", 77.44)])
    assert result["decision"]["status"] == "charge_before_departure"
    assert result["recommendations"] == []
    assert result["rejected_counts"]["unreachable_before_reserve"] == 1


def test_incompatible_connector_is_rejected() -> None:
    result = recommend_stations(trip(current_soc=20), [station("wrong", 77.25, {"chademo"})])
    assert result["recommendations"] == []
    assert result["rejected_counts"]["incompatible_connector"] == 1


def test_unknown_connector_is_only_returned_when_allowed() -> None:
    payload = trip(current_soc=20)
    payload["preferences"]["allow_unverified_connectors"] = True
    result = recommend_stations(payload, [station("unknown", 77.25, {"unknown"}, None)])
    assert result["recommendations"][0]["connector_verified"] is False
    assert "confirm" in result["recommendations"][0]["verification_note"].lower()
