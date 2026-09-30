import copy

import pytest
from shapely.geometry import LineString, box, mapping, shape

from crimemapsberlin.city_transit_index import route_object
from crimemapsberlin.geometry_decisions import compile_geometry_decisions


def _relation():
    return {
        "id": 20,
        "tags": {"type": "route", "route": "subway", "ref": "U3", "name": "U3: A => B"},
        "members": [
            {"type": "n", "ref": 90, "role": "stop"},
            {"type": "w", "ref": 91, "role": "platform"},
            {"type": "w", "ref": 10, "role": ""},
            {"type": "w", "ref": 11, "role": ""},
        ],
    }


def _ways():
    return {
        10: {"tags": {"railway": "subway", "name": "U2"},
             "geometry": mapping(LineString([(1, 1), (2, 1)]))},
        11: {"tags": {"railway": "subway", "name": "U3"},
             "geometry": mapping(LineString([(2, 1), (3, 1)]))},
        12: {"tags": {"railway": "construction", "name": "U3"},
             "geometry": mapping(LineString([(3, 1), (4, 1)]))},
    }


def test_route_members_include_shared_unnamed_line_parts_and_exclude_nonmembers():
    row = route_object(_relation(), _ways(), box(0, 0, 5, 5))
    assert row["names"] == ["U3", "U3: A => B"]
    assert shape(row["geometry"]).length == 2
    assert row["transit_source_proof"]["member_way_ids"] == [10, 11]
    assert row["transit_source_proof"]["complete"] is True
    assert row["tags"]["ref"] == "U3"


def test_missing_route_path_does_not_produce_a_partial_full_line():
    ways = _ways()
    del ways[10]
    with pytest.raises(ValueError, match="absent from source"):
        route_object(_relation(), ways, box(0, 0, 5, 5))


def test_construction_path_member_rejects_the_whole_operating_route():
    relation = _relation()
    relation["members"].append({"type": "w", "ref": 12, "role": ""})
    with pytest.raises(ValueError, match="inactive"):
        route_object(relation, _ways(), box(0, 0, 5, 5))


def test_unknown_nested_member_is_not_silently_omitted():
    relation = _relation()
    relation["members"].append({"type": "r", "ref": 100, "role": ""})
    with pytest.raises(ValueError, match="unsupported route path member"):
        route_object(relation, _ways(), box(0, 0, 5, 5))


def test_route_geometry_is_clipped_without_a_representative_point():
    row = route_object(_relation(), _ways(), box(1.5, 0, 2.5, 5))
    assert shape(row["geometry"]).length == 1
    assert box(1.5, 0, 2.5, 5).covers(shape(row["geometry"]))
    assert not any(key.startswith("count_point") for key in row)


def _geometry_inputs():
    ident = {"source_id": "source-1", "source_sha256": "a" * 64,
             "decision_sha256": "b" * 64, "location_id": "source-1:location:1",
             "geometry_request_sha256": "c" * 64}
    request = {**ident, "precision": "place", "geometry_task": "checked_point_geocode_required",
               "coordinates": None}
    inventory = {"city": "dusseldorf", "inventory_digest": "d" * 64,
                 "all_current_reviews_supported": False, "geometry_requests": [request]}
    index = {"city": "dusseldorf", "index_sha256": "e" * 64, "objects": [{
        "id": "osm/way/1", "roles": ["named_object"], "names": ["Station A"],
        "tags": {"railway": "platform", "public_transport": "platform", "level": "-1"},
        "geometry": mapping(LineString([(1, 1), (2, 1)])),
    }]}
    envelope = {"schema_version": 1, "city": "dusseldorf",
                "inventory_digest": inventory["inventory_digest"],
                "geometry_index_sha256": index["index_sha256"], "decisions": [{
                    **ident, "schema_version": 1, "city": "dusseldorf", "verdict": "resolved",
                    "method": "osm_line", "osm_object_groups": [["osm/way/1"]],
                    "review_note": "Retain the actual source platform edge.",
                    "reviewer": "test", "reviewed_at": "2026-09-30T15:00:00+09:00",
                }]}
    return inventory, index, envelope, box(0, 0, 5, 5)


def test_platform_line_is_visible_without_becoming_a_road_or_count_point():
    inventory, index, envelope, border = _geometry_inputs()
    result = compile_geometry_decisions(inventory=inventory, geometry_index=index,
                                        decision_envelope=envelope, border=border)
    geometry = result["decisions"][0]["derived_geometry"]
    assert geometry["type"] == "LineString"
    assert not any(key.startswith("count_point") for key in geometry)
    inventory["geometry_requests"][0].update(precision="street", geometry_task="checked_road_geometry_required")
    with pytest.raises(ValueError, match="checked road objects"):
        compile_geometry_decisions(inventory=inventory, geometry_index=index,
                                   decision_envelope=envelope, border=border)


@pytest.mark.parametrize("railway", ["subway", "construction"])
def test_named_track_pieces_cannot_claim_a_complete_transit_line(railway):
    inventory, index, envelope, border = _geometry_inputs()
    inventory["geometry_requests"][0].update(
        precision="route", geometry_task="checked_transit_route_geometry_required",
        transit_route={"mode": "subway", "line": "U3", "extent": "full_line"},
    )
    index["objects"][0].update(names=["U3"], tags={"railway": railway})
    envelope["decisions"][0]["method"] = "osm_transit_route"
    with pytest.raises(ValueError, match="checked line objects"):
        compile_geometry_decisions(inventory=inventory, geometry_index=index,
                                   decision_envelope=envelope, border=border)
    incomplete = copy.deepcopy(index)
    incomplete["objects"][0]["roles"].append("transit_route")
    incomplete["objects"][0]["tags"] = {"type": "route", "route": "subway", "ref": "U3"}
    with pytest.raises(ValueError, match="checked line objects"):
        compile_geometry_decisions(inventory=inventory, geometry_index=incomplete,
                                   decision_envelope=envelope, border=border)


@pytest.mark.parametrize("reviewed_mode", ["subway", "tram", "bus", "train"])
def test_native_light_rail_relation_preserves_its_mode_and_requires_compatible_review(reviewed_mode):
    relation = _relation()
    relation["tags"]["route"] = "light_rail"
    ways = _ways()
    for ident in (10, 11):
        ways[ident]["tags"]["railway"] = "light_rail"
    row = route_object(relation, ways, box(0, 0, 5, 5))
    assert row["tags"]["route"] == "light_rail"
    assert row["transit_source_proof"]["member_way_ids"] == [10, 11]
    inventory, index, envelope, border = _geometry_inputs()
    inventory["geometry_requests"][0].update(
        precision="route", geometry_task="checked_transit_route_geometry_required",
        transit_route={"mode": reviewed_mode, "line": "U3", "extent": "full_line"},
    )
    index["objects"] = [row]
    envelope["decisions"][0].update(method="osm_transit_route", osm_object_groups=[[row["id"]]])
    if reviewed_mode in {"subway", "tram"}:
        result = compile_geometry_decisions(inventory=inventory, geometry_index=index,
                                            decision_envelope=envelope, border=border)
        geometry = result["decisions"][0]["derived_geometry"]
        assert shape(geometry["geometry"]).length == 2
        assert not any(key.startswith("count_point") for key in geometry)
    else:
        with pytest.raises(ValueError, match="checked line objects"):
            compile_geometry_decisions(inventory=inventory, geometry_index=index,
                                       decision_envelope=envelope, border=border)


def test_native_light_rail_relation_rejects_inactive_members():
    relation = _relation()
    relation["tags"]["route"] = "light_rail"
    relation["members"].append({"type": "w", "ref": 12, "role": ""})
    with pytest.raises(ValueError, match="inactive"):
        route_object(relation, _ways(), box(0, 0, 5, 5))
