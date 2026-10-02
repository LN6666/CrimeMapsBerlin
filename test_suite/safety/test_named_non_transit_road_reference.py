"""An entire source-named road/tunnel can be context, never a guessed actual route."""
import copy

import pytest
from test_non_transit_road_reference import derive, fixture

from crimemapsberlin.map_decisions import _count_point
from crimemapsberlin.reviewed_city_map import _scene


def named_reference():
    decision, request, objects = fixture()
    decision.update(method="osm_non_transit_road_reference", osm_object_groups=[["osm/way/1"]],
                    review_note="Source-named tunnel reference only; no actual traffic-state finding.")
    return decision, request, objects


def test_whole_named_road_preserves_original_geometry_and_unknown_actual_extent():
    decision, request, objects = named_reference()
    original = copy.deepcopy(request)
    result = derive(decision, request, objects)
    assert result["geometry"]["coordinates"] == tuple(tuple(c) for c in objects["osm/way/1"]["geometry"]["coordinates"])
    assert result["geometry_usage"] == "source_road_reference_only"
    assert result["actual_non_transit_extent_known"] is False
    assert "source_road_extent" not in result and "complete_transit_line" not in result
    assert "count_point" not in result and request == original


@pytest.mark.parametrize("change", ["unreviewed", "transit", "unnamed", "point", "construction", "multiple_groups"])
def test_whole_named_road_rejects_unreviewed_or_wrong_objects(change):
    decision, request, objects = named_reference()
    if change == "unreviewed":
        request["transit_review"]["status"] = "unresolved"
    elif change == "transit":
        request["transit_route"] = {"mode": "bus", "line": "M29"}
    elif change == "unnamed":
        objects["osm/way/1"]["names"] = []
    elif change == "point":
        objects["osm/way/1"]["geometry"] = {"type": "Point", "coordinates": (0, 0)}
    elif change == "construction":
        objects["osm/way/1"]["tags"]["highway"] = "construction"
    else:
        decision["osm_object_groups"].append(["osm/node/2"])
    with pytest.raises(ValueError):
        derive(decision, request, objects)


def test_named_road_reference_export_keeps_original_details_and_no_transit_claim():
    decision, request, objects = named_reference()
    row = {"decision": decision, "derived_geometry": derive(decision, request, objects)}
    location = {"location_id": "1:location:1", "label": "tunnel advised open on Sunday",
                "role": "background", "precision": "route", "city_scope": "in_city",
                "evidence_quotes": ["Sunday advice"], "details": "Announced availability, not measured traffic.",
                "poi_contexts": [], "event_time": {"display": "Sunday"}}
    scene = _scene(location, row, {}, {}, None)
    assert scene["geometry_usage"] == "source_road_reference_only"
    assert scene["actual_non_transit_extent_known"] is False
    assert scene["coordinates"] is None and scene["primary_for_count"] is False
    assert scene["event_time"] == location["event_time"] and scene["details"] == location["details"]
    assert "complete_transit_line" not in scene and "transit_route" not in scene
    assert _count_point(row) is None
    with pytest.raises(ValueError, match="road reference cannot"):
        _scene(location, row, {}, {}, location["location_id"])


def test_road_reference_cannot_use_a_forged_point_or_count_point():
    decision, request, objects = named_reference()
    row = {"decision": decision, "derived_geometry": derive(decision, request, objects)}
    point = {"type": "Point", "coordinates": [0, 0]}
    row["derived_geometry"].update(type="Point", geometry=point, count_point=point)
    assert _count_point(row) is None
    location = {"location_id": "1:location:1", "label": "road reference", "role": "background",
                "precision": "route", "city_scope": "in_city", "evidence_quotes": ["road"]}
    assert _scene(location, row, {}, {}, None)["coordinates"] is None
