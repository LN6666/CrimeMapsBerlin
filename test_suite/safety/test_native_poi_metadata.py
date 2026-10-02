import copy
import hashlib
import json
from pathlib import Path

import pytest

from crimemapsberlin.native_poi_metadata import apply_native_metadata, selected_raw_elements
from crimemapsberlin.poi_context import context_kind_matches
from crimemapsberlin.poi_context_identities import identity_digest


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inputs(tmp_path, *, native_tags=None, extra_tags=None, kind="fast_food"):
    native_tags = native_tags if native_tags is not None else {"amenity": "fast_food"}
    extra_tags = extra_tags if extra_tags is not None else {"delivery": "yes"}
    raw = tmp_path / "raw.json"
    element = {"type": "node", "id": 1, "lon": 13.4, "lat": 52.5,
               "tags": {**native_tags, **extra_tags, "name": "Native café"}}
    raw.write_text(json.dumps({"elements": [element]}, ensure_ascii=False, separators=(",", ":")))
    poi_root = tmp_path / "poi"
    poi_root.mkdir()
    contract = poi_root / "poi-contract.json"
    contract.write_text("{}")
    feature = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [13.4, 52.5]},
               "properties": {"id": "osm/node/1", "kind": kind,
                              "osm_type_tags": native_tags}}
    proof = tmp_path / "proof.json"
    proof.write_text(json.dumps({"product_path": str(poi_root), "raw_native_selection_path": str(raw),
        "source_pbf_sha256": "p" * 64, "raw_native_selection_sha256": _sha(raw),
        "product_file_hashes": {str(contract): _sha(contract)}, "validation": {"passed": True, "errors": []}}))
    ledger = {"schema_version": 1, "city": "berlin", "poi_contract_sha256": _sha(contract),
              "product_proof_path": str(proof), "product_proof_sha256": _sha(proof),
              "raw_checkpoint_path": str(raw), "raw_checkpoint_sha256": _sha(raw),
              "source_pbf_sha256": "p" * 64, "decisions": [{"poi_id": "osm/node/1",
                  "poi_feature_sha256": identity_digest(feature), "native_object_id": "osm/node/1",
                  "native_element_sha256": identity_digest(element), "tags": extra_tags}]}
    ledger["ledger_sha256"] = identity_digest(ledger)
    kwargs = {"poi_index": {"type": "FeatureCollection", "features": [feature]}, "poi_root": poi_root,
              "contract_sha256": _sha(contract), "source_pbf_sha256": "p" * 64, "city": "berlin",
              "ledger": ledger}
    return kwargs


def _seal(ledger):
    ledger["ledger_sha256"] = identity_digest({k: v for k, v in ledger.items() if k != "ledger_sha256"})


def test_literal_tags_project_without_changing_native_geometry_or_kind(tmp_path):
    kwargs = _inputs(tmp_path)
    before = copy.deepcopy(kwargs)
    projected, changed, review = apply_native_metadata(**kwargs)
    feature = projected["features"][0]
    assert kwargs == before
    assert feature["geometry"] == kwargs["poi_index"]["features"][0]["geometry"]
    assert feature["properties"]["kind"] == "fast_food"
    assert feature["properties"]["osm_type_tags"] == {"amenity": "fast_food"}
    assert changed == [feature] and review["native_pois"] == 1
    assert review["changes_native_geometry_type_or_source_scene"] is False
    assert context_kind_matches("food_delivery", feature["properties"])
    assert not context_kind_matches("food_delivery", kwargs["poi_index"]["features"][0]["properties"])
    raw_path = Path(kwargs["ledger"]["raw_checkpoint_path"])
    assert selected_raw_elements(raw_path, {"osm/node/1"})["osm/node/1"]["tags"]["name"] == "Native café"


@pytest.mark.parametrize("change", [
    lambda x: x["ledger"].update(city="hamburg"),
    lambda x: x["ledger"].update(poi_contract_sha256="x" * 64),
    lambda x: x["ledger"].update(source_pbf_sha256="x" * 64),
    lambda x: x["ledger"].update(raw_checkpoint_sha256="x" * 64),
    lambda x: x["ledger"].update(product_proof_sha256="x" * 64),
    lambda x: x["ledger"]["decisions"][0].update(poi_feature_sha256="x" * 64),
    lambda x: x["ledger"]["decisions"][0].update(native_element_sha256="x" * 64),
    lambda x: x["ledger"]["decisions"][0].update(tags={"delivery": "only"}),
    lambda x: x["ledger"]["decisions"][0].update(tags={"name": "delivery workshop"}),
    lambda x: x["ledger"]["decisions"][0].update(tags={"delivery": True}),
    lambda x: x["ledger"]["decisions"][0].update(native_object_id="osm/node/2"),
    lambda x: x["ledger"]["decisions"].append(copy.deepcopy(x["ledger"]["decisions"][0])),
    lambda x: x["poi_index"]["features"][0]["properties"].update(native_context_metadata={"tags": {"delivery": "yes"}}),
    lambda x: x["poi_index"]["features"][0]["properties"]["osm_type_tags"].update(delivery="yes"),
])
def test_stale_or_invented_metadata_is_rejected_before_projection(tmp_path, change):
    kwargs = _inputs(tmp_path)
    change(kwargs)
    _seal(kwargs["ledger"])
    before = copy.deepcopy(kwargs)
    with pytest.raises(ValueError):
        apply_native_metadata(**kwargs)
    assert kwargs == before


def test_unsealed_ledger_and_absent_native_element_fail_closed(tmp_path):
    kwargs = _inputs(tmp_path)
    kwargs["ledger"]["decisions"][0]["tags"] = {"delivery": "only"}
    with pytest.raises(ValueError, match="digest mismatch"):
        apply_native_metadata(**kwargs)
    with pytest.raises(ValueError, match="missing"):
        selected_raw_elements(Path(kwargs["ledger"]["raw_checkpoint_path"]), {"osm/node/99"})


def test_duplicate_raw_elements_fail_closed(tmp_path):
    kwargs = _inputs(tmp_path)
    path = Path(kwargs["ledger"]["raw_checkpoint_path"])
    element = json.loads(path.read_text())["elements"][0]
    path.write_text(json.dumps({"elements": [element, element]}, separators=(",", ":")))
    with pytest.raises(ValueError, match="Duplicate"):
        selected_raw_elements(path, {"osm/node/1"})


def test_record_lookahead_preserves_unicode_and_selected_members(tmp_path):
    elements = [
        {"type": "node", "id": 1, "tags": {"name": "Café 歩行者", "addr:street": "Große Straße"}},
        {"type": "way", "id": 2, "tags": {"name": "irrelevant " + "ü" * 600_000}},
        {"type": "relation", "id": 3, "members": [{"type": "way", "ref": 2, "role": "outer"}],
         "tags": {"name": 'Literal text {"type":"node","id":99}'}},
    ]
    raw = tmp_path / "lookahead.json"
    raw.write_text(json.dumps({"elements": elements}, ensure_ascii=False, separators=(",", ":")))
    selected = selected_raw_elements(raw, {"osm/node/1", "osm/relation/3"})
    assert selected == {"osm/node/1": elements[0], "osm/relation/3": elements[2]}


def test_selected_native_record_still_has_the_original_decode_limit(tmp_path):
    raw = tmp_path / "oversized.json"
    element = {"type": "way", "id": 1, "tags": {"name": "x" * 1_048_576}}
    raw.write_text(json.dumps({"elements": [element, {"type": "node", "id": 2}]}, separators=(",", ":")))
    with pytest.raises(ValueError, match="exceeds supported bounded framing"):
        selected_raw_elements(raw, {"osm/way/1"})


@pytest.mark.parametrize("beauty", ["nails", "nails;spa", "cosmetics;nails"])
def test_verified_beauty_service_projects_without_reclassifying_native_shop(tmp_path, beauty):
    kwargs = _inputs(tmp_path, native_tags={"shop": "beauty"}, extra_tags={"beauty": beauty}, kind="shop")
    before = copy.deepcopy(kwargs)
    projected, _, _ = apply_native_metadata(**kwargs)
    feature = projected["features"][0]
    assert kwargs == before
    assert feature["geometry"] == before["poi_index"]["features"][0]["geometry"]
    assert feature["properties"]["kind"] == "shop"
    assert feature["properties"]["osm_type_tags"] == {"shop": "beauty"}
    assert feature["properties"]["native_context_metadata"]["tags"] == {"beauty": beauty}
    assert context_kind_matches("nail_salon", feature["properties"])
    kwargs["ledger"]["decisions"][0]["tags"]["beauty"] = "nails;invented"
    _seal(kwargs["ledger"])
    with pytest.raises(ValueError, match="literal tags changed"):
        apply_native_metadata(**kwargs)
