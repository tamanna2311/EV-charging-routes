from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.models import Station
from app.main import create_app
from app.services.stations import StationRepository


class FakeMapProvider:
    async def close(self) -> None:
        return None

    async def geocode(self, query: str) -> list[dict[str, Any]]:
        return [{"label": f"{query}, India", "latitude": 28.6, "longitude": 77.2, "type": "place"}]

    async def routes_or_fallback(self, _origin, _destination) -> list[dict[str, Any]]:
        raise AssertionError("A supplied route should avoid external routing")


@pytest.fixture
def client() -> TestClient:
    repository = StationRepository(
        [
            Station(
                station_id="sample",
                name="Sample charger",
                latitude=28.60,
                longitude=77.25,
                connector_types={"ccs2"},
                power_kw=50,
                confidence_score=80,
                status="operational",
                source_name="test",
            )
        ],
        Path("sample.csv"),
    )
    app = create_app(Settings(environment="test"), repository, FakeMapProvider())
    with TestClient(app) as test_client:
        yield test_client


def supplied_trip() -> dict[str, Any]:
    return {
        "origin": {"latitude": 28.60, "longitude": 77.20, "label": "Start"},
        "destination": {"latitude": 28.60, "longitude": 77.50, "label": "End"},
        "vehicle": {
            "battery_capacity_kwh": 40,
            "current_soc_percent": 20,
            "reserve_soc_percent": 10,
            "consumption_wh_per_km": 150,
            "connector_types": ["ccs2"],
        },
        "preferences": {"allow_unverified_connectors": True},
        "route": {
            "points": [
                {"latitude": 28.60, "longitude": 77.20},
                {"latitude": 28.60, "longitude": 77.50},
            ],
            "distance_km": 30,
            "duration_minutes": 45,
            "source": "test-route",
        },
    }


def test_health_and_metadata_report_loaded_data(client: TestClient) -> None:
    health = client.get("/api/v1/health")
    metadata = client.get("/api/v1/meta")
    assert health.status_code == 200
    assert health.json()["stations_loaded"] == 1
    assert metadata.json()["data"]["total_stations"] == 1


def test_openapi_exposes_versioned_endpoints(client: TestClient) -> None:
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    assert schema.json()["info"]["title"] == "EV RouteWise API"
    assert "/api/v1/trips/plan" in schema.json()["paths"]
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200


def test_plan_with_supplied_route_returns_actionable_result(client: TestClient) -> None:
    response = client.post("/api/v1/trips/plan", json=supplied_trip())
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["route"]["distance_km"] == 30
    assert data["route"]["label"] == "Recommended route"
    assert len(data["route_options"]) == 1
    assert data["recommendations"][0]["station_id"] == "sample"


def test_nearby_station_endpoint_is_bounded(client: TestClient) -> None:
    response = client.get("/api/v1/stations?latitude=28.60&longitude=77.20&radius_km=20")
    assert response.status_code == 200
    assert response.json()["returned"] == 1
    assert response.json()["results"][0]["distance_km"] > 0


def test_validation_errors_have_stable_shape(client: TestClient) -> None:
    response = client.post("/api/v1/trips/plan", json={"origin": {}})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["details"]


def test_root_serves_the_route_planner(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Plan my charging route" in response.text
    assert client.head("/").status_code == 200
