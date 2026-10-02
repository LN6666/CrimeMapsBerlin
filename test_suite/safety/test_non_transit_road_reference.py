"""A source motorway corridor is neither a vehicle trajectory nor a closure polygon."""
import copy

import pytest
from shapely.geometry import box

from crimemapsberlin.geometry_decisions import _derived_geometry
from crimemapsberlin.map_decisions import _count_point
from crimemapsberlin.reviewed_city_map import _scene


def fixture():
    road = {"id": "osm/way/1", "roles": ["road"], "names": ["A 115"],
            "tags": {"highway": "motorway", "ref": "A 115"},
            "geometry": {"type": "LineString", "coordinates": [(-1, 0), (0, 0), (1, 0), (2, 0), (3, 0)]}}
    nodes = [{"id": f"osm/node/{ident}", "roles": ["road", "named_object"], "names": [name],
              "tags": {"highway": "motorway_junction", "name": name},
              "geometry": {"type": "Point", "coordinates": (x, 0)}}
             for ident, x, name in ((2, 0, "Start"), (3, 2, "End"))]
    request = {"geometry_task": "checked_non_transit_route_geometry_required", "precision": "route",
               "transit_review": {"status": "reviewed_non_transit_route"}, "transit_route": None}
    decision = {"verdict": "resolved", "method": "osm_non_transit_road_reference_segment",
                "osm_object_groups": [[road["id"]], [nodes[0]["id"]], [nodes[1]["id"]]]}
    return decision, request, {r["id"]: r for r in (road, *nodes)}


def derive(decision, request, objects):
    return _derived_geometry(decision, request, objects, box(-2, -2, 5, 5), "berlin",
                             include_footprint_count_points=True)


def test_motorway_reference_preserves_native_vertices_and_unknown_actual_movement():
    decision, request, objects = fixture()
    original = copy.deepcopy(request)
    result = derive(decision, request, objects)
    assert result["geometry"]["coordinates"] == ((0., 0.), (1., 0.), (2., 0.))
    assert result["geometry_usage"] == "source_road_reference_only"
    assert result["source_road_extent"] == "native_endpoint_bounded"
    assert result["actual_non_transit_extent_known"] is False
    assert "complete_transit_line" not in result and "count_point" not in result
    assert request == original


@pytest.mark.parametrize("change", [
    {"precision": "street", "geometry_task": "checked_road_geometry_required"},
    {"geometry_task": "checked_transit_route_geometry_required"},
    {"transit_review": {"status": "unresolved"}},
    {"transit_route": {"mode": "bus", "line": "M1", "extent": "source_segment"}},
])
def test_non_transit_reference_rejects_unreviewed_or_public_transit_request(change):
    decision, request, objects = fixture()
    request.update(change)
    with pytest.raises(ValueError, match="explicitly reviewed non-transit"):
        derive(decision, request, objects)


@pytest.mark.parametrize("change", ["off_vertex", "signal", "construction", "repeat_path"])
def test_non_transit_reference_rejects_false_endpoints_or_roads(change):
    decision, request, objects = fixture()
    if change == "off_vertex":
        objects["osm/node/3"]["geometry"]["coordinates"] = (1.5, 0)
    elif change == "signal":
        objects["osm/node/3"]["tags"]["highway"] = "traffic_signals"
    elif change == "construction":
        objects["osm/way/1"]["tags"]["highway"] = "construction"
    else:
        decision["osm_object_groups"] += copy.deepcopy(decision["osm_object_groups"])
    with pytest.raises(ValueError):
        derive(decision, request, objects)


def test_non_transit_reference_export_does_not_become_transit_or_count_point():
    decision, request, objects = fixture()
    decision["review_note"] = "Road reference only; actual vehicle and closure extent unknown."
    row = {"decision": decision, "derived_geometry": derive(decision, request, objects)}
    location = {"location_id": "1:location:1", "label": "recovery near crash corridor",
                "role": "operation", "precision": "route", "city_scope": "in_city",
                "evidence_quotes": ["between Start and End"], "details": "Work extent unknown.",
                "poi_contexts": [], "event_time": {"display": "yesterday"}}
    scene = _scene(location, row, {}, {}, None)
    assert scene["geometry_usage"] == "source_road_reference_only"
    assert scene["actual_non_transit_extent_known"] is False
    assert scene["source_road_extent"] == "native_endpoint_bounded"
    assert scene["coordinates"] is None and scene["primary_for_count"] is False
    assert scene["details"] == location["details"] and scene["event_time"] == location["event_time"]
    assert "complete_transit_line" not in scene and "transit_route" not in scene
    assert _count_point(row) is None
