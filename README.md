# EV RouteWise

EV RouteWise is a route-aware charging-stop recommender for electric vehicles in India. A driver chooses a start and destination, enters the battery they have today, and receives road-route alternatives with reachable charging stations ranked for that specific trip.

The application is intentionally one deployable service: FastAPI serves the versioned backend, OpenAPI documentation and responsive web interface. This keeps the prototype easy to operate while leaving clean seams for a mobile client, commercial map provider and live charging network.

## Live deployment

- Web app and backend base URL: <https://ev-charging-routes.onrender.com>
- Swagger API explorer: <https://ev-charging-routes.onrender.com/docs>
- ReDoc reference: <https://ev-charging-routes.onrender.com/redoc>
- OpenAPI schema: <https://ev-charging-routes.onrender.com/openapi.json>
- Health check: <https://ev-charging-routes.onrender.com/api/v1/health>

## What the planner does

1. Converts place names to coordinates through a Nominatim-compatible geocoder.
2. Requests up to three road-route alternatives from an OSRM-compatible router.
3. Calculates usable energy above the driver's reserve, including a configurable driving-condition buffer.
4. Finds public station records inside each route corridor.
5. Removes known-incompatible, unreachable, private, closed and overly distant stations.
6. Ranks the remaining stops using connector compatibility, detour, data confidence, charging power, arrival margin and position on the route.
7. Returns a recommended target charge, estimated charge time when power is known, and a directions link.

The current planner ranks one stop per route option. Multi-stop optimisation, elevation/weather adjustment, live availability and tariff-aware ranking belong in the production roadmap.

## Run locally

Requires Python 3.13 (3.11+ also works).

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

Open:

- Web app: `http://127.0.0.1:8000`
- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

Run checks:

```bash
pytest
ruff check .
```

## API

All application endpoints are versioned under `/api/v1`.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/health` | Deployment health and loaded station count. |
| `GET` | `/api/v1/meta` | Capabilities, source coverage and provider metadata. |
| `GET` | `/api/v1/geocode?q=...` | Search Indian places. |
| `GET` | `/api/v1/stations?latitude=...&longitude=...` | Query nearby station records. |
| `POST` | `/api/v1/trips/plan` | Calculate route options and charging recommendations. |

Example:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/trips/plan \
  -H 'Content-Type: application/json' \
  -d @docs/example-trip.json
```

The exact request and response schemas, examples and validation constraints are always available in `/docs` and `/openapi.json`.

## Data and providers

The repository includes 537 OpenStreetMap-derived connector rows as a development seed. OpenStreetMap attribution and source IDs are preserved. The data is enough to exercise the recommendation pipeline, but it is not a claim of complete India coverage and does not include live charger status.

The default public Nominatim and OSRM services are suitable only for development and low-volume evaluation. Before a company launch, configure providers with an SLA and merge a verified charging feed. Good provider categories are:

- Maps/geocoding/routing: Mappls, Google Maps Platform, HERE, TomTom or Mapbox.
- Charger discovery and live status: direct CPO integrations (Tata Power EZ Charge, Statiq, ChargeZone, Jio-bp pulse, etc.) or an aggregator with explicit India coverage.
- Vehicle data, where users consent: OEM telematics or an account-linking platform for live state of charge and efficiency.

See [docs/architecture.md](docs/architecture.md) and [docs/data-pipeline.md](docs/data-pipeline.md) for the design and production roadmap.

## Configuration

| Variable | Default | Use |
|---|---|---|
| `APP_ENV` | `development` | Environment label returned by health checks. |
| `APP_VERSION` | Render commit or `2.0.0` | API and asset version. |
| `STATION_FILE` | `data/charging_stations.csv` | Station dataset path. |
| `NOMINATIM_URL` | public Nominatim | Nominatim-compatible geocoding base URL. |
| `OSRM_URL` | public OSRM | OSRM-compatible route base URL. |
| `MAP_USER_AGENT` | project URL | Identifies requests to open map services. |
| `CORS_ALLOWED_ORIGINS` | `*` | Comma-separated web/mobile client origins. |
| `EXTERNAL_TIMEOUT_SECONDS` | `15` | External provider timeout. |

## Deploy on Render

`render.yaml`, `.python-version` and `Procfile` are included. A Render web service should use:

- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 2`
- Health check: `/api/v1/health`
- Region: Singapore for Indian users

## License

Application code is MIT licensed. OpenStreetMap-derived data remains subject to the Open Database License (ODbL) and attribution requirements.
