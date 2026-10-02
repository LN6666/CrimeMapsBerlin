"""Synthetic explicit identities; no raw police bodies or generated city data."""

import hashlib
from copy import deepcopy

import pytest
from shapely.geometry import Point, mapping

from crimemapsberlin.poi_context_identities import apply_reviewed_identities, identity_digest
from crimemapsberlin.spatial import associate


def inputs():
    body = "An der Weltzeituhr auf dem Platz. Die genaue Position ist unbekannt."
    source = {"source_id": "report", "source_url": "https://example.invalid/report",
              "source_body": body, "source_sha256": hashlib.sha256(body.encode()).hexdigest()}
    context = {"kind": "landmark", "scope": "named_object", "radius_m": 0,
               "evidence_quote": "An der Weltzeituhr auf dem Platz."}
    scene = {"scene_id": "report:location:1", "role": "discovery", "coordinates": None,
             "geometry": mapping(Point(13.4, 52.5)), "location_object_ids": ["osm/way/1"],
             "event_time": {"date": None, "display": "alarm only"}, "primary_for_count": False,
             "poi_contexts": [context]}
    event = {"id": "report", "source_url": source["source_url"], "source_sha256": source["source_sha256"],
             "coordinates": None, "scene_locations": [scene]}
    # A square reference and the actual clock are distinct native identities.
    square = {"type": "Feature", "geometry": mapping(Point(13.4, 52.5)),
              "properties": {"id": "osm/way/1", "kind": "square", "osm_type_tags": {"place": "square"}}}
    clock = {"type": "Feature", "geometry": mapping(Point(13.401, 52.501)),
             "properties": {"id": "osm/node/2", "kind": "attraction", "osm_type_tags": {"amenity": "clock"}}}
    inventory = {"city": "berlin", "inventory_digest": "a" * 64}
    row = {"context_id": "report:location:1:poi:1", "source_id": "report",
           "source_url": source["source_url"], "source_sha256": source["source_sha256"],
           "context_sha256": identity_digest(context), "native_object_id": "osm/node/2",
           "poi_feature_sha256": identity_digest(clock), "identity_evidence_quotes": [context["evidence_quote"]],
           "review_note": "Explicit named clock context; the square is only a broad scene reference, not this object."}
    ledger = {"schema_version": 1, "city": "berlin", "inventory_digest": inventory["inventory_digest"],
              "poi_contract_sha256": "b" * 64, "decisions": [row]}
    ledger["ledger_sha256"] = identity_digest(ledger)
    return {"events": [event], "source_rows": [source], "inventory": inventory,
            "poi_index": {"type": "FeatureCollection", "features": [square, clock]},
            "poi_contract_sha256": "b" * 64, "ledger": ledger}


def resign(ledger):
    ledger["ledger_sha256"] = identity_digest({k: v for k, v in ledger.items() if k != "ledger_sha256"})


@pytest.mark.parametrize("unknown_scene", [False, True])
@pytest.mark.parametrize("district_scene", [False, True])
def test_named_reference_uses_explicit_clock_not_square_and_does_not_locate_scene(unknown_scene, district_scene):
    value = inputs()
    if unknown_scene:
        value["events"][0]["scene_locations"][0]["geometry"] = None
    if district_scene:
        value["events"][0]["scene_locations"][0]["location_precision"] = "district"
    before = deepcopy(value)
    assert associate(value["events"], value["poi_index"], include_legacy_links=False) == []
    events, proof = apply_reviewed_identities(**value)
    links = associate(events, value["poi_index"], include_legacy_links=False)
    assert [r["poi_id"] for r in links] == ["osm/node/2"]
    assert links[0]["native_identity_review"]["does_not_locate_or_count_scene"] is True
    assert proof["changes_scene_geometry_or_counts"] is False
    scene = events[0]["scene_locations"][0]
    assert {k: v for k, v in scene.items() if k != "poi_contexts"} == {
        k: v for k, v in before["events"][0]["scene_locations"][0].items() if k != "poi_contexts"}
    assert value == before
    again, _ = apply_reviewed_identities(**value)
    assert again == events


@pytest.mark.parametrize("field,bad", [
    ("source_id", "other"), ("source_url", "https://example.invalid/other"), ("source_sha256", "0" * 64),
    ("context_id", "report:location:2:poi:1"), ("context_sha256", "0" * 64),
    ("native_object_id", "osm/node/999"), ("poi_feature_sha256", "0" * 64),
    ("identity_evidence_quotes", ["invented quote"]), ("review_note", ""),
])
def test_changed_or_missing_source_context_native_identity_fails_without_mutation(field, bad):
    value = inputs()
    value["ledger"]["decisions"][0][field] = bad
    resign(value["ledger"])
    before = deepcopy(value)
    with pytest.raises(ValueError):
        apply_reviewed_identities(**value)
    assert value == before


@pytest.mark.parametrize("field,bad", [("city", "hamburg"), ("inventory_digest", "0" * 64),
                                       ("poi_contract_sha256", "0" * 64), ("schema_version", 2)])
def test_ledger_input_bindings_fail_closed(field, bad):
    value = inputs()
    value["ledger"][field] = bad
    resign(value["ledger"])
    with pytest.raises(ValueError):
        apply_reviewed_identities(**value)


@pytest.mark.parametrize("failure", ["digest", "duplicate", "extra_coordinates", "body", "native_type", "native_geometry", "scope", "preprojected"])
def test_forged_or_ambiguous_bindings_are_rejected(failure):
    value = inputs()
    ledger, row = value["ledger"], value["ledger"]["decisions"][0]
    if failure == "digest":
        ledger["ledger_sha256"] = "0" * 64
    elif failure == "duplicate":
        ledger["decisions"].append(deepcopy(row))
    elif failure == "extra_coordinates":
        row["coordinates"] = [13.4, 52.5]
    elif failure == "body":
        value["source_rows"][0]["source_body"] += " Changed."
    elif failure == "native_type":
        row.update(native_object_id="osm/way/1", poi_feature_sha256=identity_digest(value["poi_index"]["features"][0]))
    elif failure == "native_geometry":
        value["poi_index"]["features"][1]["geometry"] = mapping(Point(13.41, 52.51))
    elif failure == "scope":
        context = value["events"][0]["scene_locations"][0]["poi_contexts"][0]
        context["scope"] = "along_geometry"
        row["context_sha256"] = identity_digest(context)
    elif failure == "preprojected":
        value["events"][0]["scene_locations"][0]["poi_contexts"][0]["reviewed_object_ids"] = ["osm/node/2"]
    if failure != "digest":
        resign(ledger)
    with pytest.raises(ValueError):
        apply_reviewed_identities(**value)


def test_later_bad_decision_does_not_partially_apply_an_earlier_valid_one():
    value = inputs()
    value["ledger"]["decisions"].append({**value["ledger"]["decisions"][0], "context_id": "absent"})
    resign(value["ledger"])
    before = deepcopy(value["events"])
    with pytest.raises(ValueError):
        apply_reviewed_identities(**value)
    assert value["events"] == before


def named_place_inputs():
    value = inputs()
    context = value["events"][0]["scene_locations"][0]["poi_contexts"][0]
    context["kind"] = "named_place"
    native = value["poi_index"]["features"][1]
    native["properties"]["name"] = "Weltzeituhr"
    row = value["ledger"]["decisions"][0]
    row["context_sha256"] = identity_digest(context)
    row["poi_feature_sha256"] = identity_digest(native)
    resign(value["ledger"])
    return value


def test_literal_named_place_keeps_unspecified_source_type_and_requires_identity_ledger():
    value = named_place_inputs()
    before = deepcopy(value)
    assert associate(value["events"], value["poi_index"], include_legacy_links=False) == []
    projected, _ = apply_reviewed_identities(**value)
    context = projected[0]["scene_locations"][0]["poi_contexts"][0]
    assert context["kind"] == "named_place"
    assert context["native_identity_review"]["source_context_type_remains_unspecified"] is True
    assert len(associate(projected, value["poi_index"], include_legacy_links=False)) == 1
    assert {key: item for key, item in projected[0]["scene_locations"][0].items() if key != "poi_contexts"} == {
        key: item for key, item in value["events"][0]["scene_locations"][0].items() if key != "poi_contexts"}
    assert value == before


@pytest.mark.parametrize("name", ["zeituhr", "Welt", "Other venue", ""])
def test_named_place_requires_complete_literal_name_not_fragment_or_guessed_identity(name):
    value = named_place_inputs()
    native = value["poi_index"]["features"][1]
    native["properties"]["name"] = name
    value["ledger"]["decisions"][0]["poi_feature_sha256"] = identity_digest(native)
    resign(value["ledger"])
    with pytest.raises(ValueError, match="literal type"):
        apply_reviewed_identities(**value)


@pytest.mark.parametrize("field,bad", [("context_id", "other:location:1:poi:1"),
    ("source_url", "https://example.invalid/other"), ("source_sha256", "0" * 64),
    ("poi_feature_sha256", "0" * 64), ("source_context_type_remains_unspecified", False)])
def test_projected_literal_named_place_cannot_bypass_link_bindings(field, bad):
    value = named_place_inputs()
    projected, _ = apply_reviewed_identities(**value)
    projected[0]["scene_locations"][0]["poi_contexts"][0]["native_identity_review"][field] = bad
    assert associate(projected, value["poi_index"], include_legacy_links=False) == []
