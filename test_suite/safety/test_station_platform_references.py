import copy

import pytest
from shapely.geometry import box

from crimemapsberlin.geometry_decisions import compile_geometry_decisions
from crimemapsberlin.map_decisions import _count_point
from crimemapsberlin.station_platform_references import METHOD, digest, station_platform_reference


def inputs(role="platform"):
    geo = {"type": "Polygon", "coordinates": [[[10, 53], [10.01, 53],
        [10.01, 53.01], [10, 53.01], [10, 53]]]}
    tags = {"area": "yes", "railway": "platform", "public_transport": "platform", "subway": "yes"}
    parent = {"id": 2, "tags": {"name": "Example", "public_transport": "stop_area", "subway": "yes"},
        "members": [{"id": 1, "type": "w", "role": role}]}
    way = {"id": 1, "tags": tags, "geometry": geo, "node_ids": [1, 2, 3, 4, 1]}
    row = {"id": "osm/way/1", "names": ["Example"], "roles": ["named_object"],
        "tags": tags, "geometry": geo, "geometry_sha256": digest(geo),
        "source_url": "https://www.openstreetmap.org/way/1",
        "native_station_platform_source_proof": {"schema_version": 1,
            "source_pbf_sha256": "a" * 64, "reference_only": True,
            "parent_stop_area": parent, "parent_stop_area_sha256": digest(parent),
            "source_way": way, "source_way_sha256": digest(way), "platform_member_role": role}}
    request = {"source_id": "source-1", "source_sha256": "b" * 64,
        "decision_sha256": "c" * 64, "location_id": "source-1:location:1",
        "geometry_request_sha256": "d" * 64, "geometry_task": "checked_point_geocode_required",
        "precision": "place", "city_scope": "in_city", "coordinates": None,
        "transit_review": {"status": "source_backed_context"},
        "poi_review": {"status": "context_only"}, "poi_contexts": [{"kind": "station"}]}
    decision = {"schema_version": 1, "city": "hamburg", "method": METHOD, "verdict": "resolved",
        "osm_object_groups": [["osm/way/1"]], "source_id": request["source_id"],
        "source_sha256": request["source_sha256"], "decision_sha256": request["decision_sha256"],
        "location_id": request["location_id"], "geometry_request_sha256": request["geometry_request_sha256"],
        "review_note": "Native platform is a station context; train and event positions remain unknown.",
        "reviewer": "test", "reviewed_at": "2026-10-02T00:00:00Z"}
    return decision, request, {row["id"]: row}, box(9, 52, 11, 54)


@pytest.mark.parametrize("role", ["platform", ""])
def test_original_station_platform_is_only_context_even_with_empty_native_member_role(role):
    d, r, objects, border = inputs(role)
    result = station_platform_reference(d, r, objects, border, "a" * 64)
    assert result["geometry"] == objects["osm/way/1"]["geometry"]
    assert result["geometry_usage"].endswith("reference_only")
    assert result["actual_event_position_known"] is False
    assert result["actual_static_scene_extent_known"] is False
    assert result["coordinates_generated"] is False
    assert not {"count_point", "representative_point", "coordinates"} & result.keys()
    result["geometry"]["coordinates"][0][0][0] = 99
    assert objects["osm/way/1"]["geometry"]["coordinates"][0][0][0] == 10


def test_full_geometry_compiler_never_creates_a_platform_count_point_with_default_footprint_option():
    d, r, objects, border = inputs()
    inventory = {"city": "hamburg", "inventory_digest": "e" * 64,
        "geometry_requests": [r], "all_current_reviews_supported": True}
    index = {"city": "hamburg", "index_sha256": "f" * 64,
        "source_pbf_sha256": "a" * 64, "objects": list(objects.values())}
    env = {"schema_version": 1, "city": "hamburg", "inventory_digest": "e" * 64,
        "geometry_index_sha256": "f" * 64, "decisions": [d]}
    result = compile_geometry_decisions(inventory=inventory, geometry_index=index,
        decision_envelope=env, border=border)
    row = result["decisions"][0]
    assert row["derived_geometry"]["geometry_usage"].endswith("reference_only")
    assert _count_point(row) is None
    row["derived_geometry"]["count_point"] = {"type": "Point", "coordinates": [10, 53]}
    assert _count_point(row) is None


@pytest.mark.parametrize("change", ["pbf", "member", "name", "hash", "platform", "bus", "source_way", "outside"])
def test_rejects_stale_wrong_or_unbound_platform(change):
    d, r, objects, border = inputs()
    row = objects["osm/way/1"]
    proof = row["native_station_platform_source_proof"]
    if change == "pbf": proof["source_pbf_sha256"] = "0" * 64
    elif change == "member":
        proof["parent_stop_area"]["members"] = []
        proof["parent_stop_area_sha256"] = digest(proof["parent_stop_area"])
    elif change == "name": row["names"] = ["Nearby other station"]
    elif change == "hash": row["geometry_sha256"] = "0" * 64
    elif change == "platform": row["tags"]["railway"] = "station"
    elif change == "bus": row["tags"]["bus"] = "yes"
    elif change == "source_way": proof["source_way_sha256"] = "0" * 64
    else: border = box(0, 0, 1, 1)
    with pytest.raises(ValueError): station_platform_reference(d, r, objects, border, "a" * 64)


@pytest.mark.parametrize("change", [{"precision": "point"}, {"coordinates": [10, 53]},
    {"city_scope": "uncertain"}, {"transit_route": {"mode": "subway", "line": "U1"}},
    {"transit_review": {"status": "reviewed_route"}}, {"poi_contexts": []}])
def test_rejects_promoting_fixed_context_to_a_point_or_actual_transit_route(change):
    d, r, objects, border = inputs()
    r.update(copy.deepcopy(change))
    with pytest.raises(ValueError): station_platform_reference(d, r, objects, border, "a" * 64)
