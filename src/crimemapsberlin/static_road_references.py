"""Keep a checked road range as a reference for a static, imprecise scene.

The caller supplies its strict native road-segment compiler. This adapter does
not identify a sidewalk, car park, building, business, or exact incident point.
"""

from copy import deepcopy

METHOD = "osm_static_road_reference_segment"


def derive_static_road_reference(
    decision, request, objects, border, city, *, compile_base,
    include_footprint_count_points=False,
):
    """Delegate native range calculation without turning it into a venue."""
    if (
        decision.get("method") != METHOD
        or decision.get("verdict") != "resolved"
        or request.get("precision") != "street"
        or request.get("geometry_task") != "checked_road_geometry_required"
        or request.get("coordinates") is not None
        or request.get("city_scope") != "in_city"
        or request.get("transit_route") is not None
        or (request.get("transit_review") or {}).get("status") != "not_applicable"
    ):
        raise ValueError("static road reference needs an in-city street with no source point or transit route")
    mapped = deepcopy(decision)
    mapped["method"] = "osm_road_segment"
    result = compile_base(
        mapped, request, objects, border, city,
        include_footprint_count_points=False,
    )
    if (
        not isinstance(result, dict)
        or result.get("type") not in {"LineString", "MultiLineString"}
        or any(key.startswith("count_point") for key in result)
    ):
        raise ValueError("static reference must retain native lines without a count point")
    result = deepcopy(result)
    result.update(
        geometry_usage="source_road_reference_only",
        source_road_extent="native_endpoint_bounded",
        static_scene_reference=True,
        actual_event_position_known=False,
        actual_static_scene_extent_known=False,
    )
    return result
