"""Synthetic source-selected native reference areas; no production bodies/data."""

import hashlib
import json
from copy import deepcopy

import pytest
from shapely.geometry import MultiPolygon, Polygon, mapping

from crimemapsberlin.native_poi_references import merge_identity_ledgers, reference_features
from crimemapsberlin.poi_context_identities import apply_reviewed_identities, identity_digest
from crimemapsberlin.spatial import associate


def inputs(tmp_path):
    body = "Vor dem ausdrücklich genannten Institut. Genaue Position unbekannt."
    source = {"source_id": "source", "source_url": "https://example.invalid/source", "source_body": body,
              "source_sha256": hashlib.sha256(body.encode()).hexdigest()}
    context = {"kind": "institution", "scope": "named_object", "radius_m": 0,
               "evidence_quote": "Vor dem ausdrücklich genannten Institut."}
    event = {"id": "source", "source_url": source["source_url"], "source_sha256": source["source_sha256"],
             "scene_locations": [{"scene_id": "source:location:1", "role": "operation", "geometry": None,
                                  "coordinates": None, "primary_for_count": False, "poi_contexts": [context]}]}
    geometry = mapping(Polygon([(13.4, 52.5), (13.401, 52.5), (13.401, 52.501), (13.4, 52.5)]))
    obj = {"id": "osm/way/1", "source_url": "https://www.openstreetmap.org/way/1", "roles": ["named_object"],
           "names": ["Native named institute"], "tags": {"name": "Native named institute"}, "geometry": geometry,
           "geometry_sha256": identity_digest(geometry)}
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps({"objects": [obj]}, ensure_ascii=False, separators=(",", ":")))
    proof_path = tmp_path / "proof.json"
    proof = {"index_path": str(index_path), "index_sha256": "i" * 64,
             "index_file_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
             "source_pbf_sha256": "p" * 64, "readback_validation": {"passed": True, "errors": []}}
    proof_path.write_text(json.dumps(proof))
    row = {"context_id": "source:location:1:poi:1", "source_id": "source", "source_url": source["source_url"],
           "source_sha256": source["source_sha256"], "context_sha256": identity_digest(context),
           "native_object_id": obj["id"], "native_object_sha256": identity_digest(obj),
           "identity_evidence_quotes": [context["evidence_quote"]],
           "review_note": "The source-selected exact native named object is a reference, not the event position or a typed venue."}
    ledger = {"schema_version": 1, "city": "berlin", "inventory_digest": "a" * 64,
              "poi_contract_sha256": "b" * 64, "geometry_index_sha256": "i" * 64,
              "geometry_index_path": str(index_path), "index_proof_path": str(proof_path), "decisions": [row]}
    ledger["ledger_sha256"] = identity_digest(ledger)
    return {"events": [event], "sources": [source], "inventory": {"city": "berlin", "inventory_digest": "a" * 64},
            "geometry_ledger": {"geometry_index_sha256": "i" * 64},
            "poi_index": {"type": "FeatureCollection", "features": []}, "contract_sha256": "b" * 64,
            "source_pbf_sha256": "p" * 64,
            "boundary": {"geometry": mapping(Polygon([(13.3, 52.4), (13.5, 52.4), (13.5, 52.6), (13.3, 52.4)]))},
            "ledger": ledger}


def resign(ledger):
    ledger["ledger_sha256"] = identity_digest({k: v for k, v in ledger.items() if k != "ledger_sha256"})


def test_selected_native_area_retains_type_absence_exact_vertices_and_source_roles(tmp_path):
    value = inputs(tmp_path)
    before = deepcopy(value)
    features, ledger = reference_features(**value)
    props = features[0]["properties"]
    assert props["kind"] == "context" and props["native_type_unknown"] is True
    assert props["geometry_mode"] == "native_named_reference_area"
    assert props["center"] == list(features[0]["geometry"]["coordinates"][0][0])
    assert props["native_named_reference"]["source_context_bindings"][0]["role"] == "operation"
    pois = {"type": "FeatureCollection", "features": features}
    assert associate(value["events"], pois, include_legacy_links=False) == []
    projected, _ = apply_reviewed_identities(events=value["events"], source_rows=value["sources"],
        inventory=value["inventory"], poi_index=pois, poi_contract_sha256=value["contract_sha256"], ledger=ledger)
    links = associate(projected, pois, include_legacy_links=False)
    assert len(links) == 1 and links[0]["poi_id"] == "osm/way/1"
    scene = projected[0]["scene_locations"][0]
    assert scene["geometry"] is scene["coordinates"] is None and scene["primary_for_count"] is False
    assert scene["role"] == "operation"
    assert value == before


@pytest.mark.parametrize("field,bad", [
    ("native_object_sha256", "0" * 64), ("context_sha256", "0" * 64),
    ("source_sha256", "0" * 64), ("source_url", "https://example.invalid/other"),
    ("context_id", "absent"), ("native_object_id", "osm/way/999"),
    ("identity_evidence_quotes", ["forged quote"]), ("review_note", ""),
])
def test_changed_source_context_or_native_object_fails_closed(tmp_path, field, bad):
    value = inputs(tmp_path)
    value["ledger"]["decisions"][0][field] = bad
    resign(value["ledger"])
    with pytest.raises(ValueError):
        reference_features(**value)


@pytest.mark.parametrize("failure", ["source_body", "border", "duplicate_context", "alias_collision", "index_bytes", "index_digest", "proof", "scope", "extra_coordinate"])
def test_no_guessed_or_stale_reference_or_preexisting_alias(tmp_path, failure):
    value = inputs(tmp_path)
    row = value["ledger"]["decisions"][0]
    if failure == "source_body":
        value["sources"][0]["source_body"] += " Changed."
    elif failure == "border":
        value["boundary"]["geometry"] = mapping(Polygon([(0, 0), (1, 0), (1, 1), (0, 0)]))
    elif failure == "duplicate_context":
        value["ledger"]["decisions"].append(deepcopy(row))
    elif failure == "alias_collision":
        value["poi_index"]["features"] = [{"properties": {"id": "osm/node/2", "osm_alias_object_ids": ["osm/way/1"]}}]
    elif failure == "index_bytes":
        path = tmp_path / "index.json"
        path.write_text(path.read_text() + " ")
    elif failure == "index_digest":
        value["geometry_ledger"]["geometry_index_sha256"] = "other"
    elif failure == "proof":
        path = tmp_path / "proof.json"
        proof = json.loads(path.read_text())
        proof["readback_validation"]["passed"] = False
        path.write_text(json.dumps(proof))
    elif failure == "scope":
        c = value["events"][0]["scene_locations"][0]["poi_contexts"][0]
        c["scope"] = "along_geometry"
        row["context_sha256"] = identity_digest(c)
    elif failure == "extra_coordinate":
        row["coordinates"] = [13.4, 52.5]
    resign(value["ledger"])
    with pytest.raises(ValueError):
        reference_features(**value)


def test_multiple_contexts_on_one_reference_preserve_all_bindings_but_cap_one_report(tmp_path):
    value = inputs(tmp_path)
    scene = deepcopy(value["events"][0]["scene_locations"][0])
    scene["scene_id"] = "source:location:2"
    scene["role"] = "background"
    value["events"][0]["scene_locations"].append(scene)
    value["ledger"]["decisions"].append({**value["ledger"]["decisions"][0], "context_id": "source:location:2:poi:1"})
    resign(value["ledger"])
    features, ledger = reference_features(**value)
    assert len(features) == 1 and len(features[0]["properties"]["native_named_reference"]["source_context_bindings"]) == 2
    pois = {"type": "FeatureCollection", "features": features}
    projected, _ = apply_reviewed_identities(events=value["events"], source_rows=value["sources"], inventory=value["inventory"],
        poi_index=pois, poi_contract_sha256=value["contract_sha256"], ledger=ledger)
    assert len(associate(projected, pois, include_legacy_links=False)) == 1
    assert merge_identity_ledgers([ledger]) == ledger
    with pytest.raises(ValueError, match="Duplicate"):
        merge_identity_ledgers([ledger, ledger])


def install_native_object(value, tmp_path, obj):
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps({"objects": [obj]}, ensure_ascii=False, separators=(",", ":")))
    proof_path = tmp_path / "proof.json"
    proof = json.loads(proof_path.read_text())
    proof["index_file_sha256"] = hashlib.sha256(index_path.read_bytes()).hexdigest()
    proof_path.write_text(json.dumps(proof))
    row = value["ledger"]["decisions"][0]
    row["native_object_sha256"] = identity_digest(obj)
    resign(value["ledger"])


@pytest.mark.parametrize("pedestrian", [False, True])
def test_native_multipolygon_preserves_separate_parts_holes_and_literal_type(tmp_path, pedestrian):
    value = inputs(tmp_path)
    value["boundary"]["geometry"] = mapping(Polygon([
        (13.3, 52.4), (13.5, 52.4), (13.5, 52.6), (13.3, 52.6), (13.3, 52.4),
    ]))
    obj = json.loads((tmp_path / "index.json").read_text())["objects"][0]
    geometry = mapping(MultiPolygon([
        Polygon([(13.4, 52.5), (13.402, 52.5), (13.402, 52.502), (13.4, 52.502)],
                [[(13.4005, 52.5005), (13.401, 52.5005), (13.401, 52.501), (13.4005, 52.501)]]),
        Polygon([(13.403, 52.5), (13.404, 52.5), (13.404, 52.501), (13.403, 52.5)]),
    ]))
    obj["geometry"] = geometry
    obj["geometry_sha256"] = identity_digest(geometry)
    if pedestrian:
        obj["tags"]["highway"] = "pedestrian"
        context = value["events"][0]["scene_locations"][0]["poi_contexts"][0]
        context["kind"] = "pedestrian_zone"
        value["ledger"]["decisions"][0]["context_sha256"] = identity_digest(context)
    install_native_object(value, tmp_path, obj)
    features, identities = reference_features(**value)
    feature = features[0]
    assert identity_digest(feature["geometry"]) == identity_digest(geometry)
    assert feature["properties"]["geometry_source_type"] == "MultiPolygon"
    assert feature["properties"]["center"] == list(geometry["coordinates"][0][0][0])
    assert feature["properties"]["native_type_unknown"] is not pedestrian
    if pedestrian:
        assert feature["properties"]["osm_type_tags"] == {"highway": "pedestrian"}
    pois = {"type": "FeatureCollection", "features": features}
    projected, _ = apply_reviewed_identities(events=value["events"], source_rows=value["sources"],
        inventory=value["inventory"], poi_index=pois, poi_contract_sha256=value["contract_sha256"], ledger=identities)
    assert len(associate(projected, pois, include_legacy_links=False)) == 1
    scene = projected[0]["scene_locations"][0]
    assert scene["coordinates"] is scene["geometry"] is None and not scene["primary_for_count"]
    assert scene["role"] == "operation"
    if pedestrian:
        assert "native_type_basis" not in scene["poi_contexts"][0]["native_identity_review"]


def test_pedestrian_type_cannot_be_selected_as_an_unspecified_institution(tmp_path):
    value = inputs(tmp_path)
    obj = json.loads((tmp_path / "index.json").read_text())["objects"][0]
    obj["tags"]["highway"] = "pedestrian"
    install_native_object(value, tmp_path, obj)
    with pytest.raises(ValueError, match="pedestrian-zone"):
        reference_features(**value)


def test_one_outside_multipolygon_part_cannot_be_silently_discarded(tmp_path):
    value = inputs(tmp_path)
    obj = json.loads((tmp_path / "index.json").read_text())["objects"][0]
    obj["geometry"] = mapping(MultiPolygon([Polygon(obj["geometry"]["coordinates"][0]),
        Polygon([(0, 0), (1, 0), (1, 1), (0, 0)])]))
    obj["geometry_sha256"] = identity_digest(obj["geometry"])
    install_native_object(value, tmp_path, obj)
    with pytest.raises(ValueError, match="in-city"):
        reference_features(**value)
