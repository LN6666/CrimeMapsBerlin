"""Preserve explicitly selected native platforms as a reference collection.

The LLM reviewer chooses the platform IDs. This calculation checks geometry
and provenance consistency; it does not select a station, side or incident
position from report text, and never creates a representative/count point.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re

from shapely.geometry import shape

METHOD = "osm_platform_point_collection_reference"
USAGE = "source_native_platform_points_reference_only"


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def native_platform_reference(decision, request, objects, border):
    """Keep every selected original coordinate, including co-located nodes."""
    if (decision.get("method") != METHOD or decision.get("verdict") != "resolved"
            or request.get("geometry_task") != "checked_point_geocode_required"
            or request.get("precision") != "place"
            or request.get("city_scope") != "in_city"
            or request.get("coordinates") is not None):
        raise ValueError("Platform references need an in-city place with no supplied event point")
    groups = decision.get("osm_object_groups")
    if (not isinstance(groups, list) or len(groups) != 1
            or not isinstance(groups[0], list) or len(groups[0]) < 2
            or any(not isinstance(ident, str) for ident in groups[0])
            or len(set(groups[0])) != len(groups[0])):
        raise ValueError("Platform reference needs one group of distinct native node IDs")
    coordinates = []
    names = set()
    source_rows = []
    for ident in groups[0]:
        row = objects.get(ident)
        if not isinstance(row, dict) or row.get("id") != ident:
            raise ValueError("Selected platform is absent or has mismatched identity")
        geo = row.get("geometry", {})
        tags = row.get("tags", {})
        xy = geo.get("coordinates")
        if (not re.fullmatch(r"osm/node/[1-9]\d*", ident)
                or geo.get("type") != "Point"
                or "named_object" not in row.get("roles", [])
                or tags.get("public_transport") != "platform"
                or not isinstance(tags.get("name"), str) or not tags["name"].strip()
                or not isinstance(xy, (list, tuple)) or len(xy) != 2
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in xy)
                or abs(xy[0]) > 180 or abs(xy[1]) > 90
                or row.get("geometry_sha256") != _digest(geo)
                or row.get("source_url") != f"https://www.openstreetmap.org/node/{ident.rsplit('/', 1)[1]}"
                or "native_road_vertex_source_proof" in row):
            raise ValueError("Reference members must be named, bound original platform nodes")
        if not border.covers(shape(geo)):
            raise ValueError("Reference platform is outside the reviewed municipality")
        names.add(tags["name"].strip())
        coordinates.append(copy.deepcopy(list(xy)))
        source_rows.append({"object_id": ident, "source_url": row["source_url"],
                            "geometry_sha256": row["geometry_sha256"]})
    if len(names) != 1:
        raise ValueError("Platform reference group contains different named stops")
    geometry = {"type": "MultiPoint", "coordinates": coordinates}
    if not shape(geometry).is_valid:
        raise ValueError("Native platform reference geometry is invalid")
    return {
        "type": "MultiPoint", "geometry": geometry,
        "geometry_sha256": _digest(geometry),
        "source_object_ids": list(groups[0]),
        "source_object_groups": copy.deepcopy(groups),
        "native_platform_sources": source_rows,
        "geometry_usage": USAGE,
        "native_platform_count": len(coordinates),
        "actual_event_position_known": False,
        "actual_platform_side_known": False,
        "complete_transit_line": False,
        "coordinates_generated": False,
    }
