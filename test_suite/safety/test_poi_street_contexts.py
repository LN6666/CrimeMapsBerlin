import copy
import hashlib
import json

import pytest
from shapely.geometry import LineString, Point, mapping
from shapely.ops import transform

from crimemapsberlin.payload import compact
from crimemapsberlin.poi_context_identities import identity_digest
from crimemapsberlin.poi_street_contexts import apply_street_contexts, indexed_street_roads
from crimemapsberlin.spatial import TO_METRIC, TO_WGS, associate

X, Y = TO_METRIC(13.4, 52.5)


def _geo(dx, dy):
    return mapping(transform(TO_WGS, Point(X + dx, Y + dy)))


def _inputs(tmp_path):
    roads = []
    for ident, y in [(11, 0), (22, 800)]:
        geo = mapping(transform(TO_WGS, LineString([(X - 100, Y + y), (X + 100, Y + y)])))
        roads.append({"id": f"osm/way/{ident}", "source_url": f"https://www.openstreetmap.org/way/{ident}",
                      "roles": ["road", "named_object"], "names": ["MainRoad"],
                      "tags": {"highway": "residential", "name": "MainRoad"}, "dimension": "line",
                      "geometry": geo, "geometry_sha256": identity_digest(geo)})
    index = tmp_path / "index.json"
    index.write_text(json.dumps({"objects": roads}, separators=(",", ":")))
    index_proof = tmp_path / "index-proof.json"
    index_proof.write_text(json.dumps({"index_path": str(index), "index_sha256": "i" * 64,
        "index_file_sha256": hashlib.sha256(index.read_bytes()).hexdigest(), "source_pbf_sha256": "p" * 64,
        "readback_validation": {"passed": True, "errors": []}}))
    body = "An unnamed pub on MainRoad was damaged. No business or exact offence point is identified."
    source = {"source_id": "source", "source_url": "https://example.org/official",
              "source_body": body, "source_sha256": hashlib.sha256(body.encode()).hexdigest()}
    context = {"kind": "bar", "scope": "along_geometry", "radius_m": 0,
               "association": "source_reviewed_context_only", "evidence_quote": body}
    scene = {"scene_id": "source:location:1", "role": "incident", "location_precision": "street",
             "geocode_method": "osm_line", "primary_for_count": False, "coordinates": None,
             "geometry": compact(roads[0]["geometry"]), "geometry_sha256": roads[0]["geometry_sha256"],
             "location_object_ids": ["osm/way/11"], "poi_contexts": [context]}
    event = {"id": "source", "source_url": source["source_url"], "source_sha256": source["source_sha256"],
             "coordinates": None, "scene_locations": [scene]}
    geometry = {"ledger_sha256": "g" * 64, "geometry_index_sha256": "i" * 64, "decisions": [{
        "request": {"location_id": scene["scene_id"], "geometry_request_sha256": "r" * 64},
        "derived_geometry": {"type": "LineString", "geometry": roads[0]["geometry"], "source_object_ids": ["osm/way/11"]}}]}
    features = []
    for ident,dy,amenity,street in [(1, 25, "pub", "MainRoad"), (2, 25, "cafe", "MainRoad"),
                                   (3, 825, "pub", "MainRoad"), (4, 25, "pub", "SideRoad")]:
        geo = _geo(0, dy)
        features.append({"type": "Feature", "geometry": geo, "location_geometry": geo,
            "properties": {"id": f"osm/node/{ident}", "name": "Unrelated native name", "kind": "bar" if amenity=="pub" else "cafe",
                "osm_type_tags": {"amenity": amenity}, "geometry_mode": "footprint_missing",
                "native_context_metadata": {"tags": {"addr:street": street}, "ledger_sha256": "m" * 64,
                    "native_object_id": f"osm/node/{ident}", "native_element_sha256": "e" * 64}}})
    ledger = {"schema_version": 1, "city": "berlin", "inventory_digest": "a" * 64,
        "geometry_ledger_sha256": "g" * 64, "poi_contract_sha256": "c" * 64, "native_metadata_sha256": "m" * 64,
        "geometry_index_sha256": "i" * 64, "geometry_index_path": str(index), "index_proof_path": str(index_proof),
        "decisions": [{"context_id": "source:location:1:poi:1", "source_id": "source", "source_url": source["source_url"],
            "source_sha256": source["source_sha256"], "context_sha256": identity_digest(context),
            "geometry_request_sha256": "r" * 64, "street_names": ["MainRoad"], "evidence_quotes": [body]}]}
    ledger["ledger_sha256"] = identity_digest(ledger)
    return {"events": [event], "sources": [source], "inventory": {"city": "berlin", "inventory_digest": "a" * 64},
            "geometry_ledger": geometry, "poi_index": {"type": "FeatureCollection", "features": features},
            "contract_sha256": "c" * 64, "metadata_sha256": "m" * 64, "source_pbf_sha256": "p" * 64,
            "to_metric": TO_METRIC, "ledger": ledger}


def _seal(ledger):
    ledger["ledger_sha256"] = identity_digest({k: v for k, v in ledger.items() if k != "ledger_sha256"})


def test_off_road_address_matches_full_reviewed_street_not_other_same_name_road(tmp_path):
    kwargs = _inputs(tmp_path)
    before = copy.deepcopy({k: v for k, v in kwargs.items() if k != "to_metric"})
    assert associate(kwargs["events"], kwargs["poi_index"], include_legacy_links=False) == []
    events, review = apply_street_contexts(**kwargs)
    assert {k: v for k, v in kwargs.items() if k != "to_metric"} == before
    context = events[0]["scene_locations"][0]["poi_contexts"][0]
    assert context["reviewed_street_poi_ids"] == ["osm/node/1"]
    assert review["results"][0]["rejected_other_same_name_road_or_ambiguous_ids"] == ["osm/node/3"]
    assert review["native_address_candidates"] == 1
    assert review["changes_source_scene_geometry_time_role_count"] is False
    native_scene = events[0]["scene_locations"][0]
    assert {k: v for k, v in native_scene.items() if k != "poi_contexts"} == {
        k: v for k, v in before["events"][0]["scene_locations"][0].items() if k != "poi_contexts"}
    links = associate(events, kwargs["poi_index"], include_legacy_links=False)
    assert len(links) == 1 and links[0]["poi_id"] == "osm/node/1"
    assert links[0]["native_street_review"]["association"] == "source_reviewed_whole_street_address_context_only"
    assert links[0]["status"] == "context_along_geometry"


def test_original_geometry_link_provenance_and_announcement_cap_are_preserved(tmp_path):
    kwargs = _inputs(tmp_path)
    event = kwargs["events"][0]
    event["scene_locations"].append({"scene_id": "source:location:2", "role": "background",
        "geometry": kwargs["poi_index"]["features"][0]["geometry"], "location_object_ids": ["osm/node/1"],
        "poi_contexts": [{"kind": "bar", "scope": "named_object", "radius_m": 0, "evidence_quote": "Prior source context."}]})
    original = associate(kwargs["events"], kwargs["poi_index"], include_legacy_links=False)
    events, _ = apply_street_contexts(**kwargs)
    assert associate(events, kwargs["poi_index"], include_legacy_links=False) == original
    assert len(original) == 1 and "native_street_review" not in original[0]


@pytest.mark.parametrize("change", [
    lambda x: x["ledger"].update(city="hamburg"),
    lambda x: x["ledger"].update(inventory_digest="x" * 64),
    lambda x: x["ledger"].update(geometry_ledger_sha256="x" * 64),
    lambda x: x["ledger"].update(native_metadata_sha256="x" * 64),
    lambda x: x["ledger"]["decisions"][0].update(source_sha256="x" * 64),
    lambda x: x["ledger"]["decisions"][0].update(context_sha256="x" * 64),
    lambda x: x["ledger"]["decisions"][0].update(geometry_request_sha256="x" * 64),
    lambda x: x["ledger"]["decisions"][0].update(street_names=["WrongRoad"]),
    lambda x: x["ledger"]["decisions"][0].update(evidence_quotes=["Invented road or pub."]),
    lambda x: x["ledger"]["decisions"].append(copy.deepcopy(x["ledger"]["decisions"][0])),
    lambda x: x["events"][0]["scene_locations"][0].update(location_precision="unknown"),
    lambda x: x["events"][0]["scene_locations"][0].update(geocode_method="osm_intersection"),
    lambda x: x["events"][0]["scene_locations"][0].update(geometry_usage="source_road_reference_only"),
    lambda x: x["events"][0]["scene_locations"][0].update(source_road_extent="native_endpoint_bounded"),
    lambda x: x["events"][0]["scene_locations"][0]["poi_contexts"][0].update(scope="near_geometry"),
    lambda x: x["events"][0]["scene_locations"][0]["poi_contexts"][0].update(reviewed_street_poi_ids=["osm/node/1"]),
])
def test_changed_evidence_or_bounded_unknown_scope_fails_before_projection(tmp_path, change):
    kwargs = _inputs(tmp_path)
    change(kwargs)
    _seal(kwargs["ledger"])
    before = copy.deepcopy({k: v for k, v in kwargs.items() if k != "to_metric"})
    with pytest.raises(ValueError):
        apply_street_contexts(**kwargs)
    assert {k: v for k, v in kwargs.items() if k != "to_metric"} == before


def test_competing_road_coverage_binds_original_index_and_all_names(tmp_path):
    kwargs = _inputs(tmp_path)
    ledger = kwargs["ledger"]
    from pathlib import Path
    result = indexed_street_roads(index_path=Path(ledger["geometry_index_path"]),
        proof_path=Path(ledger["index_proof_path"]), expected_digest="i" * 64,
        source_pbf_sha256="p" * 64, street_names={"MainRoad"}, required_ids={"osm/way/11"})
    assert set(result) == {"osm/way/11", "osm/way/22"}
    Path(ledger["geometry_index_path"]).write_text("{}")
    with pytest.raises(ValueError, match="index/proof changed"):
        apply_street_contexts(**kwargs)


def spelling_inputs(tmp_path):
    kwargs = _inputs(tmp_path)
    source = kwargs["sources"][0]
    source["source_body"] = source["source_body"].replace("MainRoad", "Main Rd.")
    source["source_sha256"] = hashlib.sha256(source["source_body"].encode()).hexdigest()
    event = kwargs["events"][0]
    event["source_sha256"] = source["source_sha256"]
    context = event["scene_locations"][0]["poi_contexts"][0]
    context["evidence_quote"] = source["source_body"]
    row = kwargs["ledger"]["decisions"][0]
    row.update(source_sha256=source["source_sha256"], context_sha256=identity_digest(context),
               evidence_quotes=[source["source_body"]], source_street_spellings={"MainRoad": "Main Rd."},
               street_spelling_review_note="Individually reviewed source abbreviation for these exact native MainRoad objects, not an automatic alias.")
    _seal(kwargs["ledger"])
    return kwargs


def test_individually_reviewed_source_spelling_preserves_native_names_and_homonym_rejection(tmp_path):
    kwargs = spelling_inputs(tmp_path)
    before = copy.deepcopy(kwargs["events"])
    projected, proof = apply_street_contexts(**kwargs)
    context = projected[0]["scene_locations"][0]["poi_contexts"][0]
    assert context["reviewed_street_poi_ids"] == ["osm/node/1"]
    assert context["native_street_review"]["source_street_spellings"] == {"MainRoad": "Main Rd."}
    assert proof["results"][0]["rejected_other_same_name_road_or_ambiguous_ids"] == ["osm/node/3"]
    assert kwargs["events"] == before
    assert len(associate(projected, kwargs["poi_index"], include_legacy_links=False)) == 1


@pytest.mark.parametrize("change", [
    lambda row: row.update(source_street_spellings={"MainRoad": "Absent spelling"}),
    lambda row: row.update(source_street_spellings={"WrongRoad": "Main Rd."}),
    lambda row: row.update(street_spelling_review_note=""),
    lambda row: row.pop("street_spelling_review_note"),
    lambda row: row.update(street_names=["SideRoad"], source_street_spellings={"SideRoad": "Main Rd."}),
])
def test_unreviewed_forged_or_different_native_road_spelling_fails_closed(tmp_path, change):
    kwargs = spelling_inputs(tmp_path)
    change(kwargs["ledger"]["decisions"][0])
    _seal(kwargs["ledger"])
    with pytest.raises(ValueError):
        apply_street_contexts(**kwargs)
