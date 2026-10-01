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
from .city_road_segment import source_road_segments
from .city_transit_segment import source_track_segment, source_track_segments_between_roads
from .poi_cities import POI_CITY_SPECS, geometry_covered_by
from .spatial import metric_transforms

SCHEMA_VERSION = 1
INTERSECTION_CLUSTER_MAX_M = 150
VERDICTS = {"resolved", "unresolved", "needs_correction"}
METHODS = {
    "osm_station_platform_footprint_reference",
    "osm_platform_point_collection_reference",
    "official_pdf_horizontal_circle_reference",
    "osm_static_road_reference_segment",
    "source_coordinate",
    "osm_point",
    "osm_footprint",
    "osm_line",
    "osm_road_segment",
    "osm_non_transit_route",
    "osm_non_transit_footprint_reference",
    "osm_transit_route",
    "osm_transit_road_reference",
    "osm_transit_road_reference_segment",
    "osm_transit_line_reference",
    "osm_named_footprint_reference",
    "osm_unidentified_transit_segment",
    "osm_transit_segment",
    "osm_transit_road_segment",
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
        and (tags.get("route") == mode
             or (tags.get("route") == "light_rail" and mode in {"subway", "tram"}))
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


def _derived_geometry_without_static_reference(
    decision: dict, request: dict, objects: dict[str, dict], border, city: str,
    *, include_footprint_count_points: bool = True,
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
        path_ids = [ident for group in object_groups[::3] for ident in group]
        if (
            method not in {"osm_road_segment", "osm_transit_road_segment", "osm_transit_road_reference_segment"}
            or any(len(group) != len(set(group)) for group in object_groups)
            or len(path_ids) != len(set(path_ids))
        ):
            raise ValueError("OSM geometry decision contains duplicate object IDs")
        # Parallel carriageways may legitimately share their endpoint roads.
        # A path in one piece may also bound an adjacent piece at a shared
        # native vertex; it still occurs exactly once in the path groups.
        # The segment compiler rejects overlapping/nonunique endpoint hits.
        # Keep the explicit group roles, but list each source object only once.
        object_ids = list(dict.fromkeys(object_ids))
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
        if (any("native_road_vertex_source_proof" in row for row in selected)
                and method not in {"osm_road_segment", "osm_transit_road_segment", "osm_transit_road_reference_segment"}):
            raise ValueError("native road vertices are endpoint references only, not event/count points")
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
        elif method == "osm_named_footprint_reference":
            if task != "checked_road_geometry_required" or precision != "street":
                raise ValueError("named footprint reference needs a reviewed street-precision place")
            if len(object_groups) != 1 or any(
                geometry.geom_type not in {"Polygon", "MultiPolygon"}
                or "named_object" not in row.get("roles", [])
                or "administrative_boundary" in row.get("roles", [])
                or not row.get("names")
                for row, geometry in zip(selected, geometries, strict=True)
            ):
                raise ValueError("named footprint reference needs checked named non-administrative polygons")
            # Preserve the reviewed native bridge/square footprint, never an
            # invented centreline or a synthetic event/count point.
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
        elif method == "osm_road_segment":
            reviewed_non_transit_segment = (
                task == "checked_non_transit_route_geometry_required"
                and precision == "route"
                and (request.get("transit_review") or {}).get("status") == "reviewed_non_transit_route"
                and request.get("transit_route") is None
            )
            if not (
                (task == "checked_road_geometry_required" and precision == "street")
                or (task == "checked_area_geometry_required" and precision == "area")
                or reviewed_non_transit_segment
            ):
                raise ValueError("osm_road_segment differs from the reviewed road/area or non-transit route")
            geometry = source_road_segments(
                [[objects[ident] for ident in group] for group in object_groups]
            )
        elif method == "osm_non_transit_footprint_reference":
            review = request.get("transit_review") or {}
            if (
                task != "checked_non_transit_route_geometry_required"
                or precision != "route"
                or len(object_groups) != 1
                or review.get("status") != "reviewed_non_transit_route"
                or request.get("transit_route") is not None
            ):
                raise ValueError("non-transit footprint reference needs an explicitly reviewed non-transit route")
            if any(
                geometry.geom_type not in {"Polygon", "MultiPolygon"}
                or "named_object" not in row.get("roles", [])
                or "administrative_boundary" in row.get("roles", [])
                or not row.get("names")
                for row, geometry in zip(selected, geometries, strict=True)
            ):
                raise ValueError("non-transit footprint reference needs checked named non-administrative polygons")
            # A source-named lake/park can bound the display context without
            # supplying a boat, walking or cycling path. Never manufacture a
            # trajectory, a centreline or an event/count point from its area.
            geometry = unary_union(geometries)
        elif method == "osm_non_transit_route":
            transit_review = request.get("transit_review", {})
            if (
                task != "checked_non_transit_route_geometry_required"
                or precision != "route"
                or len(object_groups) != 1
                or transit_review.get("status") != "reviewed_non_transit_route"
                or request.get("transit_route") is not None
            ):
                raise ValueError("osm_non_transit_route needs an explicitly reviewed non-transit route")
            if any(
                geometry.geom_type not in {"LineString", "MultiLineString"}
                or "road" not in row.get("roles", [])
                or row.get("tags", {}).get("highway") in {
                    "platform", "bus_stop", "construction", "proposed"
                }
                for row, geometry in zip(selected, geometries, strict=True)
            ):
                raise ValueError("non-transit route selections must be checked operational road objects")
            geometry = unary_union(geometries)
        elif method in {"osm_transit_road_reference", "osm_transit_road_reference_segment"}:
            # Moving bus/tram and source-reviewed public-transport consequences
            # can disclose a road without identifying a service. An unspecified
            # mode is accepted only as background road context, not as a moving
            # passenger incident or a complete operational line.
            transit = request.get("transit_route", {})
            review = request.get("transit_review", {})
            unspecified_background = (
                transit.get("mode") == "other" and request.get("role") == "background"
            )
            if (
                task != "checked_transit_route_geometry_required"
                or precision != "route"
                or (method == "osm_transit_road_reference" and len(object_groups) != 1)
                or (method == "osm_transit_road_reference_segment" and len(object_groups) % 3 != 0)
                or (transit.get("mode") not in {"bus", "tram"} and not unspecified_background)
                or transit.get("extent") != "source_segment"
                or review.get("status") != "reviewed_route"
            ):
                raise ValueError("transit road reference needs an explicitly reviewed bus/tram source segment or unspecified-mode background road context")
            path_rows = (
                [objects[ident] for group in object_groups[::3] for ident in group]
                if method == "osm_transit_road_reference_segment" else selected
            )
            if any(
                geometry.geom_type not in {"LineString", "MultiLineString"}
                or "road" not in row.get("roles", [])
                or row.get("tags", {}).get("highway") not in {
                    "motorway", "motorway_link", "trunk", "trunk_link",
                    "primary", "primary_link", "secondary", "secondary_link",
                    "tertiary", "tertiary_link", "unclassified", "residential",
                    "living_street", "service", "busway",
                }
                or not row.get("names")
                for row in path_rows
                for geometry in [shape(row["geometry"])]
            ):
                raise ValueError("transit road reference selections must be checked named operational roads")
            geometry = (
                source_road_segments([[objects[ident] for ident in group] for group in object_groups])
                if method == "osm_transit_road_reference_segment" else unary_union(geometries)
            )
        elif method == "osm_transit_line_reference":
            transit = request.get("transit_route", {})
            review = request.get("transit_review", {})
            if (task != "checked_transit_route_geometry_required" or precision != "route"
                    or transit.get("extent") not in {"source_segment", "full_line"}
                    or transit.get("mode") not in {"bus", "tram", "subway", "train", "ferry"}
                    or review.get("status") != "reviewed_route"):
                raise ValueError("carrier line reference needs an explicitly reviewed transit extent")
            lines = []
            for group in object_groups:
                refs = {objects[ident].get("tags", {}).get("ref") for ident in group}
                if len(refs) != 1 or not all(isinstance(ref, str) and ref for ref in refs):
                    raise ValueError("each carrier group must identify one exact native line")
                line = next(iter(refs))
                if line in lines:
                    raise ValueError("carrier line groups must be distinct")
                lines.append(line)
                expected = {ident for ident, row in objects.items()
                            if _source_route_relation(row, line, transit.get("mode"))}
                if not expected or set(group) != expected:
                    raise ValueError("carrier reference must cover every complete checked source relation")
            # This is a canonical reviewed line declaration, not parsing or
            # matching a police narrative. Combined lines have explicit groups.
            if " and ".join(lines) != transit.get("line"):
                raise ValueError("carrier groups differ from the explicitly reviewed line declaration")
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
        elif method == "osm_transit_road_segment":
            transit = request.get("transit_route", {})
            review = request.get("transit_review", {})
            if (task != "checked_transit_route_geometry_required" or precision != "route"
                    or transit.get("extent") != "source_segment"
                    or review.get("status") != "reviewed_route"
                    or not object_groups or len(object_groups) % 3):
                raise ValueError("road-bounded transit geometry needs an explicitly reviewed source segment")
            line, mode = transit.get("line"), transit.get("mode")
            for group in object_groups[::3]:
                for ident in group:
                    row = objects[ident]
                    proof = row.get("transit_member_source_proof", {})
                    if not any(
                        m.get("line") == line and m.get("mode") in {mode, "light_rail"}
                        and _source_route_relation(objects.get(f"osm/relation/{m.get('relation_id')}", {}), line, mode)
                        and proof.get("way_id") in objects[f"osm/relation/{m.get('relation_id')}"]["transit_source_proof"]["member_way_ids"]
                        for m in proof.get("memberships", [])
                    ):
                        raise ValueError("road-bounded track membership lacks a complete checked source relation")
            geometry = source_track_segments_between_roads(
                [[objects[ident] for ident in group] for group in object_groups], line=line, mode=mode,
            )
        elif method == "osm_unidentified_transit_segment":
            transit, review = request.get("transit_route", {}), request.get("transit_review", {})
            mode = transit.get("mode")
            unknown_label = {"subway": "unidentified U-Bahn line", "tram": "unidentified tram line"}.get(mode)
            if (task != "checked_transit_route_geometry_required" or precision != "route"
                    or unknown_label is None or transit.get("line") != unknown_label
                    or transit.get("extent") != "source_segment" or review.get("status") != "reviewed_route"
                    or len(object_groups) % 4 or any(len(g) != 1 for n,g in enumerate(object_groups) if n % 4 != 1)):
                raise ValueError("unidentified-service segment needs explicit unknown identity and native relation/path/stop/stop quartets")
            segments = []
            for offset in range(0, len(object_groups), 4):
                relation = objects[object_groups[offset][0]]
                native_line = relation.get("tags", {}).get("ref")
                if not _source_route_relation(relation, native_line, mode):
                    raise ValueError("unidentified-service corridor needs a complete native carrier relation")
                path = [objects[i] for i in object_groups[offset + 1]]
                for row in path:
                    member = row.get("transit_member_source_proof", {})
                    if (member.get("schema_version") != 1 or row.get("id") != f"osm/way/{member.get('way_id')}"
                            or member.get("way_id") not in relation["transit_source_proof"]["member_way_ids"]
                            or not any(m.get("relation_id") == relation["transit_source_proof"]["relation_id"]
                                       and m.get("line") == native_line and m.get("mode") in {mode, "light_rail"}
                                       for m in member.get("memberships", []))):
                        raise ValueError("unidentified-service path lacks selected complete native carrier membership")
                segments.append(source_track_segment(path,
                    [objects[object_groups[n][0]] for n in (offset+2, offset+3)], line=native_line, mode=mode))
            # Native membership verifies the geographic corridor only. It does
            # not change the source's undisclosed historical service identity.
            geometry = unary_union(segments)
        elif method == "osm_transit_segment":
            transit = request.get("transit_route", {})
            if (task != "checked_transit_route_geometry_required" or precision != "route"
                    or transit.get("extent") != "source_segment"
                    or not object_groups or len(object_groups) % 3
                    or any(len(group) != 1 for n, group in enumerate(object_groups) if n % 3)):
                raise ValueError("osm_transit_segment requires a reviewed source segment and two stop groups")
            geometry = unary_union([
                source_track_segment(
                    [objects[ident] for ident in object_groups[offset]],
                    [objects[group[0]] for group in object_groups[offset + 1:offset + 3]],
                    line=transit.get("line"), mode=transit.get("mode"),
                )
                for offset in range(0, len(object_groups), 3)
            ])
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
    if method == "osm_footprint" and include_footprint_count_points:
        point = geometry.representative_point()
        point_geojson = mapping(point)
        result["count_point"] = point_geojson
        result["count_point_sha256"] = _digest(point_geojson)
        result["count_point_method"] = "selected_osm_footprint_representative_point"
    elif method in {"osm_transit_road_reference", "osm_transit_road_reference_segment"}:
        result["geometry_usage"] = "source_road_reference_only"
        result["complete_transit_line"] = False
        if method == "osm_transit_road_reference_segment":
            result["source_road_extent"] = "native_endpoint_bounded"
        if request.get("transit_route", {}).get("mode") == "other":
            result["service_identity_known"] = False
            result["actual_transit_extent_known"] = False
    elif method == "osm_transit_line_reference":
        result["geometry_usage"] = "carrier_line_reference_only"
        result["complete_transit_line"] = False
        result["actual_transit_extent_known"] = False
    elif method == "osm_named_footprint_reference":
        result["geometry_usage"] = "source_footprint_reference_only"
    elif method == "osm_non_transit_footprint_reference":
        result["geometry_usage"] = "source_footprint_reference_only"
        result["actual_non_transit_extent_known"] = False
    elif method == "osm_unidentified_transit_segment":
        result["geometry_usage"] = "source_transit_corridor_reference_only"
        result["complete_transit_line"] = False
        result["service_identity_known"] = False
    elif method == "osm_intersection":
        candidate_geojson = mapping(intersection_candidates)
        result["intersection_candidates"] = candidate_geojson
        result["intersection_candidates_sha256"] = _digest(candidate_geojson)
        result["intersection_spread_m"] = round(spread, 3)
        result["count_point_method"] = "selected_osm_road_groups_intersection_medoid"
    return result


def _derived_geometry(decision, request, objects, border, city, *, include_footprint_count_points=True, source_pbf_sha256=None):
    if decision.get("method") == "osm_station_platform_footprint_reference":
        from .station_platform_references import station_platform_reference
        return station_platform_reference(decision, request, objects, border, source_pbf_sha256)
    if decision.get("method") == "osm_platform_point_collection_reference":
        from .native_platform_references import native_platform_reference
        return native_platform_reference(decision, request, objects, border)
    if decision.get("method") == "official_pdf_horizontal_circle_reference":
        from .official_pdf_references import derive_pdf_circle_reference
        return derive_pdf_circle_reference(decision, request, border, city)
    if decision.get("method") == "osm_static_road_reference_segment":
        from .static_road_references import derive_static_road_reference
        return derive_static_road_reference(
            decision, request, objects, border, city,
            compile_base=_derived_geometry_without_static_reference,
            include_footprint_count_points=False,
        )
    return _derived_geometry_without_static_reference(
        decision, request, objects, border, city,
        include_footprint_count_points=include_footprint_count_points,
    )


def compile_geometry_decisions(
    *, inventory: dict, geometry_index: dict, decision_envelope: dict, border,
    include_footprint_count_points: bool = True,
) -> dict:
    """Compile a partial or complete set of current LLM geometry decisions."""
    if type(include_footprint_count_points) is not bool:
        raise TypeError("include_footprint_count_points must be a boolean")
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
            geometry = _derived_geometry(
                decision, request, objects, border, city,
                include_footprint_count_points=include_footprint_count_points,
                source_pbf_sha256=geometry_index.get("source_pbf_sha256"),
            )
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
        **({"footprint_representative_points_enabled": False}
           if not include_footprint_count_points else {}),
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
    parser.add_argument(
        "--no-representative-points", action="store_true",
        help="Keep selected footprints without generating synthetic count points; retain original OSM points and actual road intersections.",
    )
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
        include_footprint_count_points=not args.no_representative_points,
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
