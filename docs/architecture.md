# Architecture and recommendation design

## The product problem

A normal station finder answers “which chargers are near me?” That is not enough during a journey. The useful question is: “given my route, battery, reserve and connector, which stop can I actually reach and which one helps me finish the trip with the least risk?”

EV RouteWise treats the route as the primary object. Each route alternative is evaluated independently, so a driver can compare both the road path and the charging consequence of choosing it.

## System boundaries

```text
Web or mobile client
        |
        v
FastAPI /api/v1
  |          |             |
  v          v             v
Geocoder   Road router   Station repository
  |          |             |
  +----------+-------------+
             |
             v
      Recommendation engine
             |
             v
  Route options + reachable stops
```

- `app/main.py` owns HTTP contracts, validation, errors, security headers and static delivery.
- `app/services/maps.py` isolates geocoding and routing providers. The public Nominatim/OSRM defaults can be replaced with compatible hosted services through environment variables.
- `app/services/stations.py` loads, de-duplicates, reports and spatially queries station records.
- `app/domain/planner.py` contains pure energy, reachability and ranking logic. It does not know about FastAPI or HTML, so it can be reused by another API or batch process.
- `app/schemas.py` is the versioned public contract shown in OpenAPI.

## Inputs and why they matter

| Input | How it is used |
|---|---|
| Origin and destination | Produce road routes and order stops along each route. |
| Battery capacity (kWh) | Converts percentage state of charge into actual available energy. |
| Current state of charge | Determines how far the vehicle can travel before charging. |
| Reserve state of charge | Prevents recommending a station that is technically reachable only by arriving nearly empty. |
| Consumption (Wh/km) | Converts route distance into required energy. |
| Safety buffer | Accounts for speed, traffic, weather, load and imperfect efficiency estimates. |
| Connector types | Rejects known-incompatible stations. |
| Maximum AC/DC rate | Caps the charging-time estimate at what the vehicle can accept. |
| Maximum detour | Defines the station corridor around the route. |
| Ranking mode | Changes the relative importance of power, detour, confidence and battery margin. |

## Energy model

The planner computes:

```text
adjusted consumption = nominal Wh/km × (1 + safety buffer)
trip energy          = road distance × adjusted consumption
safe available      = battery energy now − reserve energy
safe range           = safe available ÷ adjusted consumption
arrival SOC          = energy remaining at a route position ÷ battery capacity
```

Station reachability is checked against the reserve, not against zero percent. This is why the same station may be recommended for a driver starting at 35% and rejected for one starting at 20%.

## Candidate filtering

The engine first uses a route bounding box to avoid expensive projection work for stations far from the trip. It then removes records that are:

- outside the driver's total-detour limit;
- private, closed or unavailable;
- below the minimum data-confidence threshold;
- known to have no compatible connector;
- reachable only after the reserve would be consumed.

Stations without connector details may be included only when the request allows unverified records. They are visibly marked and never described as verified.

## Ranking

Every feasible candidate receives a weighted score from six normalized signals:

1. Verified connector match.
2. Estimated total detour.
3. Station-data confidence.
4. Effective charging power, capped by the vehicle.
5. Battery margin on arrival.
6. Position relative to the ideal stop point on the route.

The `balanced`, `fastest`, `shortest_detour` and `safest` modes change these weights. The numeric score is an internal ranking mechanism; the driver sees explanations such as “Compatible connector”, “Under 1 km from your route” and “Comfortable arrival battery”.

## Route alternatives

The route provider is asked for up to three alternatives. Each geometry is evaluated separately and returned as a complete route plan. The UI draws the alternatives together, highlights the selected path and refreshes station recommendations when the driver switches routes.

If the router is unavailable, the engine uses a clearly labelled straight-line estimate multiplied by a conservative road factor. This keeps the application usable for evaluation while warning the driver not to treat the estimate as navigation.

## Reliability and API design

- Public endpoints are versioned under `/api/v1`.
- Pydantic rejects missing, out-of-range and unexpected fields.
- Errors use a stable `{ "error": { "code", "message", "details" } }` envelope.
- Request bodies are size-limited and every response receives a request ID.
- Health checks confirm both the process and station data are available.
- Swagger, ReDoc and the OpenAPI schema are generated from the same contracts used at runtime.
- External provider failures have bounded timeouts and route planning has an explicit estimated fallback.

## Production evolution

The current system is a strong MVP, not yet a navigation safety system. A company launch should add:

1. A contracted maps provider or self-hosted routing/geocoding stack with rate guarantees.
2. A normalized Postgres/PostGIS station store rather than loading CSV at process start.
3. Scheduled ingestion, validation, de-duplication and freshness monitoring for every source.
4. Live CPO availability, operational status, tariffs and connector-level occupancy.
5. Multi-stop graph search for trips longer than one charging leg.
6. Elevation, weather, speed, HVAC and battery-temperature adjustments.
7. Vehicle profiles and consented live SOC through OEM integrations.
8. Authentication, per-client quotas, audit logs, SLOs and provider observability.

