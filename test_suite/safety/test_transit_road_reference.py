import copy

import pytest
from shapely.geometry import box

from crimemapsberlin.geometry_decisions import _derived_geometry


def inputs():
    decision = {"verdict": "resolved", "method": "osm_transit_road_reference",
                "osm_object_groups": [["osm/way/1"]]}
    request = {"geometry_task": "checked_transit_route_geometry_required", "precision": "route",
               "transit_route": {"mode": "bus", "line": "undisclosed", "extent": "source_segment"},
               "transit_review": {"status": "reviewed_route"}}
    objects = {"osm/way/1": {"id": "osm/way/1", "roles": ["road", "named_object"],
                             "names": ["Source road"], "tags": {"highway": "tertiary"},
                             "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 0]]}}}
    return decision, request, objects


@pytest.mark.parametrize("mode", ["bus", "tram"])
def test_explicit_source_road_reference_preserves_native_geometry_without_count_or_line_claim(mode):
    decision, request, objects = inputs()
    request["transit_route"]["mode"] = mode
    result = _derived_geometry(decision, request, objects, box(-1, -1, 2, 2), "berlin")
    assert result["geometry"]["coordinates"] == ((0., 0.), (1., 0.))
    assert result["geometry_usage"] == "source_road_reference_only"
    assert result["complete_transit_line"] is False
    assert "count_point" not in result


def test_unspecified_public_transport_background_keeps_road_not_a_guessed_service():
    decision, request, objects = inputs()
    request["role"] = "background"
    request["transit_route"]["mode"] = "other"
    original = copy.deepcopy(request)
    result = _derived_geometry(decision, request, objects, box(-1, -1, 2, 2), "berlin")
    assert result["geometry_usage"] == "source_road_reference_only"
    assert result["service_identity_known"] is False
    assert result["actual_transit_extent_known"] is False
    assert result["complete_transit_line"] is False
    assert "count_point" not in result
    assert request == original


@pytest.mark.parametrize("role", [None, "incident", "accident", "discovery", "operation"])
def test_unspecified_mode_cannot_locate_a_moving_incident_or_unreviewed_role(role):
    decision, request, objects = inputs()
    request["role"] = role
    request["transit_route"]["mode"] = "other"
    with pytest.raises(ValueError, match="unspecified-mode background"):
        _derived_geometry(decision, request, objects, box(-1, -1, 2, 2), "berlin")


@pytest.mark.parametrize("change", [
    {"transit_route": {"mode": "bus", "extent": "full_line"}},
    {"transit_route": {"mode": "subway", "extent": "source_segment"}},
    {"transit_review": {"status": "reviewed_non_transit_route"}},
    {"transit_review": {"status": "not_applicable"}},
    {"geometry_task": "checked_non_transit_route_geometry_required"},
])
def test_full_line_unknown_and_private_routes_cannot_use_road_reference(change):
    decision, request, objects = inputs()
    request.update(copy.deepcopy(change))
    with pytest.raises(ValueError, match="explicitly reviewed bus/tram source segment"):
        _derived_geometry(decision, request, objects, box(-1, -1, 2, 2), "berlin")


@pytest.mark.parametrize("highway", ["platform", "bus_stop", "construction", "proposed", "footway"])
def test_non_operational_or_non_road_candidates_are_rejected(highway):
    decision, request, objects = inputs()
    objects["osm/way/1"]["tags"]["highway"] = highway
    with pytest.raises(ValueError, match="checked named operational roads"):
        _derived_geometry(decision, request, objects, box(-1, -1, 2, 2), "berlin")


def test_unnamed_or_station_geometry_cannot_be_used_as_source_road_reference():
    decision, request, objects = inputs()
    objects["osm/way/1"]["names"] = []
    with pytest.raises(ValueError, match="checked named operational roads"):
        _derived_geometry(decision, request, objects, box(-1, -1, 2, 2), "berlin")
    objects["osm/way/1"]["names"] = ["Station"]
    objects["osm/way/1"]["geometry"] = {"type": "Point", "coordinates": [0, 0]}
    with pytest.raises(ValueError, match="checked named operational roads"):
        _derived_geometry(decision, request, objects, box(-1, -1, 2, 2), "berlin")
