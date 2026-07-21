# Charging-station data

`charging_stations.csv` is an OpenStreetMap-derived seed dataset for India. It is useful for developing the route-matching and recommendation flow, but it is not a complete national registry and it does not provide live charger availability.

Important fields:

| Field | Why the planner needs it |
|---|---|
| `latitude`, `longitude` | Match a station to a road-route corridor and estimate detour. |
| `connector_type` | Reject stations that are known to be incompatible with the EV. |
| `power_kw` | Estimate charging time and support the “faster charging” preference. |
| `access_type`, `status` | Avoid private, closed or unavailable records. |
| `confidence_score` | Prefer records with more complete station details. |
| `source_*`, `last_verified_at` | Preserve provenance and freshness for audits. |

The current file contains 537 connector rows exported from OpenStreetMap. Run `python scripts/convert_osm_export.py --help` to rebuild it from an `osmium export` GeoJSON sequence. For a production launch, merge this seed with an operator or commercial feed that includes station IDs, live status, connector availability, tariffs and verified power.

