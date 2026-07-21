"""FastAPI entrypoint for the EV RouteWise web application."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import ROOT, Settings
from app.domain.planner import InputError, parse_point, recommend_stations
from app.schemas import (
    TRIP_PLAN_EXAMPLE,
    GeocodeResponse,
    StationsResponse,
    TripPlanRequest,
    TripPlanResponse,
)
from app.services.maps import MapProviderError, OpenMapProvider
from app.services.stations import StationRepository

templates = Jinja2Templates(directory=str(ROOT / "templates"))


def _error(code: str, message: str, details: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        payload["details"] = details
    return {"error": payload}


def create_app(
    settings: Settings | None = None,
    station_repository: StationRepository | None = None,
    map_provider: OpenMapProvider | None = None,
) -> FastAPI:
    settings = settings or Settings()
    repository = station_repository or StationRepository.from_csv(settings.station_file)
    provider = map_provider or OpenMapProvider(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        await provider.close()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        summary="Plan EV routes and rank reachable charging stops.",
        description=(
            "A versioned API for Indian EV route planning. It combines road-route alternatives, "
            "vehicle energy inputs and a source-attributed charging-station dataset."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact={"name": "EV RouteWise engineering", "url": "https://github.com/tamanna2311/EV-charging-routes"},
        license_info={"name": "MIT"},
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.stations = repository
    app.state.maps = provider

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
    )
    app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

    @app.middleware("http")
    async def request_controls(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > settings.max_request_bytes:
                    return JSONResponse(_error("REQUEST_TOO_LARGE", "The request body is too large."), status_code=413)
            except ValueError:
                pass
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(self)"
        return response

    @app.exception_handler(HTTPException)
    async def handle_http_error(_request: Request, exc: HTTPException):
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            payload = {"error": exc.detail}
        else:
            payload = _error("HTTP_ERROR", str(exc.detail))
        return JSONResponse(payload, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_request: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(part) for part in error["loc"] if part != "body"), "message": error["msg"]}
            for error in exc.errors()
        ]
        return JSONResponse(_error("VALIDATION_ERROR", "Please check the trip details.", details), status_code=422)

    @app.get("/", include_in_schema=False)
    async def index(request: Request):
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "station_count": len(repository.stations),
                "asset_version": settings.app_version,
                "environment": settings.environment,
            },
        )

    @app.get("/api/v1/health", tags=["System"], summary="Service health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": settings.app_version,
            "environment": settings.environment,
            "stations_loaded": len(repository.stations),
        }

    @app.get("/api/v1/meta", tags=["System"], summary="Data and capability metadata")
    async def metadata() -> dict[str, Any]:
        return {
            "service": settings.app_name,
            "version": settings.app_version,
            "capabilities": ["india_geocoding", "road_route_alternatives", "single_stop_recommendations"],
            "data": {
                **repository.statistics(),
                "coverage": "OpenStreetMap records present in this repository; not a complete national registry",
                "license": "ODbL for OpenStreetMap-derived rows",
            },
            "providers": {"geocoding": "Nominatim-compatible", "routing": "OSRM-compatible"},
        }

    @app.get("/api/v1/geocode", response_model=GeocodeResponse, tags=["Maps"], summary="Search Indian places")
    async def geocode_location(
        q: str = Query(min_length=3, max_length=200, examples=["India Gate, New Delhi"]),
    ) -> dict[str, Any]:
        try:
            return {"results": await provider.geocode(q.strip())}
        except MapProviderError as exc:
            raise HTTPException(503, {"code": "MAP_PROVIDER_UNAVAILABLE", "message": str(exc)}) from exc

    @app.get(
        "/api/v1/stations", response_model=StationsResponse, tags=["Stations"], summary="Find nearby station records"
    )
    async def nearby_stations(
        latitude: float = Query(ge=-90, le=90, examples=[28.6129]),
        longitude: float = Query(ge=-180, le=180, examples=[77.2295]),
        radius_km: float = Query(default=25, gt=0, le=100),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        results = repository.nearby(latitude, longitude, radius_km, limit)
        return {"results": results, "returned": len(results), "total_stations": len(repository.stations)}

    @app.post(
        "/api/v1/trips/plan",
        response_model=TripPlanResponse,
        tags=["Trip planning"],
        summary="Plan a trip and rank charging stops",
    )
    async def plan_trip(trip: TripPlanRequest = Body(examples=[TRIP_PLAN_EXAMPLE])) -> dict[str, Any]:
        payload = trip.model_dump(mode="json", exclude_none=True)
        try:
            origin = parse_point(payload["origin"], "origin")
            destination = parse_point(payload["destination"], "destination")
            supplied = payload.get("route") if isinstance(payload.get("route"), dict) else {}
            if supplied.get("points") and supplied.get("distance_km"):
                route_options = [supplied]
            else:
                route_options = await provider.routes_or_fallback(origin, destination)
            plans = [recommend_stations(payload, repository.stations, route) for route in route_options]
            labels = ["Recommended route", "Alternative route", "Second alternative"]
            for index, plan in enumerate(plans):
                plan["route"]["option_index"] = index
                plan["route"]["label"] = labels[index] if index < len(labels) else f"Route {index + 1}"
            return {**plans[0], "route_options": plans}
        except InputError as exc:
            raise HTTPException(400, {"code": "INVALID_TRIP", "message": str(exc)}) from exc

    return app


app = create_app()
