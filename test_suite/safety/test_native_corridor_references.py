import copy
import json

import pytest
from shapely.geometry import box

from crimemapsberlin.city_geometry_index import (
    native_road_vertex_object,
    validate_geometry_index,
    write_geometry_index,
)
from crimemapsberlin.city_road_segment import source_road_segments
from crimemapsberlin.geometry_decisions import _derived_geometry


def native_vertex():
    node = {"id": 12, "tags": {}, "coordinates": [1, 0]}
    way = {"id": 10, "tags": {"highway": "residential", "name": "Road"},
           "node_ids": [11,12,13], "geometry": {"type": "LineString", "coordinates": [[0,0],[1,0],[2,0]]}}
    source = {"sha256": "a"*64, "pbf_timestamp": "2026-09-25T20:24:36Z"}
    return node, way, source, box(-1,-1,3,1)


def test_unnamed_native_vertex_roundtrips_with_complete_source_proof_and_no_fake_name(tmp_path):
    node, way, source, border = native_vertex()
    row = native_road_vertex_object(source_node=node, source_way=way, source_metadata=source, border=border)
    assert row["names"] == [] and row["tags"] == {} and row["roles"] == ["road"]
    boundary = {"id": "osm/relation/1", "source_pbf_sha256": source["sha256"], "geometry": border.__geo_interface__}
    path = tmp_path / "index.json"
    write_geometry_index(city="berlin", objects=[row], border=border, boundary_metadata=boundary,
                         source_metadata=source, pipeline_version=4, output=path)
    result = json.loads(path.read_text())
    assert validate_geometry_index(result, city="berlin", border=border, boundary_metadata=boundary, source_metadata=source)["passed"]
    result["objects"][0]["native_road_vertex_source_proof"]["source_pbf_sha256"] = "b"*64
    assert not validate_geometry_index(result, city="berlin", border=border, boundary_metadata=boundary, source_metadata=source)["passed"]
    with pytest.raises(ValueError):
        write_geometry_index(city="berlin", objects=[row], border=border, boundary_metadata=boundary,
                             source_metadata=source, pipeline_version=3, output=path)


@pytest.mark.parametrize("change", ["mid_edge", "wrong_id", "wrong_sequence", "inactive", "outside"])
def test_native_vertex_rejects_unproved_or_projected_endpoints(change):
    node, way, source, border = native_vertex()
    if change == "mid_edge":
        node["coordinates"] = [1.5,0]
    elif change == "wrong_id":
        node["id"] = 99
    elif change == "wrong_sequence":
        way["node_ids"] = [11,12]
    elif change == "inactive":
        way["tags"]["construction:highway"] = "residential"
    else:
        border = box(3,3,4,4)
    with pytest.raises(ValueError):
        native_road_vertex_object(source_node=node, source_way=way, source_metadata=source, border=border)


def test_native_road_vertex_is_only_a_range_endpoint_not_an_event_point():
    node, way, source, border = native_vertex()
    vertex = native_road_vertex_object(source_node=node, source_way=way, source_metadata=source, border=border)
    path = {"id": "osm/way/10", "roles": ["road"], "tags": way["tags"], "geometry": way["geometry"]}
    end = {"id": "osm/way/20", "roles": ["road"], "tags": {"highway": "residential"},
           "geometry": {"type": "LineString", "coordinates": [[2,-1],[2,0],[2,1]]}}
    assert list(source_road_segments([[path],[vertex],[end]]).coords) == [(1,0),(2,0)]
    with pytest.raises(ValueError, match="endpoint references only"):
        _derived_geometry({"verdict": "resolved", "method": "osm_point", "osm_object_groups": [[vertex["id"]]]},
            {"geometry_task": "checked_point_geocode_required", "precision": "point"}, {vertex["id"]: vertex}, border, "berlin")


def unidentified_fixture():
    track = {"id": "osm/way/1", "names": ["U5"], "roles": ["named_object"], "tags": {"railway": "subway"},
             "geometry": {"type": "LineString", "coordinates": [[-1,0],[0,0],[1,0],[2,0],[3,0]]},
             "transit_member_source_proof": {"schema_version": 1, "way_id": 1, "source_way_digest": "a"*64,
                 "memberships": [{"relation_id": 99, "mode": "subway", "line": "U5"}]}}
    relation = {"id": "osm/relation/99", "names": ["U5"], "roles": ["transit_route"],
                "tags": {"type": "route", "route": "subway", "ref": "U5"}, "geometry": track["geometry"],
                "transit_source_proof": {"schema_version": 1, "relation_id": 99, "complete": True,
                    "member_way_ids": [1], "member_sequence": [1], "member_way_count": 1, "member_source_digest": "b"*64}}
    stops = [{"id": f"osm/node/{i}", "names": [label], "roles": ["named_object"],
              "tags": {"public_transport": "stop_position", "subway": "yes"},
              "geometry": {"type": "Point", "coordinates": [x,0]}}
             for i,x,label in [(2,0,"Start"),(3,2,"End")]]
    objects = {r["id"]: r for r in [track,relation,*stops]}
    decision = {"verdict": "resolved", "method": "osm_unidentified_transit_segment",
                "osm_object_groups": [[relation["id"]],[track["id"]],[stops[0]["id"]],[stops[1]["id"]]]}
    request = {"geometry_task": "checked_transit_route_geometry_required", "precision": "route",
               "transit_review": {"status": "reviewed_route"},
               "transit_route": {"mode": "subway", "line": "unidentified U-Bahn line", "extent": "source_segment"}}
    return decision,request,objects


def test_unidentified_service_uses_native_bounded_corridor_without_assigning_a_line():
    decision,request,objects = unidentified_fixture()
    original = copy.deepcopy(request)
    result = _derived_geometry(decision,request,objects,box(-2,-1,4,1),"berlin")
    assert result["geometry"]["coordinates"] == ((0.,0.),(1.,0.),(2.,0.))
    assert result["service_identity_known"] is False and result["complete_transit_line"] is False
    assert result["geometry_usage"] == "source_transit_corridor_reference_only"
    assert request == original and "count_point" not in result


def shared_carrier_fixture():
    decision, request, objects = unidentified_fixture()
    alternative = copy.deepcopy(objects["osm/relation/99"])
    alternative.update(id="osm/relation/100", names=["U4"])
    alternative["tags"]["ref"] = "U4"
    alternative["transit_source_proof"]["relation_id"] = 100
    objects[alternative["id"]] = alternative
    track = objects["osm/way/1"]
    track["names"].append("U4")
    track["transit_member_source_proof"]["memberships"].append(
        {"relation_id": 100, "mode": "subway", "line": "U4"}
    )
    decision["osm_object_groups"].extend(
        [[alternative["id"]], [track["id"]], ["osm/node/2"], ["osm/node/3"]]
    )
    return decision, request, objects


def test_alternative_carriers_preserve_shared_native_objects_and_unknown_service():
    decision, request, objects = shared_carrier_fixture()
    original = copy.deepcopy(request)
    result = _derived_geometry(decision, request, objects, box(-2, -1, 4, 1), "berlin")
    assert result["source_object_groups"] == decision["osm_object_groups"]
    assert result["source_object_ids"] == list(dict.fromkeys(
        ident for group in decision["osm_object_groups"] for ident in group
    ))
    assert result["service_identity_known"] is False and "count_point" not in result
    assert request == original


@pytest.mark.parametrize("change", ["duplicate_carrier", "repeated_path", "missing_membership"])
def test_shared_objects_do_not_bypass_each_alternative_carrier_validation(change):
    decision, request, objects = shared_carrier_fixture()
    if change == "duplicate_carrier":
        decision["osm_object_groups"][4] = ["osm/relation/99"]
    elif change == "repeated_path":
        decision["osm_object_groups"][5].append("osm/way/1")
    else:
        objects["osm/way/1"]["transit_member_source_proof"]["memberships"].pop()
    with pytest.raises(ValueError):
        _derived_geometry(decision, request, objects, box(-2, -1, 4, 1), "berlin")


@pytest.mark.parametrize("change", ["known_line", "full_line", "unreviewed", "incomplete_relation", "wrong_membership", "station_label", "projected_stop"])
def test_unidentified_corridor_rejects_scope_and_source_membership_shortcuts(change):
    decision,request,objects = unidentified_fixture()
    if change == "known_line":
        request["transit_route"]["line"] = "U5"
    elif change == "full_line":
        request["transit_route"]["extent"] = "full_line"
    elif change == "unreviewed":
        request["transit_review"]["status"] = "unresolved"
    elif change == "incomplete_relation":
        objects["osm/relation/99"]["transit_source_proof"]["complete"] = False
    elif change == "wrong_membership":
        objects["osm/way/1"]["transit_member_source_proof"]["memberships"][0]["relation_id"] = 100
    elif change == "station_label":
        objects["osm/node/2"]["tags"]["public_transport"] = "station"
    else:
        objects["osm/node/2"]["geometry"]["coordinates"] = [.5,0]
    with pytest.raises(ValueError):
        _derived_geometry(decision,request,objects,box(-2,-1,4,1),"berlin")
