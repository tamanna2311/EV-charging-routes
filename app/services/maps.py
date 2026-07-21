"""Async clients for geocoding and road-route alternatives."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from app.config import Settings
from app.domain.models import Point


class MapProviderError(RuntimeError):
    """Raised when the configured map provider cannot serve a request."""


class OpenMapProvider:
    """Low-volume development provider backed by public Nominatim and OSRM."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.AsyncClient(
            timeout=settings.external_timeout_seconds,
            headers={"User-Agent": settings.map_user_agent, "Accept": "application/json"},
        )
        self._geocode_lock = asyncio.Lock()
        self._last_geocode_request = 0.0

    async def close(self) -> None:
        await self.client.aclose()

    async def geocode(self, query: str) -> list[dict[str, Any]]:
        cleaned = " ".join(query.split())
        if len(cleaned) < 3:
            return []
        # The public Nominatim service requires a maximum of one request/second.
        async with self._geocode_lock:
            delay = 1.05 - (time.monotonic() - self._last_geocode_request)
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_geocode_request = time.monotonic()
            try:
                response = await self.client.get(
                    f"{self.settings.nominatim_url.rstrip('/')}/search",
                    params={
                        "q": cleaned,
                        "format": "jsonv2",
                        "limit": 5,
                        "countrycodes": "in",
                        "addressdetails": 1,
                    },
                )
                response.raise_for_status()
                raw_results = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise MapProviderError("Location search is temporarily unavailable") from exc

        results: list[dict[str, Any]] = []
        for item in raw_results:
            try:
                results.append(
                    {
                        "label": item["display_name"],
                        "latitude": float(item["lat"]),
                        "longitude": float(item["lon"]),
                        "type": item.get("type", "place"),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
        return results

    @staticmethod
    def _format_route(route: dict[str, Any], route_index: int) -> dict[str, Any]:
        points = [
            {"latitude": float(latitude), "longitude": float(longitude), "label": ""}
            for longitude, latitude in route["geometry"]["coordinates"]
        ]
        return {
            "points": points,
            "distance_km": float(route["distance"]) / 1000,
            "duration_minutes": float(route["duration"]) / 60,
            "source": "osrm",
            "route_index": route_index,
        }

    async def routes(self, origin: Point, destination: Point) -> list[dict[str, Any]]:
        coordinates = (
            f"{origin.longitude:.6f},{origin.latitude:.6f};{destination.longitude:.6f},{destination.latitude:.6f}"
        )
        try:
            response = await self.client.get(
                f"{self.settings.osrm_url.rstrip('/')}/route/v1/driving/{coordinates}",
                params={"overview": "full", "geometries": "geojson", "steps": "false", "alternatives": "true"},
            )
            response.raise_for_status()
            data = response.json()
            if data.get("code") != "Ok" or not data.get("routes"):
                raise MapProviderError("No drivable route was found between these places")
            return [self._format_route(route, index) for index, route in enumerate(data["routes"][:3])]
        except MapProviderError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise MapProviderError("Live road routing is temporarily unavailable") from exc

    async def routes_or_fallback(self, origin: Point, destination: Point) -> list[dict[str, Any]]:
        try:
            return await self.routes(origin, destination)
        except MapProviderError:
            return [
                {"points": [], "distance_km": None, "duration_minutes": None, "source": "estimated", "route_index": 0}
            ]
