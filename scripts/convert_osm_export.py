#!/usr/bin/env python3
"""Convert an osmium GeoJSON sequence of charging stations into the app CSV.

Example:
    osmium tags-filter india-latest.osm.pbf \
      nwr/amenity=charging_station -o charging-stations.osm.pbf
    osmium export charging-stations.osm.pbf \
      --geometry-types=point -f geojsonseq -o charging-stations.geojsonseq
    python scripts/convert_osm_export.py \
      charging-stations.geojsonseq data/charging_stations.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

COLUMNS = [
    "station_id",
    "name",
    "latitude",
    "longitude",
    "address",
    "city",
    "state",
    "country",
    "operator_name",
    "network_name",
    "access_type",
    "opening_hours",
    "status",
    "connector_type",
    "power_kw",
    "current_type",
    "connector_count",
    "payment_modes",
    "amenities",
    "source_name",
    "source_external_id",
    "source_license",
    "confidence_score",
    "last_verified_at",
]

SOCKETS = {
    "socket:ccs": "ccs2",
    "socket:ccs_combo": "ccs2",
    "socket:type2_combo": "ccs2",
    "socket:type2": "type2",
    "socket:chademo": "chademo",
    "socket:gbt": "gbt",
    "socket:gbt_dc": "gbt",
    "socket:tesla_supercharger": "tesla",
    "socket:tesla_destination": "tesla",
}


def parse_power(tags: dict[str, Any], socket_key: str | None = None) -> float | None:
    values = []
    keys = ["capacity:charging", "charging_station:output", "output"]
    if socket_key:
        keys.insert(0, f"{socket_key}:output")
    for key in keys:
        raw = str(tags.get(key) or "")
        for number, unit in re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*(kW|W)?", raw, flags=re.IGNORECASE):
            value = float(number)
            if unit.lower() == "w":
                value /= 1000
            if 0 < value <= 1000:
                values.append(value)
    return max(values) if values else None


def connector_rows(tags: dict[str, Any]) -> list[tuple[str, str | None]]:
    matches = [
        (connector, key) for key, connector in SOCKETS.items() if str(tags.get(key, "")).lower() not in {"", "0", "no"}
    ]
    return matches or [("unknown", None)]


def address(tags: dict[str, Any]) -> str:
    parts = [tags.get("addr:housenumber"), tags.get("addr:street"), tags.get("addr:suburb")]
    return ", ".join(str(part).strip() for part in parts if part)


def confidence(tags: dict[str, Any], connector: str, power: float | None) -> int:
    score = 45
    score += 10 if tags.get("name") else 0
    score += 10 if tags.get("operator") or tags.get("network") else 0
    score += 12 if connector != "unknown" else 0
    score += 8 if power else 0
    score += 5 if tags.get("opening_hours") else 0
    return min(score, 90)


def feature_rows(feature: dict[str, Any], verified_at: str) -> list[dict[str, Any]]:
    properties = feature.get("properties") or {}
    tags = properties.get("tags") if isinstance(properties.get("tags"), dict) else properties
    geometry = feature.get("geometry") or {}
    coordinates = geometry.get("coordinates") or []
    if geometry.get("type") != "Point" or len(coordinates) < 2:
        return []
    longitude, latitude = coordinates[:2]
    external_id = str(properties.get("@id") or feature.get("id") or "").replace("/", "-")
    if not external_id:
        return []
    rows = []
    for connector, socket_key in connector_rows(tags):
        power = parse_power(tags, socket_key)
        rows.append(
            {
                "station_id": f"osm-{external_id}",
                "name": tags.get("name") or f"Unnamed charging station ({tags.get('addr:city') or 'India'})",
                "latitude": latitude,
                "longitude": longitude,
                "address": address(tags),
                "city": tags.get("addr:city") or tags.get("addr:town") or "",
                "state": tags.get("addr:state") or "",
                "country": "India",
                "operator_name": tags.get("operator") or "",
                "network_name": tags.get("network") or "",
                "access_type": "public" if tags.get("access") not in {"private", "no"} else tags.get("access"),
                "opening_hours": tags.get("opening_hours") or "",
                "status": "operational" if tags.get("disused") != "yes" else "closed",
                "connector_type": connector,
                "power_kw": power or "",
                "current_type": "dc"
                if connector in {"ccs2", "chademo", "gbt", "tesla"}
                else "ac"
                if connector != "unknown"
                else "",
                "connector_count": tags.get(socket_key) if socket_key else 1,
                "payment_modes": tags.get("payment:cards") or tags.get("fee") or "",
                "amenities": "",
                "source_name": "openstreetmap",
                "source_external_id": properties.get("@id") or feature.get("id") or external_id,
                "source_license": "ODbL",
                "confidence_score": confidence(tags, connector, power),
                "last_verified_at": verified_at,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="GeoJSON sequence created by osmium export")
    parser.add_argument("output", type=Path, help="Destination CSV")
    args = parser.parse_args()
    verified_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    rows: list[dict[str, Any]] = []
    with args.input.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            cleaned = line.strip().lstrip("\x1e")
            if not cleaned:
                continue
            try:
                rows.extend(feature_rows(json.loads(cleaned), verified_at))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"Invalid JSON on line {line_number}: {exc}") from exc
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} connector rows to {args.output}")


if __name__ == "__main__":
    main()
