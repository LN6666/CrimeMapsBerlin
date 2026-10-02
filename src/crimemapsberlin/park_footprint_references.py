"""Check authored native park faces without generating an event/count point."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re

from shapely.geometry import mapping, shape
from shapely.ops import unary_union

METHOD = "osm_park_footprint_reference"
USAGE = "source_footprint_reference_only"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()


def _same_native_cycle(ring, nodes):
    if len(ring) != len(nodes) or ring[0] != ring[-1]:
        return False
    source = [n["coordinates"] for n in nodes[:-1]]
    target = ring[:-1]
    for sequence in (source, source[::-1]):
        for start, xy in enumerate(sequence):
            if xy == target[0] and sequence[start:] + sequence[:start] == target:
                return True
    return False


def validate_native_park_object(row, source_pbf_sha256, border):
    """Accept original closed park ways, including genuinely unnamed faces."""
    ident = row.get("id", "")
    proof = row.get("native_park_source_proof") or {}
    way = proof.get("source_way") or {}
    tags = way.get("tags") or {}
    geometry = json.loads(json.dumps(row.get("geometry") or {}))
    names = [tags["name"]] if isinstance(tags.get("name"), str) and tags["name"].strip() else []
    if (not isinstance(source_pbf_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", source_pbf_sha256) is None
        or re.fullmatch(r"osm/way/[1-9]\d*", ident) is None
        or proof.get("schema_version") != 1 or proof.get("reference_only") is not True
        or proof.get("source_pbf_sha256") != source_pbf_sha256
        or type(way.get("id")) is not int or way["id"] <= 0
        or ident != f"osm/way/{way['id']}"
        or row.get("source_url") != f"https://www.openstreetmap.org/way/{way['id']}"
        or proof.get("source_way_sha256") != digest(way)
        or row.get("tags") != tags or tags.get("leisure") != "park"
        or row.get("names") != names
        or "native_park_footprint" not in row.get("roles", [])
        or "administrative_boundary" in row.get("roles", [])
        or tags.get("boundary") == "administrative"
        or geometry.get("type") != "Polygon"
        or row.get("geometry_sha256") != digest(geometry)):
        raise ValueError("Park face must retain its current original park way, tags and name")
    nodes = way.get("nodes")
    rings = geometry.get("coordinates")
    if (not isinstance(nodes, list) or len(nodes) < 4
        or not isinstance(rings, list) or len(rings) != 1
        or any(not isinstance(n, dict) or type(n.get("id")) is not int or n["id"] <= 0
               or not isinstance(n.get("coordinates"), list) or len(n["coordinates"]) != 2
               or any(type(x) not in {int, float} or not math.isfinite(x) for x in n["coordinates"])
               for n in nodes)
        or nodes[0] != nodes[-1]
        or not _same_native_cycle(rings[0], nodes)):
        raise ValueError("Park face needs its complete original closed native node cycle")
    geom = shape(geometry)
    if geom.is_empty or not geom.is_valid or not border.covers(geom):
        raise ValueError("Native park face is invalid or outside the municipality")
    return geom


def valid_native_park_object(row, *, pipeline_version, source_metadata, border):
    if pipeline_version != 4 or "native_park_source_proof" not in row:
        return False
    try:
        validate_native_park_object(row, source_metadata.get("sha256"), border)
    except (TypeError, ValueError, KeyError, IndexError):
        return False
    return True


def park_footprint_reference(decision, request, objects, border, source_pbf_sha256):
    """Union selected original faces; place identity remains an LLM decision."""
    if (decision.get("method") != METHOD or decision.get("verdict") != "resolved"
        or request.get("geometry_task") != "checked_point_geocode_required"
        or request.get("precision") != "place" or request.get("city_scope") != "in_city"
        or request.get("coordinates") is not None or request.get("transit_route") is not None
        or (request.get("transit_review") or {}).get("status") != "not_applicable"
        or (request.get("poi_review") or {}).get("status") != "context_only"
        or not any(c.get("kind") == "park" for c in request.get("poi_contexts", []) if isinstance(c, dict))):
        raise ValueError("Park footprint needs an explicitly reviewed fixed park context")
    groups = decision.get("osm_object_groups")
    if (not isinstance(groups, list) or len(groups) != 1 or not isinstance(groups[0], list)
        or not groups[0] or any(not isinstance(i, str) for i in groups[0])
        or len(set(groups[0])) != len(groups[0])):
        raise ValueError("Park footprint needs one group of distinct native park ways")
    geometries, names, evidence = [], set(), []
    for ident in groups[0]:
        row = objects.get(ident)
        if not isinstance(row, dict) or row.get("id") != ident:
            raise ValueError("Selected native park face is absent or has mismatched identity")
        geometries.append(validate_native_park_object(row, source_pbf_sha256, border))
        names.update(row["names"])
        evidence.append({"object_id": ident, "source_url": row["source_url"],
            "source_way_sha256": row["native_park_source_proof"]["source_way_sha256"],
            "geometry_sha256": row["geometry_sha256"], "native_names": list(row["names"])})
    if len(names) != 1:
        raise ValueError("Park reference needs one original name anchor, without mixing named parks")
    geometry = json.loads(json.dumps(mapping(unary_union(geometries))))
    return {"type": geometry["type"], "geometry": geometry, "geometry_sha256": digest(geometry),
        "source_object_ids": list(groups[0]), "source_object_groups": copy.deepcopy(groups),
        "native_park_sources": evidence, "geometry_usage": USAGE, "static_scene_reference": True,
        "actual_event_position_known": False, "actual_static_scene_extent_known": False,
        "complete_park_boundary_known": False, "coordinates_generated": False}
