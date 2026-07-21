"""Environment-backed application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    app_name: str = "EV RouteWise API"
    app_version: str = os.getenv("APP_VERSION", os.getenv("RENDER_GIT_COMMIT", "2.0.0")[:8])
    environment: str = os.getenv("APP_ENV", "development")
    station_file: Path = Path(os.getenv("STATION_FILE", ROOT / "data" / "charging_stations.csv"))
    nominatim_url: str = os.getenv("NOMINATIM_URL", "https://nominatim.openstreetmap.org")
    osrm_url: str = os.getenv("OSRM_URL", "https://router.project-osrm.org")
    map_user_agent: str = os.getenv(
        "MAP_USER_AGENT",
        "EVRouteWise/2.0 (+https://github.com/tamanna2311/EV-charging-routes)",
    )
    cors_allowed_origins: str = os.getenv("CORS_ALLOWED_ORIGINS", "*")
    external_timeout_seconds: float = float(os.getenv("EXTERNAL_TIMEOUT_SECONDS", "15"))
    max_request_bytes: int = int(os.getenv("MAX_REQUEST_BYTES", str(128 * 1024)))

    @property
    def allowed_origins(self) -> list[str]:
        if self.cors_allowed_origins.strip() == "*":
            return ["*"]
        return [item.strip() for item in self.cors_allowed_origins.split(",") if item.strip()]
