"""Validate selected native station platforms as context-only footprints."""
from __future__ import annotations

import copy
import hashlib
import json
import re

from shapely.geometry import mapping, shape
from shapely.ops import unary_union

METHOD = "osm_station_platform_footprint_reference"
USAGE = "source_station_platform_footprint_reference_only"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()


def station_platform_reference(decision, request, objects, border, source_pbf_sha256):
    """Use authored IDs; never infer a platform, train, side or event point."""
    if (decision.get("method") != METHOD or decision.get("verdict") != "resolved"
        or request.get("geometry_task") != "checked_point_geocode_required"
        or request.get("precision") != "place" or request.get("city_scope") != "in_city"
        or request.get("coordinates") is not None or request.get("transit_route") is not None
        or (request.get("transit_review") or {}).get("status") != "source_backed_context"
        or (request.get("poi_review") or {}).get("status") != "context_only"
        or not any(c.get("kind") == "station" for c in request.get("poi_contexts", []) if isinstance(c, dict))
        or not isinstance(source_pbf_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", source_pbf_sha256) is None):
        raise ValueError("Station platform reference needs a reviewed fixed in-city station context")
    groups = decision.get("osm_object_groups")
    if (not isinstance(groups, list) or len(groups) != 1 or not isinstance(groups[0], list)
        or not groups[0] or any(not isinstance(i, str) for i in groups[0])
        or len(set(groups[0])) != len(groups[0])):
        raise ValueError("Station footprint needs one group of distinct native platform IDs")
    geometries, station_ids, evidence = [], set(), []
    for ident in groups[0]:
        row = objects.get(ident)
        if not isinstance(row, dict) or row.get("id") != ident:
            raise ValueError("Selected station platform is absent or has mismatched identity")
        proof = row.get("native_station_platform_source_proof") or {}
        parent = proof.get("parent_stop_area") or {}
        way = proof.get("source_way") or {}
        tags = row.get("tags") or {}
        geometry = row.get("geometry") or {}
        if (not re.fullmatch(r"osm/way/[1-9]\d*", ident)
            or proof.get("schema_version") != 1
            or proof.get("source_pbf_sha256") != source_pbf_sha256
            or proof.get("reference_only") is not True
            or type(parent.get("id")) is not int or parent["id"] <= 0
            or type(way.get("id")) is not int or way["id"] <= 0
            or proof.get("parent_stop_area_sha256") != digest(parent)
            or proof.get("source_way_sha256") != digest(way)
            or ident != f"osm/way/{way['id']}"
            or row.get("source_url") != f"https://www.openstreetmap.org/way/{way['id']}"
            or tags != way.get("tags")
            or tags.get("area") != "yes" or tags.get("railway") != "platform"
            or tags.get("public_transport") != "platform" or tags.get("subway") != "yes"
            or tags.get("bus") == "yes"
            or geometry != way.get("geometry") or geometry.get("type") != "Polygon"
            or row.get("geometry_sha256") != digest(geometry)
            or "named_object" not in row.get("roles", [])
            or "administrative_boundary" in row.get("roles", [])
            or "native_road_vertex_source_proof" in row):
            raise ValueError("Station footprint must retain the bound original subway platform")
        ptags = parent.get("tags") or {}
        name = ptags.get("name")
        member = {"id": way["id"], "type": "w", "role": proof.get("platform_member_role")}
        if (ptags.get("public_transport") != "stop_area" or ptags.get("subway") != "yes"
            or not isinstance(name, str) or not name.strip()
            or row.get("names") != [name]
            or member not in parent.get("members", [])
            or member["role"] not in {"", "platform"}):
            raise ValueError("Platform must be an actual member of one named subway stop area")
        rings = geometry.get("coordinates")
        nodes = way.get("node_ids")
        if (not isinstance(rings, list) or len(rings) != 1
            or not isinstance(nodes, list) or len(nodes) != len(rings[0])
            or len(nodes) < 4 or nodes[0] != nodes[-1]
            or rings[0][0] != rings[0][-1]
            or any(type(n) is not int or n <= 0 for n in nodes)
            or any(not isinstance(xy, list) or len(xy) != 2
                   or any(type(x) not in {int, float} for x in xy) for xy in rings[0])):
            raise ValueError("Platform polygon needs its original closed native node sequence")
        geom = shape(geometry)
        if geom.is_empty or not geom.is_valid or not border.covers(geom):
            raise ValueError("Native station platform is invalid or outside the municipality")
        geometries.append(geom)
        station_ids.add(parent["id"])
        evidence.append({"object_id": ident, "source_url": row["source_url"],
            "parent_stop_area_id": f"osm/relation/{parent['id']}",
            "parent_stop_area_sha256": proof["parent_stop_area_sha256"],
            "source_way_sha256": proof["source_way_sha256"],
            "geometry_sha256": row["geometry_sha256"]})
    if len(station_ids) != 1:
        raise ValueError("Station reference cannot combine different stop areas")
    geometry = json.loads(json.dumps(mapping(unary_union(geometries))))
    return {"type": geometry["type"], "geometry": geometry,
        "geometry_sha256": digest(geometry), "source_object_ids": list(groups[0]),
        "source_object_groups": copy.deepcopy(groups), "native_platform_sources": evidence,
        "geometry_usage": USAGE, "static_scene_reference": True,
        "actual_static_scene_extent_known": False, "actual_event_position_known": False,
        "actual_platform_side_known": False, "complete_transit_line": False,
        "coordinates_generated": False}
