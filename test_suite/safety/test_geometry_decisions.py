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


@pytest.mark.parametrize("precision", ["street", "area", "route"])
def test_geometry_decisions_keep_only_an_explicitly_bounded_source_road_segment(precision):
    inventory, index, decisions, border = _inputs()
    inventory["geometry_requests"][0].update(
        precision=precision,
        geometry_task={
            "street": "checked_road_geometry_required",
            "area": "checked_area_geometry_required",
            "route": "checked_non_transit_route_geometry_required",
        }[precision],
        transit_review={"status": "reviewed_non_transit_route"} if precision == "route" else None,
    )
    index["objects"][0]["geometry"] = mapping(LineString([
        (6.76, 51.22), (6.77, 51.23), (6.78, 51.24), (6.79, 51.25)
    ]))
    index["objects"] += [
        {"id": "osm/way/5", "roles": ["road"], "tags": {"highway": "residential"},
         "geometry": mapping(LineString([(6.77, 51.22), (6.77, 51.23), (6.77, 51.24)]))},
        {"id": "osm/way/6", "roles": ["road"], "tags": {"highway": "residential"},
         "geometry": mapping(LineString([(6.78, 51.23), (6.78, 51.24), (6.78, 51.25)]))},
    ]
    decisions["decisions"][0].update(
        method="osm_road_segment", osm_object_groups=[["osm/way/1"], ["osm/way/5"], ["osm/way/6"]]
    )
    result = compile_geometry_decisions(
        inventory=inventory, geometry_index=index, decision_envelope=decisions,
        border=border, include_footprint_count_points=False,
    )
    derived = result["decisions"][0]["derived_geometry"]
    assert set(derived["geometry"]["coordinates"]) == {(6.77, 51.23), (6.78, 51.24)}
    assert derived["source_object_groups"] == decisions["decisions"][0]["osm_object_groups"]
    assert "count_point" not in derived
    decisions["decisions"][0]["method"] = "osm_point"
    with pytest.raises(ValueError, match="differs from the reviewed precision"):
        compile_geometry_decisions(
            inventory=inventory, geometry_index=index, decision_envelope=decisions, border=border,
        )


@pytest.mark.parametrize("request_update", [
    {"transit_review": {"status": "reviewed_unknown_route"}},
    {"transit_review": {"status": "reviewed_route"}},
    {"transit_review": {"status": "not_applicable"}},
    {"transit_review": {}},
    {"transit_review": None},
    {"transit_route": {"mode": "bus", "line": "67"}},
    {"geometry_task": "checked_transit_route_geometry_required"},
])
def test_bounded_road_segment_does_not_reclassify_transit_or_unreviewed_routes(request_update):
    inventory, index, decisions, border = _inputs()
    inventory["geometry_requests"][0].update(
        precision="route", geometry_task="checked_non_transit_route_geometry_required",
        transit_review={"status": "reviewed_non_transit_route"},
    )
    inventory["geometry_requests"][0].update(request_update)
    decisions["decisions"][0]["method"] = "osm_road_segment"
    with pytest.raises(ValueError, match="reviewed road/area or non-transit route"):
        compile_geometry_decisions(
            inventory=inventory, geometry_index=index, decision_envelope=decisions, border=border,
        )


def test_bounded_parallel_carriageways_may_share_endpoint_roads_but_not_path_objects():
    inventory, index, decisions, border = _inputs()
    index["objects"][0]["geometry"] = mapping(LineString([
        (6.76, 51.22), (6.77, 51.23), (6.78, 51.24), (6.79, 51.25)
    ]))
    index["objects"] += [
        {"id": "osm/way/5", "roles": ["road"], "tags": {"highway": "residential"},
         "geometry": mapping(LineString([
             (6.77, 51.22), (6.77, 51.23), (6.77, 51.2301), (6.77, 51.24)
         ]))},
        {"id": "osm/way/6", "roles": ["road"], "tags": {"highway": "residential"},
         "geometry": mapping(LineString([
             (6.78, 51.23), (6.78, 51.24), (6.78, 51.2401), (6.78, 51.25)
         ]))},
        {"id": "osm/way/7", "roles": ["road"], "tags": {"highway": "residential"},
         "geometry": mapping(LineString([
             (6.76, 51.2201), (6.77, 51.2301), (6.78, 51.2401), (6.79, 51.2501)
         ]))},
    ]
    selected = decisions["decisions"][0]
    selected.update(method="osm_road_segment", osm_object_groups=[
        ["osm/way/1"], ["osm/way/5"], ["osm/way/6"],
        ["osm/way/7"], ["osm/way/5"], ["osm/way/6"],
    ])
    result = compile_geometry_decisions(
        inventory=inventory, geometry_index=index, decision_envelope=decisions,
        border=border, include_footprint_count_points=False,
    )
    derived = result["decisions"][0]["derived_geometry"]
    assert derived["type"] == "MultiLineString"
    assert set(derived["source_object_ids"]) == {"osm/way/1", "osm/way/5", "osm/way/6", "osm/way/7"}
    assert len(derived["source_object_ids"]) == 4
    assert derived["source_object_groups"] == selected["osm_object_groups"]
    assert "count_point" not in derived
    for invalid in (
        [*selected["osm_object_groups"][:3], ["osm/way/1"], ["osm/way/5"], ["osm/way/6"]],
        [["osm/way/1"], ["osm/way/5", "osm/way/5"], ["osm/way/6"]],
    ):
        selected["osm_object_groups"] = invalid
        with pytest.raises(ValueError, match="duplicate object IDs"):
            compile_geometry_decisions(
                inventory=inventory, geometry_index=index, decision_envelope=decisions, border=border,
            )
    selected.update(method="osm_intersection", osm_object_groups=[["osm/way/1"], ["osm/way/1"]])
    with pytest.raises(ValueError, match="duplicate object IDs"):
        compile_geometry_decisions(
            inventory=inventory, geometry_index=index, decision_envelope=decisions, border=border,
        )


@pytest.mark.parametrize("invalid", [None, "repeat_path", "own_endpoint", "projected_endpoint"])
def test_adjacent_bounded_road_pieces_may_reference_each_others_native_endpoints(invalid):
    inventory, index, decisions, border = _inputs()
    paths = {
        1: [(6.76, 51.23), (6.77, 51.23)],
        5: [(6.77, 51.23), (6.78, 51.231), (6.79, 51.23)],
        6: [(6.77, 51.23), (6.78, 51.229), (6.79, 51.23)],
        7: [(6.79, 51.23), (6.80, 51.23)],
        8: [(6.76, 51.22), (6.76, 51.23), (6.76, 51.24)],
        9: [(6.80, 51.22), (6.80, 51.23), (6.80, 51.24)],
    }
    index["objects"] = [
        {"id": f"osm/way/{ident}", "roles": ["road"],
         "tags": {"highway": "primary"}, "geometry": mapping(LineString(points))}
        for ident, points in paths.items()
    ]
    groups = [
        ["osm/way/1"], ["osm/way/8"], ["osm/way/5", "osm/way/6"],
        ["osm/way/5"], ["osm/way/1"], ["osm/way/7"],
        ["osm/way/6"], ["osm/way/1"], ["osm/way/7"],
        ["osm/way/7"], ["osm/way/5", "osm/way/6"], ["osm/way/9"],
    ]
    if invalid == "repeat_path":
        groups[6] = ["osm/way/5"]
    elif invalid == "own_endpoint":
        groups[1] = ["osm/way/1"]
    elif invalid == "projected_endpoint":
        index["objects"][-2]["geometry"] = mapping(LineString([
            (6.76, 51.22), (6.76, 51.24)
        ]))
    decisions["decisions"][0].update(method="osm_road_segment", osm_object_groups=groups)
    if invalid:
        expected = {"repeat_path": "duplicate object IDs", "own_endpoint": "unique junction",
                    "projected_endpoint": "shared native"}[invalid]
        with pytest.raises(ValueError, match=expected):
            compile_geometry_decisions(
                inventory=inventory, geometry_index=index, decision_envelope=decisions,
                border=border, include_footprint_count_points=False,
            )
    else:
        result = compile_geometry_decisions(
            inventory=inventory, geometry_index=index, decision_envelope=decisions,
            border=border, include_footprint_count_points=False,
        )
        derived = result["decisions"][0]["derived_geometry"]
        assert derived["source_object_groups"] == groups
        assert len(derived["source_object_ids"]) == 6
        assert "count_point" not in derived
        from shapely.geometry import shape
        from shapely.ops import unary_union
        assert shape(derived["geometry"]).equals(unary_union([
            LineString(paths[i]) for i in [1, 5, 6, 7]
        ]))


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


def test_geometry_decisions_can_keep_footprints_without_generating_representatives(monkeypatch):
    from shapely.geometry.base import BaseGeometry

    from crimemapsberlin.map_decisions import _validate_inputs

    inventory, index, decisions, border = _inputs()
    inventory.update(schema_version=1, all_current_reviews_supported=True)
    decisions["decisions"][1].update(
        verdict="resolved", method="osm_footprint",
        osm_object_groups=[["osm/way/4"]],
    )
    default = compile_geometry_decisions(
        inventory=inventory, geometry_index=index,
        decision_envelope=decisions, border=border,
    )
    explicit_default = compile_geometry_decisions(
        inventory=inventory, geometry_index=index,
        decision_envelope=decisions, border=border,
        include_footprint_count_points=True,
    )
    assert default == explicit_default

    def forbidden_representative(*args, **kwargs):
        pytest.fail("Strict review must not even compute a representative point")

    monkeypatch.setattr(BaseGeometry, "representative_point", forbidden_representative)
    strict = compile_geometry_decisions(
        inventory=inventory, geometry_index=index,
        decision_envelope=decisions, border=border,
        include_footprint_count_points=False,
    )
    derived = strict["decisions"][1]["derived_geometry"]
    previous = default["decisions"][1]["derived_geometry"]
    assert derived["geometry"] == previous["geometry"]
    assert derived["geometry_sha256"] == previous["geometry_sha256"]
    assert derived["source_object_ids"] == previous["source_object_ids"]
    assert not any(key.startswith("count_point") for key in derived)
    assert strict["ledger_sha256"] != default["ledger_sha256"]
    assert strict["footprint_representative_points_enabled"] is False
    assert strict["geometry_review_complete"] is True
    assert strict["publication_ready"] is False
    _validate_inputs(inventory, strict, "dusseldorf")


@pytest.mark.parametrize("method", ["osm_point", "osm_intersection"])
def test_no_representative_points_keeps_original_points_and_real_intersections(method):
    inventory, index, decisions, border = _inputs()
    decisions["decisions"][1].update(
        verdict="resolved", method=method,
        osm_object_groups=[["osm/node/2"]] if method == "osm_point"
        else [["osm/way/1"], ["osm/way/3"]],
    )
    default = compile_geometry_decisions(
        inventory=inventory, geometry_index=index,
        decision_envelope=decisions, border=border,
    )
    strict = compile_geometry_decisions(
        inventory=inventory, geometry_index=index,
        decision_envelope=decisions, border=border,
        include_footprint_count_points=False,
    )
    assert strict["decisions"] == default["decisions"]
    assert strict["ledger_sha256"] == default["ledger_sha256"]
    assert strict["decisions"][1]["derived_geometry"]["type"] == "Point"


def test_geometry_decisions_require_boolean_footprint_point_policy():
    inventory, index, decisions, border = _inputs()
    with pytest.raises(TypeError, match="must be a boolean"):
        compile_geometry_decisions(
            inventory=inventory, geometry_index=index,
            decision_envelope=decisions, border=border,
            include_footprint_count_points=None,
        )


@pytest.mark.parametrize(
    ("precision", "geometry_task"),
    [
        ("area", "checked_area_geometry_required"),
        ("place", "checked_point_geocode_required"),
        ("point", "checked_point_geocode_required"),
    ],
)
def test_geometry_decisions_allow_llm_selected_lines_for_disclosed_named_roads(
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


def test_geometry_decisions_do_not_replace_a_reviewed_address_with_a_whole_road():
    inventory, index, decisions, border = _inputs()
    request = inventory["geometry_requests"][1]
    request["precision"] = "address"
    decisions["decisions"][1].update(
        verdict="resolved",
        method="osm_line",
        osm_object_groups=[["osm/way/1"]],
    )
    with pytest.raises(ValueError, match="differs from the reviewed precision"):
        compile_geometry_decisions(
            inventory=inventory,
            geometry_index=index,
            decision_envelope=decisions,
            border=border,
        )


def test_geometry_decisions_keep_reviewed_non_transit_routes_as_selected_road_ranges():
    inventory, index, decisions, border = _inputs()
    request = inventory["geometry_requests"][1]
    request.update(
        precision="route", geometry_task="checked_non_transit_route_geometry_required",
        transit_review={"status": "reviewed_non_transit_route"},
    )
    decisions["decisions"][1].update(
        verdict="resolved", method="osm_non_transit_route",
        osm_object_groups=[["osm/way/1", "osm/way/3"]],
    )
    result = compile_geometry_decisions(
        inventory=inventory, geometry_index=index, decision_envelope=decisions, border=border,
    )
    derived = result["decisions"][1]["derived_geometry"]
    assert derived["type"] == "MultiLineString"
    assert derived["source_object_ids"] == ["osm/way/1", "osm/way/3"]
    assert "count_point" not in derived


@pytest.mark.parametrize("status", ["reviewed_unknown_route", "reviewed_route", "not_applicable"])
def test_geometry_decisions_do_not_disguise_public_or_unknown_transit_as_a_road_route(status):
    inventory, index, decisions, border = _inputs()
    inventory["geometry_requests"][1].update(
        precision="route", geometry_task="checked_non_transit_route_geometry_required",
        transit_review={"status": status},
    )
    decisions["decisions"][1].update(
        verdict="resolved", method="osm_non_transit_route", osm_object_groups=[["osm/way/1"]],
    )
    with pytest.raises(ValueError, match="explicitly reviewed non-transit route"):
        compile_geometry_decisions(
            inventory=inventory, geometry_index=index, decision_envelope=decisions, border=border,
        )


@pytest.mark.parametrize("tags", [{"railway": "subway"}, {"highway": "platform"}, {"highway": "construction"}])
def test_geometry_decisions_reject_rail_and_platform_objects_for_non_transit_routes(tags):
    inventory, index, decisions, border = _inputs()
    inventory["geometry_requests"][1].update(
        precision="route", geometry_task="checked_non_transit_route_geometry_required",
        transit_review={"status": "reviewed_non_transit_route"},
    )
    index["objects"][2].update(tags=tags)
    if "railway" in tags:
        index["objects"][2]["roles"] = ["named_object"]
    decisions["decisions"][1].update(
        verdict="resolved", method="osm_non_transit_route", osm_object_groups=[["osm/way/3"]],
    )
    with pytest.raises(ValueError, match="operational road objects"):
        compile_geometry_decisions(
            inventory=inventory, geometry_index=index, decision_envelope=decisions, border=border,
        )


def test_geometry_decisions_require_every_source_relation_for_full_transit_line():
    inventory, index, decisions, border = _inputs()
    request = inventory["geometry_requests"][1]
    request.update(
        precision="route",
        geometry_task="checked_transit_route_geometry_required",
        transit_route={
            "mode": "subway", "line": "U8", "extent": "full_line",
            "evidence_quote": "The incident occurred inside a train on line U8.",
        },
    )
    index["objects"][0].update(names=["U8"], tags={"railway": "subway"})
    index["objects"].append({
        "id": "osm/relation/5", "roles": ["named_object", "transit_route"], "names": ["U8"],
        "tags": {"type": "route", "route": "subway", "ref": "U8"},
        "transit_source_proof": {
            "schema_version": 1, "complete": True, "relation_id": 5,
            "member_way_ids": [10], "member_way_count": 1,
            "member_sequence": [10], "member_source_digest": "a" * 64,
        },
        "geometry": mapping(LineString([(6.78, 51.24), (6.79, 51.25)])),
    })
    index["objects"].append({
        "id": "osm/relation/6", "roles": ["named_object", "transit_route"], "names": ["U8"],
        "tags": {"type": "route", "route": "subway", "ref": "U8"},
        "transit_source_proof": {
            "schema_version": 1, "complete": True, "relation_id": 6,
            "member_way_ids": [11], "member_way_count": 1,
            "member_sequence": [11], "member_source_digest": "b" * 64,
        },
        "geometry": mapping(LineString([(6.76, 51.22), (6.78, 51.24)])),
    })
    decisions["decisions"][1].update(
        verdict="resolved",
        method="osm_transit_route",
        osm_object_groups=[["osm/relation/5", "osm/relation/6"]],
    )
    result = compile_geometry_decisions(
        inventory=inventory,
        geometry_index=index,
        decision_envelope=decisions,
        border=border,
    )
    assert result["decisions"][1]["derived_geometry"]["type"] == "MultiLineString"
    incomplete = copy.deepcopy(decisions)
    incomplete["decisions"][1]["osm_object_groups"] = [["osm/relation/5"]]
    with pytest.raises(ValueError, match="every complete source route relation"):
        compile_geometry_decisions(
            inventory=inventory,
            geometry_index=index,
            decision_envelope=incomplete,
            border=border,
        )
