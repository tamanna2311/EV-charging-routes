# Charging-station data pipeline

## What is collected

The planner needs one canonical station record with location, public-access status, connector types, charging power, operator, source identity and verification time. Optional fields such as address, opening hours, payment modes, amenities and connector count improve the user experience and confidence score.

Coordinates alone are enough to draw a dot, but not enough to recommend it safely. Connector, power, status and freshness decide whether the station is useful for a particular driver.

## Current OpenStreetMap seed

The checked-in CSV was derived from OpenStreetMap features tagged `amenity=charging_station`. OpenStreetMap is free open data under ODbL; it is not a paid API. The local extract avoids calling Overpass for every user request and preserves the OSM element ID for provenance.

The reproducible process is:

```bash
# Download India from https://download.geofabrik.de/asia/india.html
osmium tags-filter india-latest.osm.pbf \
  nwr/amenity=charging_station \
  -o charging-stations.osm.pbf

osmium export charging-stations.osm.pbf \
  --geometry-types=point \
  -f geojsonseq \
  -o charging-stations.geojsonseq

python scripts/convert_osm_export.py \
  charging-stations.geojsonseq \
  data/charging_stations.csv
```

The converter maps OSM socket tags to canonical connectors, keeps unknown connector data explicitly unknown, parses available power values, calculates a completeness-based confidence score and records an ISO verification timestamp.

## Why the number is lower than reported national totals

Government or industry reports may cite tens of thousands of registered or operational public chargers in India. That figure does not mean all records are openly downloadable with coordinates, connector metadata and live status. OpenStreetMap only contains stations contributed and maintained by its community, so this repository must not present its row count as the national total.

## Production sources

Use a layered strategy rather than trusting one file:

1. Government open-data catalogues for official counts and static registered locations where downloadable terms permit use.
2. Direct charging-point-operator integrations for authoritative connector, power, tariff and live availability data.
3. Commercial aggregators for faster network breadth, after verifying India coverage and redistribution rights.
4. OpenStreetMap as a coverage backstop and source of community corrections.
5. User reports as queued evidence, not immediate truth; verify before changing operational status.

Every source should retain its original ID, license, retrieval time and verification status. Never silently overwrite a higher-authority field with a lower-authority value.

## Recommended normalized model

For Postgres/PostGIS, separate these concepts:

- `stations`: physical site, location, operator, address and access.
- `charge_points`: individual charger/EVSE identity and status.
- `connectors`: plug type, power, current type, tariff and live availability.
- `source_records`: provider ID, raw payload hash, license and retrieval time.
- `status_events`: time-series operational/availability updates.
- `verification_events`: operator, automated and user verification history.

The API can then return a stable internal station ID while exposing source provenance for auditing.

## Quality gates

An ingestion job should reject invalid coordinates and impossible power values; normalize connector names; de-duplicate nearby records; flag stale live data; compare source totals against historical ranges; and publish coverage, completeness and freshness dashboards. A station should only be described as “live” when the latest provider event is recent enough for that provider's SLA.

