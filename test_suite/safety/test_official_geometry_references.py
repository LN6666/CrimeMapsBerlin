"""Independent official polygons retain provenance, holes and no event points."""
import copy

import pytest
from shapely.geometry import Point, Polygon, box, mapping, shape
from shapely.ops import transform

from crimemapsberlin.geometry_decisions import compile_geometry_decisions
from crimemapsberlin.map_decisions import _count_point, _validate_inputs
from crimemapsberlin.official_geometry_references import (
    INDEX_KEYS, METHOD, SOURCE_URL, _digest, validate_official_reference_index,
)
from crimemapsberlin.reviewed_city_map import _scene
from crimemapsberlin.spatial import metric_transforms


def inputs():
    metric, wgs84 = metric_transforms("EPSG:25832")
    border = transform(wgs84, box(475000, 5560000, 475100, 5560100))
    native = Polygon([(475010, 5560010), (475050, 5560010), (475050, 5560050),
                      (475010, 5560050), (475010, 5560010)],
                     [[(475020, 5560020), (475020, 5560030), (475030, 5560030),
                       (475030, 5560020), (475020, 5560020)]])
    feature = {"type": "Feature", "properties": {
        "GmlID": "Stadtbezirke.120", "STBZ_ID": 651, "STBZ_NAME": "Riedberg"},
        "geometry": mapping(native)}
    fc = {"type": "FeatureCollection", "crs": {
        "type": "name", "properties": {"name": "EPSG:25832"}}, "features": [feature]}
    request = {"source_id": "S", "source_sha256": "a" * 64,
        "decision_sha256": "b" * 64, "location_id": "S:location:1",
        "geometry_request_sha256": "c" * 64, "label": "Riedberg",
        "role": "background", "precision": "district", "city_scope": "in_city",
        "geometry_task": "checked_district_geometry_required", "coordinates": None,
        "evidence_quotes": ["left Riedberg in an unknown direction"]}
    ref = {"id": "official/frankfurt/Stadtbezirke.120", "feature_id": "Stadtbezirke.120",
        "feature_sha256": _digest(feature),
        "reviewed_location_bindings": [{key: request[key] for key in (
            "location_id", "source_sha256", "geometry_request_sha256")}],
        "municipal_boundary_sha256": _digest(mapping(border)),
        "reviewed_outside_area_m2": 0, "reviewed_max_outside_vertex_distance_m": 0}
    index = {"schema_version": 1, "city": "frankfurt", "source_url": SOURCE_URL,
        "source_crs": "EPSG:25832", "acquired_at": "2026-10-02T05:48:58+09:00",
        "response_sha256_observed": "d" * 64, "original_feature_collection": fc,
        "original_feature_collection_sha256": _digest(fc), "references": [ref]}
    rehash(index)
    inventory = {"schema_version": 1, "city": "frankfurt", "inventory_digest": "e" * 64,
        "all_current_reviews_supported": True, "geometry_requests": [request]}
    osm = {"city": "frankfurt", "index_sha256": "f" * 64, "objects": []}
    decision = {key: request[key] for key in (
        "source_id", "source_sha256", "decision_sha256", "location_id", "geometry_request_sha256")}
    decision.update(schema_version=1, city="frankfurt", verdict="resolved", method=METHOD,
        osm_object_groups=[], official_reference_id=ref["id"], review_note="Official background footprint only",
        reviewer="test reviewer", reviewed_at="2026-10-02T12:00:00+09:00")
    envelope = {"schema_version": 1, "city": "frankfurt", "inventory_digest": inventory["inventory_digest"],
        "geometry_index_sha256": osm["index_sha256"], "official_reference_index_sha256": index["index_sha256"],
        "decisions": [decision]}
    return inventory, osm, envelope, index, border


def rehash(index):
    index["index_sha256"] = _digest({key: index[key] for key in INDEX_KEYS})


def compile_inputs(values):
    inv, osm, envelope, official, border = values
    return compile_geometry_decisions(inventory=inv, geometry_index=osm,
        decision_envelope=envelope, border=border, official_reference_index=official,
        include_footprint_count_points=False)


def test_original_vertices_holes_and_independent_provenance_survive_without_count():
    values = inputs(); inv, osm, env, index, border = values
    result = compile_inputs(values); row = result["decisions"][0]; derived = row["derived_geometry"]
    _, wgs84 = metric_transforms("EPSG:25832")
    expected = mapping(transform(wgs84, shape(index["original_feature_collection"]["features"][0]["geometry"])))
    assert derived["geometry"] == expected
    assert len(derived["geometry"]["coordinates"]) == 2
    assert derived["source_object_ids"] == [] and "count_point" not in derived
    assert derived["actual_event_position_known"] is False and derived["actual_event_extent_known"] is False
    assert derived["source_reference_provenance"][0]["source_url"] == SOURCE_URL
    assert derived["source_reference_provenance"][0]["original_footprint_clipped"] is False
    assert result["official_reference_index_sha256"] == index["index_sha256"]
    _validate_inputs(inv, result, "frankfurt")
    scene = _scene(row["request"], row, {}, {}, None)
    assert scene["coordinates"] is None and scene["primary_for_count"] is False
    assert scene["location_object_ids"] == [] and scene["source_reference_ids"] == derived["source_reference_ids"]
    derived["count_point"] = {"type": "Point", "coordinates": [8.6, 50.1]}
    assert _count_point(row) is None
    with pytest.raises(ValueError, match="cannot be a primary"):
        _scene(row["request"], row, {}, {}, row["request"]["location_id"])


@pytest.mark.parametrize("change", ["index_digest", "source", "crs", "fc_crs", "fc_digest",
    "feature_digest", "boundary", "outside_proof", "distance_proof", "duplicate_ref",
    "duplicate_feature", "binding_source", "binding_request", "envelope_digest"])
def test_stale_source_geometry_and_location_bindings_are_rejected(change):
    values = inputs(); inv, osm, env, index, border = values; ref = index["references"][0]
    if change == "source": index["source_url"] = "https://example.invalid/WFS"
    elif change == "crs": index["source_crs"] = "EPSG:4326"
    elif change == "fc_crs": index["original_feature_collection"]["crs"]["properties"]["name"] = "EPSG:4326"
    elif change == "fc_digest": index["original_feature_collection_sha256"] = "0" * 64
    elif change == "feature_digest": ref["feature_sha256"] = "0" * 64
    elif change == "boundary": ref["municipal_boundary_sha256"] = "0" * 64
    elif change == "outside_proof": ref["reviewed_outside_area_m2"] = 1
    elif change == "distance_proof": ref["reviewed_max_outside_vertex_distance_m"] = .5
    elif change == "duplicate_ref": index["references"].append(copy.deepcopy(ref))
    elif change == "duplicate_feature": index["original_feature_collection"]["features"] *= 2; index["original_feature_collection_sha256"] = _digest(index["original_feature_collection"])
    elif change == "binding_source": ref["reviewed_location_bindings"][0]["source_sha256"] = "0" * 64
    elif change == "binding_request": ref["reviewed_location_bindings"][0]["geometry_request_sha256"] = "0" * 64
    rehash(index); env["official_reference_index_sha256"] = index["index_sha256"]
    if change == "index_digest": index["index_sha256"] = "0" * 64
    if change == "envelope_digest": env["official_reference_index_sha256"] = "0" * 64
    with pytest.raises(ValueError): compile_inputs(values)


@pytest.mark.parametrize("change", ["incident", "place", "coordinates", "transit", "osm", "absent", "scope"])
def test_district_reference_cannot_become_an_actual_location_or_route(change):
    values = inputs(); inv, osm, env, index, border = values; req = inv["geometry_requests"][0]
    if change == "incident": req["role"] = "incident"
    elif change == "place": req["precision"] = "place"
    elif change == "coordinates": req["coordinates"] = [8.6, 50.1]
    elif change == "transit": req["transit_route"] = {"mode": "bus", "line": "63"}
    elif change == "osm": env["decisions"][0]["osm_object_groups"] = [["osm/way/1"]]
    elif change == "absent": env["decisions"][0]["official_reference_id"] = "osm/way/1"
    elif change == "scope": req["city_scope"] = "out_of_city"
    with pytest.raises(ValueError): compile_inputs(values)


def test_independent_border_difference_is_retained_but_larger_discrepancy_is_rejected():
    values = inputs(); inv, osm, env, index, border = values; ref = index["references"][0]
    metric, _ = metric_transforms("EPSG:25832"); metric_border = transform(metric, border)
    for extension, accepted in [(.1, True), (2, False)]:
        native = box(475090, 5560020, 475100 + extension, 5560040)
        feature = index["original_feature_collection"]["features"][0]; feature["geometry"] = mapping(native)
        index["original_feature_collection_sha256"] = _digest(index["original_feature_collection"])
        ref["feature_sha256"] = _digest(feature)
        ref["reviewed_outside_area_m2"] = native.difference(metric_border).area
        ref["reviewed_max_outside_vertex_distance_m"] = max(Point(p).distance(metric_border) for p in native.exterior.coords)
        rehash(index); env["official_reference_index_sha256"] = index["index_sha256"]
        if accepted:
            result = compile_inputs(values)
            assert result["decisions"][0]["derived_geometry"]["source_reference_provenance"][0]["outside_municipality_area_m2"] > 0
        else:
            with pytest.raises(ValueError, match="bounded municipal difference"): compile_inputs(values)


def test_official_index_digest_is_bound_to_map_validation_and_required_on_recompile():
    values = inputs(); inv, osm, env, index, border = values; result = compile_inputs(values)
    result["official_reference_index_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="digest"): _validate_inputs(inv, result, "frankfurt")
    with pytest.raises(ValueError, match="unknown fields"):
        compile_geometry_decisions(inventory=inv, geometry_index=osm, decision_envelope=env, border=border)
