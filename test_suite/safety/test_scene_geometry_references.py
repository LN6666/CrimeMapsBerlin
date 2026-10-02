"""Display references must not acquire exact-event or count-point meaning."""
import copy

import pytest
from shapely.geometry import box

from crimemapsberlin.geometry_decisions import _derived_geometry
from crimemapsberlin.map_decisions import _count_point
from crimemapsberlin.reviewed_city_map import _scene


def derive(method, groups, objects, *, line="M1", mode="tram", precision="route", extent="source_segment"):
    request = {
        "geometry_task": "checked_transit_route_geometry_required" if precision == "route" else "checked_road_geometry_required",
        "precision": precision,
        "transit_route": {"mode": mode, "line": line, "extent": extent},
        "transit_review": {"status": "reviewed_route"},
    }
    return _derived_geometry({"verdict": "resolved", "method": method,
                              "osm_object_groups": groups}, request, objects,
                             box(-2, -2, 5, 5), "berlin")


def native_relation(ident, line="M1", mode="tram"):
    return {"id": f"osm/relation/{ident}", "names": [line],
            "roles": ["named_object", "transit_route"],
            "tags": {"type": "route", "route": mode, "ref": line},
            "geometry": {"type": "LineString", "coordinates": [(0, 0), (3, 0)]},
            "transit_source_proof": {"schema_version": 1, "relation_id": ident,
                "complete": True, "member_way_ids": [1], "member_way_count": 1,
                "member_sequence": [1], "member_source_digest": "a" * 64}}


@pytest.mark.parametrize("extent", ["source_segment", "full_line"])
def test_carrier_reference_requires_all_directions_and_keeps_event_extent_unknown(extent):
    objects = {r["id"]: r for r in [native_relation(99), native_relation(100)]}
    result = derive("osm_transit_line_reference", [list(objects)], objects, extent=extent)
    assert result["geometry_usage"] == "carrier_line_reference_only"
    assert result["complete_transit_line"] is False
    assert result["actual_transit_extent_known"] is False
    assert "count_point" not in result
    with pytest.raises(ValueError, match="every complete"):
        derive("osm_transit_line_reference", [["osm/relation/99"]], objects, extent=extent)


@pytest.mark.parametrize("extent", [None, "unknown", "actual_trip"])
def test_carrier_reference_rejects_undeclared_transit_extent(extent):
    row = native_relation(99)
    with pytest.raises(ValueError, match="explicitly reviewed transit extent"):
        derive("osm_transit_line_reference", [[row["id"]]], {row["id"]: row}, extent=extent)


def test_combined_carriers_are_explicit_not_inferred_from_an_accident_location():
    objects = {r["id"]: r for r in [native_relation(99, "U1", "subway"),
                                   native_relation(100, "U3", "subway")]}
    result = derive("osm_transit_line_reference", [["osm/relation/99"], ["osm/relation/100"]],
                    objects, line="U1 and U3", mode="subway")
    assert result["actual_transit_extent_known"] is False
    with pytest.raises(ValueError, match="line declaration"):
        derive("osm_transit_line_reference", [["osm/relation/99"], ["osm/relation/100"]],
               objects, line="unidentified U-Bahn line", mode="subway")


@pytest.mark.parametrize("change", ["incomplete", "wrong_member_proof", "missing_name", "inactive", "unsupported_mode"])
def test_carrier_rejects_unproved_or_incompatible_native_relations(change):
    row = native_relation(99)
    mode = "tram"
    if change == "incomplete":
        row["transit_source_proof"]["complete"] = False
    elif change == "wrong_member_proof":
        row["transit_source_proof"]["member_way_count"] = 2
    elif change == "missing_name":
        row["names"] = []
    elif change == "inactive":
        row["tags"]["route"] = "disused"
    else:
        mode = "disused"
        row["tags"]["route"] = mode
    with pytest.raises(ValueError):
        derive("osm_transit_line_reference", [[row["id"]]], {row["id"]: row}, mode=mode)


def road(ident, coordinates):
    return {"id": f"osm/way/{ident}", "roles": ["road", "named_object"],
            "names": [f"Road {ident}"], "tags": {"highway": "primary"},
            "geometry": {"type": "LineString", "coordinates": coordinates}}


def test_bounded_road_reference_keeps_native_vertices_and_shared_endpoints():
    objects = {r["id"]: r for r in [road(1, [(-1, 0), (0, 0), (1, 0), (2, 0), (3, 0)]),
        road(2, [(-1, .1), (0, .1), (1, .1), (2, .1), (3, .1)]),
        road(3, [(0, -1), (0, 0), (0, .1), (0, 1)]),
        road(4, [(2, -1), (2, 0), (2, .1), (2, 1)])]}
    groups = [["osm/way/1"], ["osm/way/3"], ["osm/way/4"],
              ["osm/way/2"], ["osm/way/3"], ["osm/way/4"]]
    result = derive("osm_transit_road_reference_segment", groups, objects, mode="bus")
    assert result["geometry"]["coordinates"] == (((0., 0.), (1., 0.), (2., 0.)),
                                                   ((0., .1), (1., .1), (2., .1)))
    assert result["geometry_usage"] == "source_road_reference_only"
    assert result["source_road_extent"] == "native_endpoint_bounded"
    assert result["complete_transit_line"] is False
    assert "count_point" not in result
    projected = copy.deepcopy(objects)
    projected["osm/way/4"]["geometry"]["coordinates"] = [(1.5, -1), (1.5, 1)]
    with pytest.raises(ValueError, match="shared native source vertices"):
        derive("osm_transit_road_reference_segment", groups, projected, mode="bus")
    with pytest.raises(ValueError, match="bus/tram"):
        derive("osm_transit_road_reference_segment", groups, objects, mode="subway")


def test_unknown_mode_traffic_background_preserves_native_bounded_road_only():
    objects = {r["id"]: r for r in [
        road(1, [(-1, 0), (0, 0), (1, 0), (2, 0), (3, 0)]),
        road(2, [(0, -1), (0, 0), (0, 1)]),
        road(3, [(2, -1), (2, 0), (2, 1)]),
    ]}
    request = {"geometry_task": "checked_transit_route_geometry_required", "precision": "route",
               "role": "background", "transit_review": {"status": "reviewed_route"},
               "transit_route": {"mode": "other", "line": "unidentified affected service", "extent": "source_segment"}}
    decision = {"verdict": "resolved", "method": "osm_transit_road_reference_segment",
                "osm_object_groups": [["osm/way/1"], ["osm/way/2"], ["osm/way/3"]]}
    original = copy.deepcopy(request)
    result = _derived_geometry(decision, request, objects, box(-2, -2, 5, 5), "berlin")
    assert result["geometry"]["coordinates"] == ((0., 0.), (1., 0.), (2., 0.))
    assert result["source_road_extent"] == "native_endpoint_bounded"
    assert result["actual_transit_extent_known"] is False
    assert result["service_identity_known"] is False
    assert "count_point" not in result
    assert request == original
    for change in ({"transit_route": {"mode": "other", "extent": "full_line"}},
                   {"transit_review": {"status": "unresolved"}}, {"role": "incident"}):
        changed = copy.deepcopy(request)
        changed.update(change)
        with pytest.raises(ValueError):
            _derived_geometry(decision, changed, objects, box(-2, -2, 5, 5), "berlin")
    projected = copy.deepcopy(objects)
    projected["osm/way/3"]["geometry"]["coordinates"] = [(1.5, -1), (1.5, 1)]
    with pytest.raises(ValueError, match="shared native source vertices"):
        _derived_geometry(decision, request, projected, box(-2, -2, 5, 5), "berlin")


def test_named_bridge_footprint_is_not_a_synthetic_count_point():
    row = {"id": "osm/way/1", "names": ["Bridge"], "roles": ["named_object"],
           "tags": {"man_made": "bridge"},
           "geometry": {"type": "Polygon", "coordinates": [[(0, 0), (1, 0), (1, 1), (0, 0)]]}}
    result = derive("osm_named_footprint_reference", [[row["id"]]], {row["id"]: row}, precision="street")
    assert result["geometry_usage"] == "source_footprint_reference_only"
    assert result["geometry"]["type"] == "Polygon"
    assert "count_point" not in result
    row["roles"].append("administrative_boundary")
    with pytest.raises(ValueError, match="non-administrative polygons"):
        derive("osm_named_footprint_reference", [[row["id"]]], {row["id"]: row}, precision="street")


def place_footprint(row, *, change=None):
    request = {"geometry_task": "checked_point_geocode_required", "precision": "place",
               "role": "incident", "transit_route": None}
    if change:
        request.update(change)
    return _derived_geometry({"verdict": "resolved", "method": "osm_place_footprint_reference",
        "osm_object_groups": [[row["id"]]]}, request, {row["id"]: row},
        box(-2, -2, 5, 5), "berlin", include_footprint_count_points=True)


@pytest.mark.parametrize("change", [None,
    {"geometry_task": "checked_area_geometry_required", "precision": "area"}])
def test_nearby_place_reference_never_becomes_an_inside_venue_count(change):
    row = lake()
    result = place_footprint(row, change=change)
    assert result["geometry_usage"] == "source_footprint_reference_only"
    assert result["geometry"]["type"] == "Polygon"
    assert "count_point" not in result
    assert "complete_transit_line" not in result


@pytest.mark.parametrize("change", [{"precision": "address"}, {"precision": "point"},
    {"geometry_task": "checked_district_geometry_required", "precision": "district"},
    {"geometry_task": "checked_non_transit_route_geometry_required", "precision": "route"},
    {"transit_route": {"mode": "bus", "line": "M29", "extent": "source_segment"}}])
def test_place_reference_rejects_different_precision_or_public_transit(change):
    with pytest.raises(ValueError, match="reviewed non-transit place/area"):
        place_footprint(lake(), change=change)


@pytest.mark.parametrize("change", ["district", "unnamed", "point", "line"])
def test_place_reference_rejects_administrative_unnamed_or_wrong_geometry(change):
    row = lake()
    if change == "district":
        row["roles"].append("administrative_boundary")
    elif change == "unnamed":
        row["names"] = []
    elif change == "point":
        row["geometry"] = {"type": "Point", "coordinates": (0, 0)}
    else:
        row["geometry"] = {"type": "LineString", "coordinates": [(0, 0), (1, 1)]}
    with pytest.raises(ValueError, match="named non-administrative polygons"):
        place_footprint(row)


def test_place_reference_survives_map_export_without_becoming_a_venue_count():
    location = {"location_id": "1:location:1", "label": "encounter in front of a venue",
        "role": "incident", "precision": "place", "city_scope": "in_city",
        "evidence_quotes": ["in front of the venue"], "details": "Outside; precise encounter position unknown.",
        "poi_contexts": []}
    row = {"decision": {"verdict": "resolved", "method": "osm_place_footprint_reference",
                       "review_note": "Venue footprint is a reference, not an inside offence."},
           "derived_geometry": place_footprint(lake())}
    scene = _scene(location, row, {}, {}, None)
    assert scene["geometry_usage"] == "source_footprint_reference_only"
    assert scene["coordinates"] is None and scene["primary_for_count"] is False
    assert scene["details"] == location["details"] and scene["poi_contexts"] == []
    assert _count_point(row) is None


def non_transit_footprint(row, *, change=None):
    request = {"geometry_task": "checked_non_transit_route_geometry_required", "precision": "route",
               "transit_review": {"status": "reviewed_non_transit_route"}, "transit_route": None}
    if change:
        request.update(change)
    return _derived_geometry({"verdict": "resolved", "method": "osm_non_transit_footprint_reference",
        "osm_object_groups": [[row["id"]]]}, request, {row["id"]: row},
        box(-2, -2, 5, 5), "berlin", include_footprint_count_points=True)


def lake():
    return {"id": "osm/way/1", "names": ["Lake"], "roles": ["named_object"],
            "tags": {"natural": "water"},
            "geometry": {"type": "Polygon", "coordinates": [[(0, 0), (1, 0), (1, 1), (0, 0)]]}}


def test_non_transit_lake_reference_preserves_area_not_actual_path_or_count():
    row = lake()
    result = non_transit_footprint(row)
    assert result["geometry_usage"] == "source_footprint_reference_only"
    assert result["actual_non_transit_extent_known"] is False
    assert result["geometry"]["type"] == "Polygon"
    assert result["geometry"]["coordinates"] == (((0., 0.), (1., 0.), (1., 1.), (0., 0.)),)
    assert "count_point" not in result
    assert "complete_transit_line" not in result


@pytest.mark.parametrize("change", [
    {"precision": "area"}, {"geometry_task": "checked_transit_route_geometry_required"},
    {"transit_review": {"status": "unknown"}},
    {"transit_route": {"mode": "ferry", "line": "F1", "extent": "source_segment"}},
])
def test_non_transit_footprint_rejects_unreviewed_or_public_transit_paths(change):
    with pytest.raises(ValueError, match="explicitly reviewed non-transit"):
        non_transit_footprint(lake(), change=change)


@pytest.mark.parametrize("change", ["district", "unnamed", "point", "line"])
def test_non_transit_footprint_rejects_district_unnamed_or_wrong_dimension(change):
    row = lake()
    if change == "district":
        row["roles"].append("administrative_boundary")
    elif change == "unnamed":
        row["names"] = []
    elif change == "point":
        row["geometry"] = {"type": "Point", "coordinates": (0, 0)}
    else:
        row["geometry"] = {"type": "LineString", "coordinates": [(0, 0), (1, 1)]}
    with pytest.raises(ValueError, match="named non-administrative polygons"):
        non_transit_footprint(row)
