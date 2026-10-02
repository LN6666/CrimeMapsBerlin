"""Source-bound municipal district footprints, kept separate from OSM objects.

Only original Frankfurt WFS polygons are accepted. Reprojection preserves every
source vertex and hole. Small differences between independently sourced city
borders are measured and bound to the reviewed index, never clipped away.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime

from shapely.geometry import Point, mapping, shape
from shapely.ops import transform

from .spatial import metric_transforms

METHOD = "official_district_footprint_reference"
SOURCE_URL = "https://geowebdienste.frankfurt.de/WFS_Stadtgebietsgliederung"
INDEX_KEYS = {
    "schema_version", "city", "source_url", "source_crs", "acquired_at",
    "response_sha256_observed", "original_feature_collection",
    "original_feature_collection_sha256", "references",
}
REFERENCE_KEYS = {
    "id", "feature_id", "feature_sha256", "reviewed_location_bindings",
    "municipal_boundary_sha256", "reviewed_outside_area_m2",
    "reviewed_max_outside_vertex_distance_m",
}


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def _sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        ch in "0123456789abcdef" for ch in value)


def validate_official_reference_index(index: dict, *, city: str, border) -> dict:
    if not isinstance(index, dict) or set(index) != INDEX_KEYS | {"index_sha256"}:
        raise ValueError("official reference index has missing or unknown fields")
    core = {key: index[key] for key in INDEX_KEYS}
    if index["index_sha256"] != _digest(core):
        raise ValueError("official reference index digest is stale")
    if (index["schema_version"] != 1 or city != "frankfurt"
            or index["city"] != city or index["source_url"] != SOURCE_URL
            or index["source_crs"] != "EPSG:25832"):
        raise ValueError("official reference source, city or CRS differs")
    acquired = datetime.fromisoformat(index["acquired_at"])
    if acquired.tzinfo is None or acquired.utcoffset() is None:
        raise ValueError("official acquisition time needs a timezone")
    if not _sha(index["response_sha256_observed"]):
        raise ValueError("official reference needs its observed response digest")
    fc = index["original_feature_collection"]
    if (not isinstance(fc, dict) or fc.get("type") != "FeatureCollection"
            or fc.get("crs") != {"type": "name", "properties": {"name": "EPSG:25832"}}
            or index["original_feature_collection_sha256"] != _digest(fc)):
        raise ValueError("official original feature collection or CRS is stale")
    features = {}
    for feature in fc.get("features", []):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError("invalid official source feature")
        props = feature.get("properties", {})
        ident = props.get("GmlID")
        if (not isinstance(ident, str) or not ident.startswith("Stadtbezirke.")
                or ident in features or type(props.get("STBZ_ID")) is not int
                or not isinstance(props.get("STBZ_NAME"), str)
                or not props["STBZ_NAME"].strip()):
            raise ValueError("official source feature identity is invalid or duplicated")
        features[ident] = feature
    metric, wgs84 = metric_transforms("EPSG:25832")
    metric_border = transform(metric, border)
    boundary_sha = _digest(mapping(border))
    refs = index["references"]
    if not isinstance(refs, list) or not refs:
        raise ValueError("official reference index needs reviewed selections")
    checked = {}
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != REFERENCE_KEYS:
            raise ValueError("official reference has missing or unknown fields")
        ident = ref["id"]
        feature = features.get(ref["feature_id"])
        if (feature is None or ident != f"official/frankfurt/{ref['feature_id']}"
                or ident in checked or ref["feature_sha256"] != _digest(feature)
                or ref["municipal_boundary_sha256"] != boundary_sha):
            raise ValueError("official feature or municipal boundary binding is stale")
        native = shape(feature["geometry"])
        if native.geom_type not in {"Polygon", "MultiPolygon"} or native.is_empty or not native.is_valid:
            raise ValueError("official district must retain a valid original polygon")
        polygons = list(native.geoms) if native.geom_type == "MultiPolygon" else [native]
        vertices = [p for poly in polygons for ring in [poly.exterior, *poly.interiors]
                    for p in ring.coords]
        outside = native.difference(metric_border).area
        distance = max(Point(p).distance(metric_border) for p in vertices)
        for key, actual in [("reviewed_outside_area_m2", outside),
                            ("reviewed_max_outside_vertex_distance_m", distance)]:
            expected = ref[key]
            if (type(expected) not in {int, float} or not math.isfinite(expected)
                    or not math.isclose(expected, actual, rel_tol=0, abs_tol=1e-6)):
                raise ValueError("official municipal difference differs from reviewed proof")
        # This exception belongs solely to independent official background
        # footprints; it never changes the OSM municipal-containment contract.
        if outside > 5 or distance > 1 or native.intersection(metric_border).area <= 0:
            raise ValueError("official footprint exceeds the bounded municipal difference")
        bindings = ref["reviewed_location_bindings"]
        if not isinstance(bindings, list) or not bindings:
            raise ValueError("official reference needs reviewed source-location bindings")
        seen = set()
        for binding in bindings:
            if (not isinstance(binding, dict) or set(binding) != {
                    "location_id", "source_sha256", "geometry_request_sha256"}
                    or not isinstance(binding["location_id"], str)
                    or binding["location_id"] in seen
                    or not _sha(binding["source_sha256"])
                    or not _sha(binding["geometry_request_sha256"])):
                raise ValueError("official source-location binding is invalid or duplicated")
            seen.add(binding["location_id"])
        geometry = mapping(transform(wgs84, native))
        projected = shape(geometry)
        if projected.is_empty or not projected.is_valid:
            raise ValueError("official original polygon cannot be reprojected")
        checked[ident] = {
            "geometry": geometry, "bindings": bindings,
            "provenance": {
                "reference_id": ident, "source_url": index["source_url"],
                "source_crs": index["source_crs"], "feature_id": ref["feature_id"],
                "feature_sha256": ref["feature_sha256"],
                "feature_name": feature["properties"]["STBZ_NAME"],
                "acquired_at": index["acquired_at"],
                "original_feature_collection_sha256": index["original_feature_collection_sha256"],
                "municipal_boundary_sha256": boundary_sha,
                "outside_municipality_area_m2": outside,
                "max_outside_vertex_distance_m": distance,
                "projection": "EPSG:25832 to EPSG:4326, original vertices and holes",
                "original_footprint_clipped": False,
                "historical_event_boundary_verified": False,
            },
        }
    return checked


def derive_official_district_reference(decision: dict, request: dict, references: dict) -> dict:
    if (decision["osm_object_groups"] or request.get("coordinates") is not None
            or request.get("geometry_task") != "checked_district_geometry_required"
            or request.get("precision") != "district" or request.get("role") != "background"
            or request.get("city_scope") != "in_city"
            or request.get("transit_route")):
        raise ValueError("official district footprint needs a background district with no event point or route")
    ident = decision.get("official_reference_id")
    ref = references.get(ident) if isinstance(ident, str) else None
    if ref is None:
        raise ValueError("selected official reference is absent from the checked index")
    binding = {key: request[key] for key in (
        "location_id", "source_sha256", "geometry_request_sha256")}
    if binding not in ref["bindings"]:
        raise ValueError("official reference was not reviewed for this source-location request")
    geometry = ref["geometry"]
    return {
        "type": geometry["type"], "geometry": geometry,
        "geometry_sha256": _digest(geometry), "source_object_ids": [], "source_object_groups": [],
        "source_reference_ids": [ident], "source_reference_provenance": [ref["provenance"]],
        "geometry_usage": "source_footprint_reference_only",
        "actual_event_position_known": False, "actual_event_extent_known": False,
    }
