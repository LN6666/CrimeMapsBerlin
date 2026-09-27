"""Deterministic metric geometry and report-to-place associations.

Hexagons follow PostGIS ST_HexagonGrid's flat-top, origin-anchored layout.
EPSG:25833 gives Berlin ground metres; display geometry is WGS84.
No association is a probability or a claim against an individual business.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict

from pyproj import Transformer
from shapely.geometry import Point, Polygon, mapping, shape
from shapely.ops import transform
from shapely.strtree import STRtree

TO_METRIC = Transformer.from_crs(4326, 25833, always_xy=True).transform
TO_WGS = Transformer.from_crs(25833, 4326, always_xy=True).transform
HEX_SIZES = {"overview": 1100, "detail": 275}
POI_RADIUS_M = 50
MAPPABLE_PRECISIONS = {"point", "street", "place", "address"}


def feature(geometry, properties):
    return {"type": "Feature", "geometry": mapping(geometry), "properties": properties}


def collection(features):
    return {"type": "FeatureCollection", "features": features}


def cell_for(lon: float, lat: float, size: float):
    if size <= 0 or not (-180 <= lon <= 180 and -90 < lat < 90):
        raise ValueError("Invalid point or hexagon size")
    x, y = TO_METRIC(lon, lat)
    col = round(x / (1.5 * size))
    candidates = []
    height = math.sqrt(3) * size
    for i in range(col - 1, col + 2):
        row = round(y / height - (i % 2) / 2)
        for j in range(row - 1, row + 2):
            cx, cy = 1.5 * size * i, height * (j + (i % 2) / 2)
            candidates.append(((x - cx) ** 2 + (y - cy) ** 2, i, j, cx, cy))
    _, i, j, cx, cy = min(candidates)  # stable tie break on cell boundary
    polygon = Polygon(
        [(cx + size * math.cos(k * math.pi / 3), cy + size * math.sin(k * math.pi / 3)) for k in range(6)]
    )
    return f"{size}:{i}:{j}", transform(TO_WGS, polygon)


def hexagons(events: list[dict], size: float):
    groups = defaultdict(list)
    geometries = {}
    for e in events:
        if e["location_precision"] not in MAPPABLE_PRECISIONS or not e.get("coordinates"):
            continue
        key, geometry = cell_for(*e["coordinates"], size)
        groups[key].append(e)
        geometries[key] = geometry
    return collection(
        [
            feature(
                geometries[key],
                {
                    "id": key,
                    "edge_m": size,
                    "count": len(rows),
                    "event_ids": [e["id"] for e in rows],
                    "categories": dict(Counter(e["category"] for e in rows)),
                    "outcomes": dict(Counter(e.get("outcome", "unknown") for e in rows)),
                    "approximate_count": sum(e["location_precision"] != "point" for e in rows),
                },
            )
            for key, rows in sorted(groups.items())
        ]
    )


def classify_poi(tags: dict) -> str | None:
    amenity = tags.get("amenity")
    if amenity in {"bar", "pub"}:
        return "bar"
    if amenity in {"nightclub", "restaurant", "cafe", "fast_food", "marketplace", "parking"}:
        return amenity
    if (
        amenity == "bus_station"
        or tags.get("railway") == "station"
        or tags.get("building") == "train_station"
    ):
        return "station"
    if tags.get("aeroway") == "terminal":
        return "airport"
    if tags.get("shop") in {"mall", "department_store", "supermarket", "convenience"}:
        return "shop"
    if tags.get("tourism") in {"attraction", "museum"}:
        return "attraction"
    if tags.get("tourism") == "hotel":
        return "hotel"
    if tags.get("leisure") == "park":
        return "park"
    return None


def osm_geometry(element: dict):
    if element.get("geojson_geometry"):
        return shape(element["geojson_geometry"])
    if element["type"] == "node":
        return Point(element["lon"], element["lat"])
    coords = [(p["lon"], p["lat"]) for p in element.get("geometry", [])]
    if len(coords) >= 4 and coords[0] == coords[-1]:
        polygon = Polygon(coords)
        if polygon.is_valid and not polygon.is_empty:
            return polygon
    # Relations/stop_area do not necessarily describe a footprint. Do not invent one.
    return None


def pois_from_osm(payload: dict):
    features = []
    rejected = Counter()
    for item in payload["elements"]:
        tags = item.get("tags", {})
        kind = classify_poi(tags)
        if not kind:
            continue
        geometry = osm_geometry(item)
        if geometry is None:
            rejected["missing_or_unsupported_geometry"] += 1
            continue
        if geometry.geom_type == "Point":
            center = geometry
        else:
            center = geometry.representative_point()
        footprint_kind = kind in {
            "station",
            "airport",
            "park",
            "parking",
            "marketplace",
            "shop",
            "attraction",
        }
        if kind in {"station", "airport"}:
            display = geometry
            mode = "osm_footprint" if geometry.geom_type != "Point" else "footprint_missing"
        elif footprint_kind and geometry.geom_type != "Point":
            display, mode = geometry, "osm_footprint"
        else:
            display = transform(TO_WGS, transform(TO_METRIC, center).buffer(POI_RADIUS_M, quad_segs=8))
            mode = "50m_circle"
        place = feature(
            display,
            {
                "id": f"osm/{item['type']}/{item['id']}",
                "name": tags.get("name", kind),
                "aliases": [
                    v
                    for key in ("alt_name", "official_name", "short_name", "loc_name")
                    for v in tags.get(key, "").split(";")
                    if v
                ],
                "kind": kind,
                "geometry_mode": mode,
                "center": [center.x, center.y],
                "source_url": f"https://www.openstreetmap.org/{item['type']}/{item['id']}",
                "opening_hours": tags.get("opening_hours"),
                "wikidata": tags.get("wikidata"),
            },
        )
        place["location_geometry"] = mapping(geometry)
        features.append(place)
    # Collapse a same-type, same-name node lying inside an area footprint/circle from a way.
    areas = [f for f in features if f["properties"]["geometry_mode"] == "osm_footprint"]
    area_geoms = [shape(f["geometry"]) for f in areas]
    tree = STRtree(area_geoms)
    deduped = []
    for f in features:
        p = f["properties"]
        if "/node/" in p["id"]:
            point = Point(p["center"])
            duplicates = [areas[int(i)] for i in tree.query(point, predicate="intersects")]
            if any(
                a["properties"]["name"] == p["name"] and a["properties"]["kind"] == p["kind"]
                for a in duplicates
            ):
                rejected["duplicate_node_in_way"] += 1
                continue
        deduped.append(f)
    return collection(deduped), dict(rejected)


def associate(events: list[dict], pois: dict, matching_types_only: bool = True):
    """Match to 50m circles or station footprint. Count each report once per POI.

    Street-level geocodes generate candidates, not confirmed venue attribution.
    District geocodes never cause 50m association or polygon containment.
    """
    places = pois["features"]
    place_by_id = {f["properties"]["id"]: f for f in places}
    metric = [transform(TO_METRIC, shape(f["geometry"])) for f in places]
    tree = STRtree(metric)
    links = []
    seen = set()
    for event in events:
        if not event.get("poi_mentions") or event["location_precision"] not in MAPPABLE_PRECISIONS:
            continue
        if not event.get("coordinates"):
            continue
        if event["location_precision"] == "place":
            # A park/station representative must not accidentally darken unrelated neighbours.
            for ident in event.get("location_object_ids", []):
                f = place_by_id.get(ident)
                if f is None:
                    continue
                p = f["properties"]
                if not matching_types_only or p["kind"] in event["poi_mentions"]:
                    links.append(
                        dict(
                            event_id=event["id"],
                            poi_id=p["id"],
                            status="named_place_candidate",
                            source_url=event["source_url"],
                            mention_basis=event["mention_basis"],
                        )
                    )
            continue
        point = transform(TO_METRIC, Point(event["coordinates"]))
        for idx in tree.query(point, predicate="intersects"):
            p = places[int(idx)]["properties"]
            if p["geometry_mode"] == "footprint_missing":
                continue
            if matching_types_only and p["kind"] not in event["poi_mentions"]:
                continue
            pair = event["id"], p["id"]
            if pair in seen:
                continue
            seen.add(pair)
            links.append(
                {
                    "event_id": event["id"],
                    "poi_id": p["id"],
                    "status": "nearby_type_match"
                    if event["location_precision"] == "point"
                    else "approximate_candidate",
                    "source_url": event["source_url"],
                    "mention_basis": event["mention_basis"],
                }
            )
    return links


def build_months(events: list[dict], pois: dict):
    months = {}
    seen = set()
    for e in events:
        if e["id"] in seen:
            raise ValueError("Duplicate event id")
        seen.add(e["id"])
        # Unknown dates must not be silently assigned to the fetch month.
        if e.get("month") is None:
            continue
        months.setdefault(e["month"], []).append(e)
    return {
        month: {
            "event_ids": [e["id"] for e in rows],
            "hex": {name: hexagons(rows, size) for name, size in HEX_SIZES.items()},
            "links": associate(rows, pois),
        }
        for month, rows in sorted(months.items())
    }
