"""Metric clipping of a reviewed named street to one reviewed district.

This produces a current geographic reference, never an actual event extent,
historical boundary, journey or count point. Names are selected by the reviewer;
the compiler checks the complete same-name street membership inside the area.
"""
from __future__ import annotations
from shapely.geometry import shape
from shapely.ops import transform, unary_union
from .city_geometry_index import OPERATIONAL_HIGHWAYS
from .poi_cities import POI_CITY_SPECS, geometry_covered_by
from .spatial import metric_transforms


def _lines(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry] if geometry.length > 0 else []
    if geometry.geom_type in {"MultiLineString", "GeometryCollection"}:
        return [line for member in geometry.geoms for line in _lines(member)]
    return []


def district_road_reference(groups: list[list[dict]], *, objects: dict, border, city: str,
                            road_identity_tag: str = "name"):
    if len(groups) != 2 or not groups[0] or len(groups[1]) != 1:
        raise ValueError("district road reference needs road objects and one district polygon")
    roads, boundary_rows = groups
    boundary = boundary_rows[0]; tags = boundary.get("tags", {})
    district = shape(boundary["geometry"])
    district_name = tags.get("name")
    if ("administrative_boundary" not in boundary.get("roles", [])
            or tags.get("boundary") != "administrative" or tags.get("admin_level") != "10"
            or not isinstance(district_name, str) or not district_name.strip()
            or district_name not in boundary.get("names", [])
            or district.geom_type not in {"Polygon", "MultiPolygon"}
            or district.is_empty or not district.is_valid
            or not geometry_covered_by(border, district)):
        raise ValueError("district road reference needs a checked independent district boundary")
    if road_identity_tag not in {"name", "ref"}:
        raise ValueError("district road identity must use an original name or ref")
    street_name = roads[0].get("tags", {}).get(road_identity_tag)
    if not isinstance(street_name, str) or not street_name.strip():
        raise ValueError("district road reference needs an original street name")
    if road_identity_tag == "ref" and ";" in street_name:
        raise ValueError("district highway reference needs one original road ref")
    def matches(row):
        return ("road" in row.get("roles", []) and row.get("tags", {}).get(road_identity_tag) == street_name
                and street_name in row.get("names", [])
                and row.get("tags", {}).get("highway") in OPERATIONAL_HIGHWAYS
                and row.get("geometry", {}).get("type") in {"LineString", "MultiLineString"})
    if any(not matches(row) for row in roads):
        raise ValueError("district road selections must retain one original operational street name")
    metric, wgs84 = metric_transforms(POI_CITY_SPECS[city].epsg)
    metric_district = transform(metric, district)
    expected = {}
    for ident, row in sorted(objects.items()):
        if not matches(row):
            continue
        original = transform(metric, shape(row["geometry"]))
        parts = _lines(original.intersection(metric_district))
        if parts:
            expected[ident] = (original, parts)
    selected_ids = [row["id"] for row in roads]
    if len(selected_ids) != len(set(selected_ids)) or set(selected_ids) != set(expected):
        raise ValueError("district road reference must retain every matching positive-length in-district road object")
    clipped = unary_union([line for ident in sorted(expected) for line in expected[ident][1]])
    if clipped.is_empty or clipped.geom_type not in {"LineString", "MultiLineString"}:
        raise ValueError("district road intersection has no linear reference geometry")
    geometry = transform(wgs84, clipped)
    return geometry, {
        "district_object_id": boundary["id"], "district_name": district_name,
        ("street_name" if road_identity_tag == "name" else "road_ref"): street_name,
        "metric_crs": f"EPSG:{POI_CITY_SPECS[city].epsg}",
        "method": "metric_street_intersection_with_reviewed_district",
        "selected_original_length_m": sum(original.length for original, _ in expected.values()),
        "retained_reference_length_m": clipped.length,
        "per_original_object": [{"id": ident, "original_length_m": original.length,
            "retained_length_m": sum(part.length for part in parts),
            "geometry_sha256": objects[ident]["geometry_sha256"]}
            for ident, (original, parts) in expected.items()],
        "boundary_geometry_sha256": boundary["geometry_sha256"],
        "boundary_intersection_vertices_are_event_coordinates": False,
        "historical_boundary_verified": False,
    }
