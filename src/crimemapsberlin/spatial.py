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


def metric_transforms(epsg: int):
    """Use each city's metric CRS; Berlin defaults below remain stable."""
    return (
        Transformer.from_crs(4326, epsg, always_xy=True).transform,
        Transformer.from_crs(epsg, 4326, always_xy=True).transform,
    )


TO_METRIC, TO_WGS = metric_transforms(25833)
HEX_SIZES = {"overview": 1100, "detail": 275}
POI_RADIUS_M = 50
MAPPABLE_PRECISIONS = {"point", "street", "place", "address"}


def _valid_coordinates(coordinates):
    return (
        isinstance(coordinates, (list, tuple))
        and len(coordinates) >= 2
        and all(type(value) in {int, float} and math.isfinite(value) for value in coordinates[:2])
        and -180 <= coordinates[0] <= 180
        and -90 < coordinates[1] < 90
    )


def count_location(event: dict) -> dict | None:
    """Return one source-backed count point per announcement, or no count point.

    Older published events have no scene array and keep their existing top-level
    location. Scene-aware events must explicitly identify a single primary point.
    """
    if "scene_locations" not in event:
        return event if (
            event.get("location_precision") in MAPPABLE_PRECISIONS
            and event.get("coordinates")
        ) else None
    scenes = event["scene_locations"]
    if not isinstance(scenes, list) or not all(isinstance(scene, dict) for scene in scenes):
        raise ValueError(f"Invalid scene_locations for {event.get('id')}")
    if event.get("candidate_road_geometry") is not None:
        raise ValueError(f"Duplicate top-level scene road for {event.get('id')}")
    if any(type(scene.get("primary_for_count")) is not bool for scene in scenes):
        raise ValueError(f"Missing scene primary marker for {event.get('id')}")
    primaries = [scene for scene in scenes if scene["primary_for_count"]]
    if len(primaries) > 1:
        raise ValueError(f"Multiple count scenes for {event.get('id')}")
    if not primaries:
        if event.get("coordinates") is not None:
            raise ValueError(f"Top-level point without count scene for {event.get('id')}")
        return None
    primary = primaries[0]
    if str(primary.get("geometry_usage", "")).endswith("reference_only"):
        raise ValueError(f"Display reference cannot be a count scene for {event.get('id')}")
    point = primary.get("coordinates")
    geometry = primary.get("geometry")
    if geometry is not None and not isinstance(geometry, dict):
        raise ValueError(f"Invalid count scene geometry for {event.get('id')}")
    geometry_point = geometry.get("coordinates") if geometry and geometry.get("type") == "Point" else None
    if point is None:
        point = geometry_point
    if (
        primary.get("location_precision") not in MAPPABLE_PRECISIONS
        or not _valid_coordinates(point)
        or (geometry_point is not None and (
            not _valid_coordinates(geometry_point)
            or list(geometry_point[:2]) != list(point[:2])
        ))
    ):
        raise ValueError(f"Invalid count scene point for {event.get('id')}")
    if (
        not _valid_coordinates(event.get("coordinates"))
        or list(event["coordinates"][:2]) != list(point[:2])
        or event.get("location_precision") != primary["location_precision"]
        or event.get("location_label") != primary.get("label")
    ):
        raise ValueError(f"Top-level location differs from count scene for {event.get('id')}")
    return dict(primary, coordinates=list(point[:2]))


def feature(geometry, properties):
    return {"type": "Feature", "geometry": mapping(geometry), "properties": properties}


def collection(features):
    return {"type": "FeatureCollection", "features": features}


def cell_for(lon: float, lat: float, size: float, *, to_metric=TO_METRIC, to_wgs=TO_WGS):
    if size <= 0 or not (-180 <= lon <= 180 and -90 < lat < 90):
        raise ValueError("Invalid point or hexagon size")
    x, y = to_metric(lon, lat)
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
    return f"{size}:{i}:{j}", transform(to_wgs, polygon)


def hexagons(events: list[dict], size: float, *, to_metric=TO_METRIC, to_wgs=TO_WGS):
    groups = defaultdict(list)
    geometries = {}
    seen_ids = set()
    for e in events:
        if e["id"] in seen_ids:
            raise ValueError(f"Duplicate announcement ID: {e['id']}")
        seen_ids.add(e["id"])
        location = count_location(e)
        if location is None:
            continue
        key, geometry = cell_for(*location["coordinates"], size, to_metric=to_metric, to_wgs=to_wgs)
        groups[key].append((e, location))
        geometries[key] = geometry
    return collection(
        [
            feature(
                geometries[key],
                {
                    "id": key,
                    "edge_m": size,
                    "count": len(rows),
                    "event_ids": [e["id"] for e, _ in rows],
                    "categories": dict(Counter(e["category"] for e, _ in rows)),
                    "outcomes": dict(Counter(e.get("outcome", "unknown") for e, _ in rows)),
                    "approximate_count": sum(
                        location["location_precision"] != "point" for _, location in rows
                    ),
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


def pois_from_osm(payload: dict, *, to_metric=TO_METRIC, to_wgs=TO_WGS):
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
            display = transform(to_wgs, transform(to_metric, center).buffer(POI_RADIUS_M, quad_segs=8))
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


def associate(
    events: list[dict],
    pois: dict,
    matching_types_only: bool = True,
    *,
    to_metric=TO_METRIC,
    include_legacy_links: bool = True,
):
    """Match to 50m circles or station footprint. Count each report once per POI.

    Street-level geocodes generate candidates, not confirmed venue attribution.
    District geocodes never cause 50m association or polygon containment.
    Reviewed candidates disable legacy links so only explicit scene POI contexts survive.
    """
    places = pois["features"]
    place_by_id = {f["properties"]["id"]: f for f in places}
    place_index_by_id = {f["properties"]["id"]: index for index, f in enumerate(places)}
    metric = [transform(to_metric, shape(f["geometry"])) for f in places]
    tree = STRtree(metric)
    links = []
    seen = set()
    if include_legacy_links:
        for event in events:
            location = count_location(event)
            if location is None:
                continue
            scene_aware = "scene_locations" in event
            mentions = (
                location.get("poi_mentions", []) if scene_aware else event.get("poi_mentions", [])
            )
            object_ids = (
                location.get("location_object_ids", [])
                if scene_aware
                else event.get("location_object_ids", [])
            )
            if (not scene_aware and not mentions) or (
                scene_aware and not mentions and not object_ids
            ):
                continue
            if scene_aware and not (
                location.get("evidence_quote") or location.get("geocode_evidence")
            ):
                continue
            mention_basis = (
                location.get("mention_basis", "scene_specific_source_match")
                if scene_aware
                else event["mention_basis"]
            )
            if location["location_precision"] == "place":
                # A park/station representative must not accidentally darken unrelated neighbours.
                for ident in dict.fromkeys(object_ids):
                    f = place_by_id.get(ident)
                    if f is None:
                        continue
                    p = f["properties"]
                    pair = event["id"], p["id"]
                    if pair in seen:
                        continue
                    if not matching_types_only or not mentions or p["kind"] in mentions:
                        seen.add(pair)
                        links.append(
                            dict(
                                event_id=event["id"],
                                poi_id=p["id"],
                                status="named_place_candidate",
                                source_url=event["source_url"],
                                mention_basis=mention_basis,
                            )
                        )
                continue
            if not mentions:
                continue
            point = transform(to_metric, Point(location["coordinates"]))
            for idx in tree.query(point, predicate="intersects"):
                p = places[int(idx)]["properties"]
                if p["geometry_mode"] == "footprint_missing":
                    continue
                if matching_types_only and p["kind"] not in mentions:
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
                        if location["location_precision"] == "point"
                        else "approximate_candidate",
                        "source_url": event["source_url"],
                        "mention_basis": mention_basis,
                    }
                )
    reviewed_pairs = {}
    for event in events:
        for scene in event.get("scene_locations", []):
            contexts = scene.get("poi_contexts", [])
            if not contexts:
                continue
            geometry_value = scene.get("geometry") or scene.get("candidate_road_geometry")
            if geometry_value is not None:
                try:
                    scene_geometry = shape(geometry_value)
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f"Invalid POI context geometry for {event.get('id')}") from exc
            elif _valid_coordinates(scene.get("coordinates")):
                scene_geometry = Point(scene["coordinates"])
            else:
                continue
            if scene_geometry.is_empty or not scene_geometry.is_valid:
                raise ValueError(f"Invalid POI context geometry for {event.get('id')}")
            scene_metric = transform(to_metric, scene_geometry)
            for context in contexts:
                kind = context.get("kind")
                scope = context.get("scope")
                radius = context.get("radius_m")
                native_platforms = (
                    scene.get("geometry_usage") == "source_native_platform_points_reference_only"
                )
                if scope == "named_object" or (scope == "along_geometry" and native_platforms):
                    # Original reviewed platform IDs survive public coordinate rounding.
                    # These are station-name references, never inferred incident positions.
                    candidate_indexes = [
                        place_index_by_id[ident]
                        for ident in scene.get("location_object_ids", [])
                        if ident in place_index_by_id
                    ]
                elif scope in {"along_geometry", "near_geometry"}:
                    query = scene_metric.buffer(radius) if scope == "near_geometry" else scene_metric
                    candidate_indexes = [int(index) for index in tree.query(query, predicate="intersects")]
                else:
                    raise ValueError(f"Invalid POI context scope for {event.get('id')}")
                for index in candidate_indexes:
                    place = places[index]["properties"]
                    if kind not in place.get("context_kinds", [place.get("kind")]):
                        continue
                    pair = event["id"], place["id"]
                    if pair not in seen:
                        seen.add(pair)
                        row = {
                            "event_id": event["id"],
                            "scene_id": scene.get("scene_id"),
                            "poi_id": place["id"],
                            "status": f"context_{scope}",
                            "source_url": event["source_url"],
                            "mention_basis": "source_reviewed_context_only",
                            "evidence_quote": context.get("evidence_quote"),
                        }
                        links.append(row)
                        if native_platforms:
                            row.update({k: scene[k] for k in (
                                "geometry_usage", "actual_platform_side_known", "actual_event_position_known"
                            ) if k in scene})
                        if "context_kinds" in place:
                            row.update(context_kinds=[], source_context_evidence=[])
                            reviewed_pairs[pair] = row
                    row = reviewed_pairs.get(pair)
                    if row is not None:
                        evidence = {
                            "scene_id": scene.get("scene_id"), "kind": kind,
                            "scope": scope, "radius_m": radius,
                            "evidence_quote": context.get("evidence_quote"),
                            "source_sha256": event.get("source_sha256"),
                            "source_review_sha256": event.get("source_review_sha256"),
                        }
                        if kind not in row["context_kinds"]:
                            row["context_kinds"].append(kind)
                        if evidence not in row["source_context_evidence"]:
                            row["source_context_evidence"].append(evidence)
    return links


def build_months(
    events: list[dict],
    pois: dict,
    *,
    to_metric=TO_METRIC,
    to_wgs=TO_WGS,
    include_legacy_links: bool = True,
):
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
            "hex": {
                name: hexagons(rows, size, to_metric=to_metric, to_wgs=to_wgs)
                for name, size in HEX_SIZES.items()
            },
            "links": associate(
                rows,
                pois,
                to_metric=to_metric,
                include_legacy_links=include_legacy_links,
            ),
        }
        for month, rows in sorted(months.items())
    }
