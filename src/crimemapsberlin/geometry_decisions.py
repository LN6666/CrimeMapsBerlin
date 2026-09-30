"""Validate LLM geometry selections against reviewed scenes and checked OSM.

The LLM decides whether a reviewed location corresponds to source coordinates
or one or more OSM objects.  This module only checks identity, current hashes,
geometry types and municipal containment, then derives geometry from the
selected source objects.  It never matches names or changes scene semantics.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from shapely.geometry import MultiPoint, Point, mapping, shape
from shapely.ops import transform, unary_union

from .city_geometry_index import validate_geometry_index
from .poi_cities import POI_CITY_SPECS, geometry_covered_by
from .spatial import metric_transforms

SCHEMA_VERSION = 1
INTERSECTION_CLUSTER_MAX_M = 150
VERDICTS = {"resolved", "unresolved", "needs_correction"}
METHODS = {
    "source_coordinate",
    "osm_point",
    "osm_footprint",
    "osm_line",
    "osm_transit_route",
    "osm_intersection",
    "osm_polygon",
    "none",
}
POINT_PRECISIONS = {"point", "address", "place"}
DECISION_KEYS = {
    "schema_version",
    "city",
    "source_id",
    "source_sha256",
    "decision_sha256",
    "location_id",
    "geometry_request_sha256",
    "verdict",
    "method",
    "osm_object_groups",
    "review_note",
    "reviewer",
    "reviewed_at",
}
ENVELOPE_KEYS = {
    "schema_version",
    "city",
    "inventory_digest",
    "geometry_index_sha256",
    "decisions",
}


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _exact_keys(value: object, keys: set[str], label: str) -> dict:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    missing = keys - set(value)
    extra = set(value) - keys
    if missing or extra:
        raise ValueError(
            f"{label} has missing fields {sorted(missing)} or unknown fields {sorted(extra)}"
        )
    return value


def _reviewed_at(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("geometry decision needs reviewed_at")
    candidate = value.strip()
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError("geometry decision has invalid reviewed_at") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("geometry decision reviewed_at must include a timezone")
    return candidate


def _identity(decision: dict, request: dict, city: str) -> None:
    for key in (
        "source_id",
        "source_sha256",
        "decision_sha256",
        "location_id",
        "geometry_request_sha256",
    ):
        if decision[key] != request[key]:
            raise ValueError(f"geometry decision {key} differs from current request")
    if decision["schema_version"] != SCHEMA_VERSION or decision["city"] != city:
        raise ValueError("geometry decision schema version or city differs")


def _source_route_relation(row: dict, line: str, mode: str) -> bool:
    tags = row.get("tags", {})
    proof = row.get("transit_source_proof", {})
    members = proof.get("member_way_ids")
    sequence = proof.get("member_sequence")
    source_digest = proof.get("member_source_digest")
    return (
        "transit_route" in row.get("roles", [])
        and row.get("id") == f"osm/relation/{proof.get('relation_id')}"
        and tags.get("type") == "route"
        and tags.get("route") == mode
        and tags.get("ref") == line
        and line in row.get("names", [])
        and proof.get("schema_version") == 1
        and proof.get("complete") is True
        and isinstance(members, list)
        and bool(members)
        and all(type(ident) is int for ident in members)
        and members == sorted(set(members))
        and proof.get("member_way_count") == len(members)
        and isinstance(sequence, list)
        and all(type(ident) is int for ident in sequence)
        and set(sequence) == set(members)
        and isinstance(source_digest, str)
        and len(source_digest) == 64
        and all(char in "0123456789abcdef" for char in source_digest)
        and row.get("geometry", {}).get("type") in {"LineString", "MultiLineString"}
    )


def _derived_geometry(
    decision: dict, request: dict, objects: dict[str, dict], border, city: str
) -> dict | None:
    verdict = decision["verdict"]
    method = decision["method"]
    object_groups = decision["osm_object_groups"]
    if not isinstance(object_groups, list) or any(
        not isinstance(group, list) or any(not isinstance(ident, str) for ident in group)
        for group in object_groups
    ):
        raise TypeError("osm_object_groups must be a list of string lists")
    object_ids = [ident for group in object_groups for ident in group]
    if len(object_ids) != len(set(object_ids)):
        raise ValueError("OSM geometry decision contains duplicate object IDs")
    if verdict in {"unresolved", "needs_correction"}:
        if method != "none" or object_groups:
            raise ValueError("unresolved geometry decisions cannot select geometry")
        return None
    if verdict != "resolved" or method == "none":
        raise ValueError("resolved geometry decision needs a geometry method")

    task = request["geometry_task"]
    precision = request["precision"]
    if method == "source_coordinate":
        if task != "review_point_requires_boundary_check" or object_groups:
            raise ValueError("source_coordinate is only valid for a supplied source point")
        coordinates = request["coordinates"]
        if coordinates is None:
            raise ValueError("source_coordinate request has no coordinate")
        geometry = Point(coordinates)
        if not border.covers(geometry):
            raise ValueError("source coordinate lies outside the municipality")
    else:
        if not object_ids or any(not group for group in object_groups):
            raise ValueError("OSM geometry method needs at least one object ID")
        try:
            selected = [objects[ident] for ident in object_ids]
        except KeyError as exc:
            raise ValueError(f"selected OSM object is absent from the checked index: {exc.args[0]}") from exc
        geometries = [shape(row["geometry"]) for row in selected]
        if method == "osm_point":
            if task != "checked_point_geocode_required" or precision not in POINT_PRECISIONS:
                raise ValueError("osm_point differs from the reviewed precision")
            if len(object_groups) != 1 or len(geometries) != 1 or geometries[0].geom_type != "Point":
                raise ValueError("osm_point needs exactly one OSM point")
            geometry = geometries[0]
        elif method == "osm_footprint":
            if task != "checked_point_geocode_required" or precision not in POINT_PRECISIONS:
                raise ValueError("osm_footprint differs from the reviewed precision")
            if len(object_groups) != 1 or any(
                geometry.geom_type not in {"Polygon", "MultiPolygon"}
                for geometry in geometries
            ):
                raise ValueError("osm_footprint selections must be polygon objects")
            geometry = unary_union(geometries)
        elif method == "osm_line":
            line_matches_review = (
                (task == "checked_road_geometry_required" and precision == "street")
                or (task == "checked_area_geometry_required" and precision == "area")
                or (
                    task == "checked_point_geocode_required"
                    and precision in {"point", "place"}
                )
            )
            if not line_matches_review:
                raise ValueError("osm_line differs from the reviewed precision")
            if len(object_groups) != 1 or any(
                geometry.geom_type not in {"LineString", "MultiLineString"}
                or not (
                    "road" in row["roles"]
                    or (
                        task == "checked_point_geocode_required"
                        and precision in {"point", "place"}
                        and (
                            row.get("tags", {}).get("public_transport") == "platform"
                            or row.get("tags", {}).get("railway") in {"platform", "platform_edge"}
                        )
                    )
                )
                for row, geometry in zip(selected, geometries, strict=True)
            ):
                raise ValueError("osm_line selections must be checked road objects or point/place platforms")
            geometry = unary_union(geometries)
        elif method == "osm_transit_route":
            if (
                task != "checked_transit_route_geometry_required"
                or precision != "route"
                or len(object_groups) != 1
            ):
                raise ValueError("osm_transit_route differs from the reviewed precision")
            transit = request.get("transit_route")
            line = transit.get("line") if isinstance(transit, dict) else None
            mode = transit.get("mode") if isinstance(transit, dict) else None
            if not isinstance(line, str) or not line:
                raise ValueError("transit route request has no reviewed line")
            if any(
                geometry.geom_type not in {"LineString", "MultiLineString"}
                or line not in row.get("names", [])
                or not (
                    _source_route_relation(row, line, mode)
                    or (
                        transit.get("extent") == "source_segment"
                        and row.get("tags", {}).get("railway")
                        and row.get("tags", {}).get("railway") not in {
                            "construction", "proposed", "disused", "abandoned", "razed"
                        }
                    )
                )
                for row, geometry in zip(selected, geometries, strict=True)
            ):
                raise ValueError("transit route selections must be checked line objects")
            if transit.get("extent") == "full_line":
                expected = {
                    ident
                    for ident, row in objects.items()
                    if _source_route_relation(row, line, mode)
                }
                if not expected or set(object_ids) != expected:
                    raise ValueError(
                        "full transit route selection must cover every complete source route relation"
                    )
            geometry = unary_union(geometries)
        elif method == "osm_intersection":
            if task != "checked_point_geocode_required" or precision not in POINT_PRECISIONS:
                raise ValueError("osm_intersection differs from the reviewed precision")
            if len(object_groups) < 2:
                raise ValueError("osm_intersection needs at least two road groups")
            grouped = []
            selected_by_id = {row["id"]: row for row in selected}
            for group in object_groups:
                rows = [selected_by_id[ident] for ident in group]
                group_geometries = [shape(row["geometry"]) for row in rows]
                if any(
                    geometry.geom_type not in {"LineString", "MultiLineString"}
                    or "road" not in row["roles"]
                    for row, geometry in zip(rows, group_geometries, strict=True)
                ):
                    raise ValueError("osm_intersection groups must contain checked roads")
                grouped.append(unary_union(group_geometries))
            candidates = []
            for left, right in itertools.combinations(grouped, 2):
                intersection = left.intersection(right)
                if intersection.geom_type == "Point" and not intersection.is_empty:
                    candidates.append(intersection)
                elif intersection.geom_type == "MultiPoint":
                    candidates.extend(intersection.geoms)
                elif intersection.geom_type == "GeometryCollection":
                    candidates.extend(
                        part for part in intersection.geoms if part.geom_type == "Point"
                    )
            unique = {
                (point.x, point.y): point for point in candidates if not point.is_empty
            }
            candidates = [unique[key] for key in sorted(unique)]
            if not candidates:
                raise ValueError("selected roads have no point intersection")
            to_metric, _ = metric_transforms(POI_CITY_SPECS[city].epsg)
            metric_points = [transform(to_metric, point) for point in candidates]
            spread = max(
                (
                    left.distance(right)
                    for left, right in itertools.combinations(metric_points, 2)
                ),
                default=0.0,
            )
            if spread > INTERSECTION_CLUSTER_MAX_M:
                raise ValueError(
                    f"selected road intersections span {spread:.1f} m, exceeding the junction limit"
                )
            medoid = min(
                range(len(candidates)),
                key=lambda index: (
                    sum(metric_points[index].distance(other) for other in metric_points),
                    candidates[index].x,
                    candidates[index].y,
                ),
            )
            geometry = candidates[medoid]
            intersection_candidates = MultiPoint(candidates)
        elif method == "osm_polygon":
            polygon_matches_review = (
                (task == "checked_area_geometry_required" and precision == "area")
                or (task == "checked_district_geometry_required" and precision == "district")
                or (task == "checked_point_geocode_required" and precision in POINT_PRECISIONS)
                or (task == "checked_road_geometry_required" and precision == "street")
            )
            if not polygon_matches_review:
                raise ValueError("osm_polygon differs from the reviewed precision")
            if len(object_groups) != 1 or any(
                geometry.geom_type not in {"Polygon", "MultiPolygon"}
                for geometry in geometries
            ):
                raise ValueError("osm_polygon selections must be polygon objects")
            if precision == "district" and any(
                "administrative_boundary" not in row["roles"] for row in selected
            ):
                raise ValueError("district geometry must use administrative boundary objects")
            if precision == "street" and any("road" not in row["roles"] for row in selected):
                raise ValueError("street polygons must use checked road objects")
            geometry = unary_union(geometries)
        else:
            raise ValueError("unsupported geometry method")

    if geometry.is_empty or not geometry.is_valid or not geometry_covered_by(border, geometry):
        raise ValueError("derived geometry is invalid or outside the municipality")
    geojson = mapping(geometry)
    result = {
        "type": geometry.geom_type,
        "geometry": geojson,
        "geometry_sha256": _digest(geojson),
        "source_object_ids": object_ids,
        "source_object_groups": object_groups,
    }
    if method == "osm_footprint":
        point = geometry.representative_point()
        point_geojson = mapping(point)
        result["count_point"] = point_geojson
        result["count_point_sha256"] = _digest(point_geojson)
        result["count_point_method"] = "selected_osm_footprint_representative_point"
    elif method == "osm_intersection":
        candidate_geojson = mapping(intersection_candidates)
        result["intersection_candidates"] = candidate_geojson
        result["intersection_candidates_sha256"] = _digest(candidate_geojson)
        result["intersection_spread_m"] = round(spread, 3)
        result["count_point_method"] = "selected_osm_road_groups_intersection_medoid"
    return result


def compile_geometry_decisions(
    *, inventory: dict, geometry_index: dict, decision_envelope: dict, border
) -> dict:
    """Compile a partial or complete set of current LLM geometry decisions."""
    envelope = _exact_keys(decision_envelope, ENVELOPE_KEYS, "geometry decision envelope")
    city = inventory.get("city")
    if (
        envelope["schema_version"] != SCHEMA_VERSION
        or envelope["city"] != city
        or geometry_index.get("city") != city
    ):
        raise ValueError("geometry decision inputs belong to different cities or schemas")
    if envelope["geometry_index_sha256"] != geometry_index.get("index_sha256"):
        raise ValueError("geometry decision envelope is stale for the OSM index")
    decisions = envelope["decisions"]
    if not isinstance(decisions, list):
        raise TypeError("geometry decisions must be a list")

    requests = {
        row["location_id"]: row for row in inventory.get("geometry_requests", [])
    }
    if len(requests) != len(inventory.get("geometry_requests", [])):
        raise ValueError("scene inventory has duplicate geometry location IDs")
    objects = {row["id"]: row for row in geometry_index.get("objects", [])}
    compiled = []
    seen = set()
    verdict_counts: Counter = Counter()
    method_counts: Counter = Counter()
    for number, raw in enumerate(decisions, start=1):
        label = f"geometry decision {number}"
        decision = _exact_keys(raw, DECISION_KEYS, label)
        location_id = decision["location_id"]
        if location_id in seen or location_id not in requests:
            raise ValueError(f"{label} has a duplicate or unknown location_id")
        seen.add(location_id)
        request = requests[location_id]
        _identity(decision, request, city)
        if decision["verdict"] not in VERDICTS or decision["method"] not in METHODS:
            raise ValueError(f"{label} has an invalid verdict or method")
        if not isinstance(decision["osm_object_groups"], list):
            raise TypeError(f"{label} osm_object_groups must be a list")
        note = decision["review_note"].strip() if isinstance(decision["review_note"], str) else ""
        reviewer = decision["reviewer"].strip() if isinstance(decision["reviewer"], str) else ""
        if not note or not reviewer:
            raise ValueError(f"{label} needs a review note and reviewer")
        try:
            geometry = _derived_geometry(decision, request, objects, border, city)
        except (TypeError, ValueError) as exc:
            raise type(exc)(f"{label} ({location_id}): {exc}") from exc
        normalized = {
            **decision,
            "osm_object_groups": [list(group) for group in decision["osm_object_groups"]],
            "review_note": note,
            "reviewer": reviewer,
            "reviewed_at": _reviewed_at(decision["reviewed_at"]),
        }
        compiled.append(
            {
                "request": request,
                "decision": normalized,
                "decision_sha256": _digest(normalized),
                "derived_geometry": geometry,
            }
        )
        verdict_counts[decision["verdict"]] += 1
        method_counts[decision["method"]] += 1

    pending = len(requests) - len(compiled)
    all_reviewed = pending == 0
    review_complete = all_reviewed and verdict_counts["needs_correction"] == 0
    core = {
        "schema_version": SCHEMA_VERSION,
        "city": city,
        "inventory_digest": inventory["inventory_digest"],
        "submitted_inventory_digest": envelope["inventory_digest"],
        "geometry_index_sha256": geometry_index["index_sha256"],
        "decisions": compiled,
    }
    return {
        **core,
        "ledger_sha256": _digest(core),
        "request_count": len(requests),
        "decision_count": len(compiled),
        "pending_count": pending,
        "inventory_extended_since_submission": (
            envelope["inventory_digest"] != inventory["inventory_digest"]
        ),
        "verdict_counts": dict(sorted(verdict_counts.items())),
        "method_counts": dict(sorted(method_counts.items())),
        "all_requests_reviewed": all_reviewed,
        "geometry_review_complete": review_complete,
        "publication_ready": False,
        "publication_blocks": [
            *([] if inventory.get("all_current_reviews_supported") else ["source_review_incomplete"]),
            *([] if review_complete else ["geometry_review_incomplete"]),
            "owner_approval_missing",
            "approved_map_build_absent",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--geometry-index", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--boundary", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    geometry_index = json.loads(args.geometry_index.read_text(encoding="utf-8"))
    decision_envelope = json.loads(args.decisions.read_text(encoding="utf-8"))
    boundary = json.loads(args.boundary.read_text(encoding="utf-8"))
    border = shape(boundary["geometry"])
    source = {
        "sha256": geometry_index["source_pbf_sha256"],
        "pbf_timestamp": geometry_index["source_pbf_timestamp"],
    }
    validation = validate_geometry_index(
        geometry_index,
        city=inventory["city"],
        border=border,
        boundary_metadata=boundary,
        source_metadata=source,
    )
    if not validation["passed"]:
        raise SystemExit("Invalid geometry index: " + "; ".join(validation["errors"][:10]))
    result = compile_geometry_decisions(
        inventory=inventory,
        geometry_index=geometry_index,
        decision_envelope=decision_envelope,
        border=border,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    temporary.replace(args.out)
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "decisions"},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
