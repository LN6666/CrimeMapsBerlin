import copy

import pytest
from shapely.geometry import box

from crimemapsberlin.geometry_decisions import _derived_geometry


def fixture():
    tracks = [
        {"id": "osm/way/1", "names": ["M2"], "roles": ["named_object"],
         "tags": {"railway": "tram"}, "dimension": "line",
         "geometry": {"type": "LineString", "coordinates": [(-1, 0), (0, 0), (1, 0), (2, 0), (3, 0)]}},
        {"id": "osm/way/2", "names": ["M2"], "roles": ["named_object"],
         "tags": {"railway": "tram"}, "dimension": "line",
         "geometry": {"type": "LineString", "coordinates": [(3, .1), (2, .1), (1, .1), (0, .1), (-1, .1)]}},
    ]
    for row in tracks:
        row["transit_member_source_proof"] = {
            "schema_version": 1, "way_id": int(row["id"].split("/")[-1]),
            "source_way_digest": "a" * 64,
            "line_alias_basis": "verified_operational_route_path_membership",
            "memberships": [{"relation_id": 99, "line": "M2", "mode": "tram"}],
        }
    roads = [{"id": f"osm/way/{i}", "names": [name], "roles": ["named_object", "road"],
              "tags": {"highway": "primary"}, "dimension": "line",
              "geometry": {"type": "LineString", "coordinates": [(x, -.5), (x, 0), (x, .1), (x, .5)]}}
             for i, x, name in [(3, 0, "Start road"), (4, 2, "End road")]]
    relation = {"id": "osm/relation/99", "roles": ["named_object", "transit_route"],
                "names": ["M2"], "tags": {"type": "route", "route": "tram", "ref": "M2"},
                "geometry": tracks[0]["geometry"], "transit_source_proof": {
                    "schema_version": 1, "relation_id": 99, "complete": True,
                    "member_way_ids": [1, 2], "member_way_count": 2,
                    "member_sequence": [1, 2], "member_source_digest": "b" * 64,
                }}
    objects = {r["id"]: r for r in [*tracks, *roads, relation]}
    decision = {"verdict": "resolved", "method": "osm_transit_road_segment",
                "osm_object_groups": [["osm/way/1"], ["osm/way/3"], ["osm/way/4"],
                                      ["osm/way/2"], ["osm/way/3"], ["osm/way/4"]]}
    request = {"geometry_task": "checked_transit_route_geometry_required", "precision": "route",
               "transit_review": {"status": "reviewed_route"},
               "transit_route": {"line": "M2", "mode": "tram", "extent": "source_segment"}}
    return decision, request, objects


def derive(decision, request, objects):
    return _derived_geometry(decision, request, objects, box(-2, -1, 4, 1), "berlin")


def test_native_rail_road_vertices_cut_both_directions_without_count_point():
    decision, request, objects = fixture()
    result = derive(decision, request, objects)
    assert result["geometry"]["type"] == "MultiLineString"
    assert result["geometry"]["coordinates"] == (((0., 0.), (1., 0.), (2., 0.)),
                                                   ((0., .1), (1., .1), (2., .1)))
    assert result["source_object_ids"] == ["osm/way/1", "osm/way/3", "osm/way/4", "osm/way/2"]
    assert result["source_object_groups"] == decision["osm_object_groups"]
    assert "count_point" not in result


@pytest.mark.parametrize("change", ["off_vertex", "missing_relation", "wrong_member", "inactive", "platform", "wrong_line", "full_line", "bus", "unknown_review", "repeat_path"])
def test_road_bounded_transit_rejects_projection_unproved_membership_and_wrong_scope(change):
    decision, request, objects = fixture()
    if change == "off_vertex":
        objects["osm/way/4"]["geometry"]["coordinates"] = [(1.5, -.5), (1.5, .5)]
    elif change == "missing_relation":
        objects.pop("osm/relation/99")
    elif change == "wrong_member":
        objects["osm/relation/99"]["transit_source_proof"].update(member_way_ids=[8, 9], member_sequence=[8, 9])
    elif change == "inactive":
        objects["osm/way/1"]["tags"]["construction:railway"] = "tram"
    elif change == "platform":
        objects["osm/way/1"]["tags"]["railway"] = "platform"
    elif change == "wrong_line":
        request["transit_route"]["line"] = "M10"
    elif change == "full_line":
        request["transit_route"]["extent"] = "full_line"
    elif change == "bus":
        request["transit_route"]["mode"] = "bus"
    elif change == "unknown_review":
        request["transit_review"]["status"] = "unresolved"
    else:
        decision["osm_object_groups"][3] = copy.deepcopy(decision["osm_object_groups"][0])
    with pytest.raises(ValueError):
        derive(decision, request, objects)
