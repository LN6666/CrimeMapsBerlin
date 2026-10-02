"""Native junction candidates must not become inferred event/count points."""
import copy

import pytest
from shapely.geometry import box

from crimemapsberlin.geometry_decisions import _derived_geometry
from crimemapsberlin.map_decisions import _count_point
from crimemapsberlin.reviewed_city_map import _scene


def fixture(*, two=True):
    objects = {f"osm/way/{ident}": {"id": f"osm/way/{ident}", "roles": ["road", "named_object"],
        "names": [f"Road{ident}"], "tags": {"highway": "primary", "name": f"Road{ident}"},
        "geometry": {"type": "LineString", "coordinates": coords}}
        for ident, coords in ((1, [(0, 0), (1, 0), (2, 0)]), (2, [(1, -1), (1, 0), (1, 1)]))}
    if two:
        objects["osm/way/3"] = {**copy.deepcopy(objects["osm/way/2"]), "id": "osm/way/3",
            "geometry": {"type": "LineString", "coordinates": [(1.0001, -1), (1.0001, 0), (1.0001, 1)]}}
    decision = {"verdict": "resolved", "method": "osm_junction_reference", "review_note": "Reference only.",
        "osm_object_groups": [["osm/way/1"], [k for k in objects if k != "osm/way/1"]]}
    request = {"geometry_task": "checked_point_geocode_required", "precision": "point"}
    return decision, request, objects


def derive(decision, request, objects):
    return _derived_geometry(decision, request, objects, box(-2, -2, 5, 5), "berlin")


@pytest.mark.parametrize("two", [False, True])
def test_reference_retains_all_junction_candidates_without_medoid_event_or_count(two):
    decision, request, objects = fixture(two=two)
    derived = derive(decision, request, objects)
    assert derived["type"] == ("MultiPoint" if two else "Point")
    assert derived["geometry_usage"] == "source_junction_reference_only"
    assert derived["actual_event_position_known"] is False
    assert "count_point" not in derived and "count_point_method" not in derived
    row = {"decision": decision, "derived_geometry": derived}
    assert _count_point(row) is None
    derived["count_point"] = {"type": "Point", "coordinates": (1, 0)}
    assert _count_point(row) is None
    location = {"location_id": "1:location:1", "label": "van search near junction", "role": "search",
        "precision": "point", "city_scope": "in_city", "evidence_quotes": ["near junction"],
        "details": "Actual parking and interior positions unknown.", "poi_contexts": []}
    scene = _scene(location, row, {}, {}, None)
    assert scene["geometry_usage"] == "source_junction_reference_only"
    assert scene["actual_event_position_known"] is False
    assert scene["coordinates"] is None and scene["primary_for_count"] is False
    with pytest.raises(ValueError, match="cannot be a primary"):
        _scene(location, row, {}, {}, location["location_id"])


@pytest.mark.parametrize("change", [
    {"precision": "address"}, {"precision": "route"}, {"precision": "district"},
    {"geometry_task": "checked_area_geometry_required"},
    {"transit_route": {"mode": "tram", "line": "M10"}},
])
def test_junction_reference_rejects_different_source_precision_or_transit(change):
    decision, request, objects = fixture()
    request.update(change)
    with pytest.raises(ValueError):
        derive(decision, request, objects)


def test_ordinary_reviewed_intersection_contract_is_unchanged():
    decision, request, objects = fixture()
    decision["method"] = "osm_intersection"
    derived = derive(decision, request, objects)
    assert derived["type"] == "Point" and "geometry_usage" not in derived
    assert derived["count_point_method"] == "selected_osm_road_groups_intersection_medoid"
    assert _count_point({"decision": decision, "derived_geometry": derived}) is not None


@pytest.mark.parametrize("role", ["background", "arrest", "accident", "operation"])
def test_area_reference_retains_precision_unknown_extent_and_original_vertex(role):
    decision, request, objects = fixture(two=False)
    request.update(geometry_task="checked_area_geometry_required", precision="area", role=role)
    derived = derive(decision, request, objects)
    assert derived["geometry"]["coordinates"] == (1, 0)
    assert derived["actual_event_position_known"] is False
    assert derived["actual_event_extent_known"] is False
    assert "count_point" not in derived and "count_point_method" not in derived
    location = {"location_id": "1:location:1", "label": "junction vicinity", "role": role,
        "precision": "area", "city_scope": "in_city", "evidence_quotes": ["junction vicinity"]}
    row = {"decision": decision, "derived_geometry": derived}
    scene = _scene(location, row, {}, {}, None)
    assert scene["location_precision"] == "area" and scene["coordinates"] is None
    assert scene["actual_event_extent_known"] is False and _count_point(row) is None
    with pytest.raises(ValueError, match="cannot be a primary"):
        _scene(location, row, {}, {}, location["location_id"])


@pytest.mark.parametrize("change", [
    {"geometry_task": "checked_point_geocode_required"}, {"precision": "district"},
    {"transit_route": {"mode": "tram", "line": "12"}}, {"coordinates": [1, 0]},
])
def test_area_reference_rejects_mismatched_task_transit_or_source_point(change):
    decision, request, objects = fixture(two=False)
    request.update(geometry_task="checked_area_geometry_required", precision="area")
    request.update(change)
    with pytest.raises(ValueError):
        derive(decision, request, objects)


def test_area_reference_rejects_planar_crossing_without_original_vertex():
    decision, request, objects = fixture(two=True)
    request.update(geometry_task="checked_area_geometry_required", precision="area")
    objects["osm/way/3"]["tags"]["name"] = objects["osm/way/2"]["tags"]["name"] = "Second"
    objects["osm/way/1"]["tags"]["name"] = "First"
    with pytest.raises(ValueError, match="original shared road vertices"):
        derive(decision, request, objects)


@pytest.mark.parametrize("kind", ["same_name", "unnamed", "three_groups"])
def test_area_reference_rejects_incomplete_or_ambiguous_road_identity(kind):
    decision, request, objects = fixture(two=False)
    request.update(geometry_task="checked_area_geometry_required", precision="area")
    if kind == "same_name":
        objects["osm/way/2"]["tags"]["name"] = objects["osm/way/1"]["tags"]["name"]
    elif kind == "unnamed":
        objects["osm/way/2"]["tags"].pop("name")
    else:
        decision["osm_object_groups"].append(["osm/way/2"])
    with pytest.raises(ValueError):
        derive(decision, request, objects)


def test_ordinary_area_intersection_cannot_become_event_point():
    decision, request, objects = fixture(two=False)
    decision["method"] = "osm_intersection"
    request.update(geometry_task="checked_area_geometry_required", precision="area")
    with pytest.raises(ValueError, match="reviewed precision"):
        derive(decision, request, objects)


def test_area_reference_preserves_every_original_parallel_road_junction():
    decision, request, objects = fixture(two=True)
    request.update(geometry_task="checked_area_geometry_required", precision="area")
    objects["osm/way/1"]["geometry"]["coordinates"].insert(2, (1.0001, 0))
    objects["osm/way/3"]["tags"]["name"] = objects["osm/way/2"]["tags"]["name"]
    derived = derive(decision, request, objects)
    assert derived["type"] == "MultiPoint" and len(derived["geometry"]["coordinates"]) == 2
    assert derived["geometry"] == derived["intersection_candidates"]
    assert derived["actual_event_extent_known"] is False and "count_point_method" not in derived
