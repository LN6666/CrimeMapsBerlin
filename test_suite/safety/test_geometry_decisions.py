import copy

import pytest
from shapely.geometry import LineString, Point, box, mapping

from crimemapsberlin.geometry_decisions import compile_geometry_decisions


def _inputs():
    street_request = {
        "source_id": "source-1",
        "source_url": "https://example.invalid/source-1",
        "source_sha256": "a" * 64,
        "decision_sha256": "b" * 64,
        "location_id": "source-1:location:1",
        "incident_ids": ["source-1:incident:1"],
        "label": "Ratinger Straße",
        "role": "incident",
        "precision": "street",
        "city_scope": "in_city",
        "evidence_quotes": ["Die Tat ereignete sich auf der Ratinger Straße."],
        "coordinates": None,
        "geometry_task": "checked_road_geometry_required",
        "geometry_request_sha256": "c" * 64,
    }
    point_request = {
        **street_request,
        "location_id": "source-1:location:2",
        "label": "Bolker Stern",
        "precision": "place",
        "coordinates": None,
        "geometry_task": "checked_point_geocode_required",
        "geometry_request_sha256": "d" * 64,
    }
    inventory = {
        "city": "dusseldorf",
        "inventory_digest": "e" * 64,
        "all_current_reviews_supported": False,
        "geometry_requests": [street_request, point_request],
    }
    index = {
        "city": "dusseldorf",
        "index_sha256": "f" * 64,
        "objects": [
            {
                "id": "osm/way/1",
                "roles": ["named_object", "road"],
                "geometry": mapping(LineString([(6.76, 51.22), (6.78, 51.24)])),
            },
            {
                "id": "osm/node/2",
                "roles": ["named_object"],
                "geometry": mapping(Point(6.77, 51.23)),
            },
            {
                "id": "osm/way/3",
                "roles": ["named_object", "road"],
                "geometry": mapping(LineString([(6.76, 51.24), (6.78, 51.22)])),
            },
            {
                "id": "osm/way/4",
                "roles": ["address", "named_object"],
                "geometry": mapping(box(6.769, 51.229, 6.771, 51.231)),
            },
        ],
    }
    identity = {
        "schema_version": 1,
        "city": "dusseldorf",
        "source_id": "source-1",
        "source_sha256": "a" * 64,
        "decision_sha256": "b" * 64,
        "review_note": "The reviewed label was compared with the checked OSM object.",
        "reviewer": "test-reviewer",
        "reviewed_at": "2026-09-29T13:00:00+02:00",
    }
    decisions = {
        "schema_version": 1,
        "city": "dusseldorf",
        "inventory_digest": inventory["inventory_digest"],
        "geometry_index_sha256": index["index_sha256"],
        "decisions": [
            {
                **identity,
                "location_id": street_request["location_id"],
                "geometry_request_sha256": street_request["geometry_request_sha256"],
                "verdict": "resolved",
                "method": "osm_line",
                "osm_object_groups": [["osm/way/1"]],
            },
            {
                **identity,
                "location_id": point_request["location_id"],
                "geometry_request_sha256": point_request["geometry_request_sha256"],
                "verdict": "unresolved",
                "method": "none",
                "osm_object_groups": [],
            },
        ],
    }
    return inventory, index, decisions, box(6.70, 51.15, 6.90, 51.35)


def test_geometry_decisions_bind_requests_and_derive_only_selected_osm_geometry():
    inventory, index, decisions, border = _inputs()
    result = compile_geometry_decisions(
        inventory=inventory,
        geometry_index=index,
        decision_envelope=decisions,
        border=border,
    )
    assert result["decision_count"] == 2
    assert result["pending_count"] == 0
    assert result["verdict_counts"] == {"resolved": 1, "unresolved": 1}
    assert result["geometry_review_complete"] is True
    assert result["decisions"][0]["derived_geometry"]["type"] == "LineString"
    assert result["decisions"][1]["derived_geometry"] is None
    assert result["publication_ready"] is False
    assert result["publication_blocks"][0] == "source_review_incomplete"


def test_geometry_decisions_reject_stale_request():
    inventory, index, decisions, border = _inputs()
    stale = copy.deepcopy(decisions)
    stale["decisions"][0]["geometry_request_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="differs from current request"):
        compile_geometry_decisions(
            inventory=inventory,
            geometry_index=index,
            decision_envelope=stale,
            border=border,
        )


def test_geometry_decisions_reject_wrong_geometry_type():
    inventory, index, decisions, border = _inputs()
    wrong = copy.deepcopy(decisions)
    wrong["decisions"][0]["osm_object_groups"] = [["osm/node/2"]]
    with pytest.raises(ValueError, match="checked road objects"):
        compile_geometry_decisions(
            inventory=inventory,
            geometry_index=index,
            decision_envelope=wrong,
            border=border,
        )


def test_geometry_decisions_survive_an_extended_inventory_when_each_request_is_current():
    inventory, index, decisions, border = _inputs()
    decisions["inventory_digest"] = "0" * 64
    result = compile_geometry_decisions(
        inventory=inventory,
        geometry_index=index,
        decision_envelope=decisions,
        border=border,
    )
    assert result["inventory_extended_since_submission"] is True
    assert result["decision_count"] == 2


def test_geometry_decisions_compute_an_intersection_only_after_llm_groups_roads():
    inventory, index, decisions, border = _inputs()
    intersection = copy.deepcopy(decisions)
    intersection["decisions"][1].update(
        verdict="resolved",
        method="osm_intersection",
        osm_object_groups=[["osm/way/1"], ["osm/way/3"]],
    )
    result = compile_geometry_decisions(
        inventory=inventory,
        geometry_index=index,
        decision_envelope=intersection,
        border=border,
    )
    derived = result["decisions"][1]["derived_geometry"]
    assert derived["type"] == "Point"
    assert derived["geometry"]["coordinates"] == pytest.approx((6.77, 51.23))


def test_geometry_decisions_keep_selected_footprint_and_derive_a_named_count_point():
    inventory, index, decisions, border = _inputs()
    footprint = copy.deepcopy(decisions)
    footprint["decisions"][1].update(
        verdict="resolved",
        method="osm_footprint",
        osm_object_groups=[["osm/way/4"]],
    )
    result = compile_geometry_decisions(
        inventory=inventory,
        geometry_index=index,
        decision_envelope=footprint,
        border=border,
    )
    derived = result["decisions"][1]["derived_geometry"]
    assert derived["type"] == "Polygon"
    assert derived["count_point"]["type"] == "Point"
    assert derived["count_point_method"] == "selected_osm_footprint_representative_point"


@pytest.mark.parametrize(
    ("precision", "geometry_task"),
    [
        ("area", "checked_area_geometry_required"),
        ("place", "checked_point_geocode_required"),
    ],
)
def test_geometry_decisions_allow_llm_selected_lines_for_named_linear_areas(
    precision, geometry_task
):
    inventory, index, decisions, border = _inputs()
    request = inventory["geometry_requests"][1]
    request["precision"] = precision
    request["geometry_task"] = geometry_task
    decisions["decisions"][1].update(
        verdict="resolved",
        method="osm_line",
        osm_object_groups=[["osm/way/1"]],
    )
    result = compile_geometry_decisions(
        inventory=inventory,
        geometry_index=index,
        decision_envelope=decisions,
        border=border,
    )
    assert result["decisions"][1]["derived_geometry"]["type"] == "LineString"
