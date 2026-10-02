import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

FILE = Path(__file__).parents[2] / "src/crimemapsberlin/poi_scope.py"
spec = importlib.util.spec_from_file_location("scope_candidate", FILE)
scope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scope)
POLICY = json.loads((Path(__file__).parents[2] / "config/poi-scope.v1.json").read_text())


def feature(ident="osm/node/1", kind="context", tags=None):
    geometry = {"type": "Point", "coordinates": [13.123456789, 52.123456789]}
    return {"type": "Feature", "geometry": geometry, "location_geometry": deepcopy(geometry),
            "properties": {"id": ident, "kind": kind, "name": "unknown",
                           "geometry_mode": "footprint_missing", "osm_type_tags": tags or {"amenity": "bench"}}}


def inputs():
    event = {"id": "a", "source_url": "https://official.example/a", "source_sha256": "a" * 64,
             "scene_locations": [{"role": "discovery", "location_precision": "district", "coordinates": None,
                                  "primary_for_count": False, "event_time": {"precision": "unknown"},
                                  "poi_contexts": []}]}
    rows = [feature(), feature("osm/node/2"), feature("osm/node/3", "cafe", {"amenity": "cafe"})]
    month = {"events": [event], "event_ids": ["a"], "links": [{"event_id": "a", "poi_id": "osm/node/1",
             "source_url": event["source_url"]}], "hex": {"overview": {}, "detail": {}}}
    manifest = {"schema_version": 2, "generation": "g", "months": {"2026-09": {"count": 1}},
                "tile_index": {"pois": ["context/1_2", "cafe/1_2"]}, "metadata": {"poi_count": 3},
                "publication_ready": False, "owner_approved": False}
    files = {"g/months/2026-09.json": month,
             "g/pois/context/1_2.json": {"type": "FeatureCollection", "features": rows[:2]},
             "g/pois/cafe/1_2.json": {"type": "FeatureCollection", "features": rows[2:]},
             "g/search.json": [{"id": r["properties"]["id"], "name": "unknown"} for r in rows]}
    return manifest, {k: json.dumps(v).encode() for k, v in files.items()}


def run(manifest, files):
    writes = {}
    result, receipt = scope.transform_artifact(manifest=manifest, read=lambda p: files[p], policy=POLICY,
                                             write=lambda p, b: writes.__setitem__(p, b))
    return result, receipt, writes


def modify(files, path, action):
    value = json.loads(files[path])
    action(value)
    files[path] = json.dumps(value).encode()


def test_lossless_scope_and_unchanged_unknown_scene_count_and_approval():
    manifest, files = inputs()
    before = deepcopy(manifest)
    result, receipt, writes = run(manifest, files)
    assert (receipt["poi_count"], receipt["background_core_count"], receipt["source_only_count"]) == (2, 1, 1)
    assert receipt["source_poi_pair_count"] == 1 and receipt["all_protected_ids_retained"]
    assert json.loads(writes["g/pois/context/1_2.json"])["features"][0] == json.loads(
        files["g/pois/context/1_2.json"])["features"][0]
    assert "g/months/2026-09.json" in receipt["unchanged_files"] and "g/months/2026-09.json" not in writes
    assert manifest == before and result["owner_approved"] is False and result["publication_ready"] is False
    assert [r["id"] for r in json.loads(writes["g/search.json"])] == ["osm/node/1", "osm/node/3"]


@pytest.mark.parametrize("field,value,error", [("poi_id", "osm/node/99", "absent"),
    ("source_url", "https://other.example/a", "source")])
def test_missing_or_stale_source_link_fails(field, value, error):
    manifest, files = inputs()
    modify(files, "g/months/2026-09.json", lambda m: m["links"][0].__setitem__(field, value))
    with pytest.raises(ValueError, match=error):
        run(manifest, files)


def test_duplicate_pair_fails():
    manifest, files = inputs()
    modify(files, "g/months/2026-09.json", lambda m: m["links"].append(deepcopy(m["links"][0])))
    with pytest.raises(ValueError, match="Duplicate announcement/POI"):
        run(manifest, files)


def test_conflicting_stable_native_identity_fails():
    manifest, files = inputs()
    manifest["tile_index"]["pois"].append("context/2_2")
    files["g/pois/context/2_2.json"] = files["g/pois/context/1_2.json"]
    modify(files, "g/pois/context/2_2.json", lambda t: t["features"][0]["geometry"]["coordinates"].__setitem__(0, 20))
    with pytest.raises(ValueError, match="Conflicting"):
        run(manifest, files)


def test_source_only_unknown_native_type_is_preserved_with_current_binding():
    manifest, files = inputs()
    tile = json.loads(files["g/pois/context/1_2.json"])
    properties = tile["features"][0]["properties"]
    properties.pop("osm_type_tags")
    properties["native_type_unknown"] = True
    properties["native_named_reference"] = {"source_context_bindings": [{"source_id": "a",
        "source_url": "https://official.example/a", "source_sha256": "a" * 64}]}
    files["g/pois/context/1_2.json"] = json.dumps(tile).encode()
    _, _, writes = run(manifest, files)
    assert json.loads(writes["g/pois/context/1_2.json"])["features"][0] == tile["features"][0]
    properties["native_named_reference"]["source_context_bindings"][0]["source_sha256"] = "b" * 64
    files["g/pois/context/1_2.json"] = json.dumps(tile).encode()
    with pytest.raises(ValueError, match="binding changed"):
        run(manifest, files)


def test_missing_native_tags_cannot_be_replaced_by_name():
    value = feature()
    value["properties"].pop("osm_type_tags")
    value["properties"]["name"] = "famous cafe"
    with pytest.raises(ValueError, match="osm_type_tags"):
        scope.select_feature(value, {"osm/node/1"}, POLICY)


def test_explicit_identity_without_spatial_link_is_kept():
    manifest, files = inputs()
    modify(files, "g/months/2026-09.json", lambda m: m["events"][0]["scene_locations"][0].__setitem__(
        "poi_contexts", [{"reviewed_object_ids": ["osm/node/2"]}]))
    _, receipt, writes = run(manifest, files)
    assert receipt["poi_count"] == 3 and not any("/pois/" in p for p in writes)


def test_native_alias_retains_canonical_object():
    manifest, files = inputs()
    modify(files, "g/months/2026-09.json", lambda m: m["links"][0].__setitem__("poi_id", "osm/node/9"))
    modify(files, "g/pois/context/1_2.json", lambda t: t["features"][0]["properties"].__setitem__(
        "osm_alias_object_ids", ["osm/node/9"]))
    _, receipt, _ = run(manifest, files)
    assert receipt["poi_count"] == 2 and receipt["all_protected_ids_retained"]


def test_native_platform_is_only_source_linked_without_literal_bus_or_tram():
    value = feature("osm/way/1", "station", {"railway": "platform"})
    assert scope.select_feature(value, set(), POLICY) == (False, None)
    assert scope.select_feature(value, {"osm/way/1"}, POLICY) == (True, None)


@pytest.mark.parametrize("path", ["../a", "/a", "a/../b", "a\\b"])
def test_unsafe_paths_fail(path):
    with pytest.raises(ValueError):
        scope.safe_path(path)


def test_core_rules_match_existing_classifier_and_city_set():
    from crimemapsberlin.spatial import classify_poi
    samples = [{}, {"name": "bar"}, {"shop": "vacant"}, {"shop": "supermarket"}, {"shop": "  "},
               {"railway": "platform"}, {"public_transport": "platform", "train": "yes"},
               {"amenity": "pub", "shop": "yes"}, {"leisure": "park", "landuse": "grass"}]
    for rule in POLICY["background_rules"]:
        for alternative in rule.get("alternatives", []):
            samples.append({k: v[0] for k, v in alternative.items()})
    for tags in samples:
        assert scope.core_kind(tags, POLICY) == classify_poi(tags)
    assert len(POLICY["background_categories"]) == 13 and len(POLICY["cities"]) == 14


def test_original_pbf_tags_adapter_is_literal_and_hash_bound():
    value = feature('osm/way/1', 'bakery', {'shop': 'bakery'})
    properties = value['properties']
    properties['native_tags'] = properties.pop('osm_type_tags')
    properties['tag_provenance'] = 'original_current_PBF'
    properties['source_pbf_sha256'] = 'a' * 64
    assert scope.select_feature(value, set(), POLICY) == (True, 'shop')
    assert value['properties']['kind'] == 'bakery'
    properties['source_pbf_sha256'] = 'wrong'
    with pytest.raises(ValueError, match='source binding'):
        scope.select_feature(value, set(), POLICY)


def test_idless_search_is_rebuilt_from_retained_native_ids_and_existing_values():
    manifest, files = inputs()
    modify(files, 'g/search.json', lambda search: [row.pop('id') for row in search])
    _, receipt, writes = run(manifest, files)
    assert receipt['search_mode'] == 'rebuilt_from_retained_native_features'
    assert [row['id'] for row in json.loads(writes['g/search.json'])] == ['osm/node/1', 'osm/node/3']


def test_custom_feature_collection_adapter_keeps_exact_selected_values():
    collection = {'type': 'FeatureCollection', 'features': [feature(), feature('osm/node/2'),
                  feature('osm/node/3', 'cafe', {'amenity': 'cafe'})]}
    old = deepcopy(collection)
    links = [{'event_id': 'a', 'poi_id': 'osm/node/1', 'source_url': 'https://official.example/a'}]
    filtered, receipt = scope.filter_feature_collection(collection=collection, source_links=links,
                                                        explicit_native_ids=set(), policy=POLICY)
    assert collection == old and filtered['features'] == [old['features'][0], old['features'][2]]
    assert receipt['display_category_counts'] == {'cafe': 1, 'context': 1}
    assert receipt['publication_ready'] is False


def test_receipt_validator_rejects_invented_completion_and_bad_partition():
    spec = importlib.util.spec_from_file_location('scope_validator', FILE.with_name('poi_scope_validation.py'))
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    manifest, files = inputs()
    _, receipt, _ = run(manifest, files)
    assert validator.validate_receipt(receipt, POLICY) == []
    bad = deepcopy(receipt)
    bad['publication_ready'] = True
    assert any('publication_ready' in e for e in validator.validate_receipt(bad, POLICY))
    bad = deepcopy(receipt)
    bad['source_only_count'] += 1
    assert any('partition' in e for e in validator.validate_receipt(bad, POLICY))


def test_duplicate_month_inventory_and_ambiguous_native_alias_fail():
    manifest, files = inputs()
    modify(files, 'g/months/2026-09.json', lambda month: month['event_ids'].append('a'))
    with pytest.raises(ValueError, match='Month event inventory'):
        run(manifest, files)
    manifest, files = inputs()
    modify(files, 'g/pois/context/1_2.json', lambda tile: [feature['properties'].__setitem__(
        'osm_alias_object_ids', ['osm/node/9']) for feature in tile['features']])
    with pytest.raises(ValueError, match='multiple POI identities'):
        run(manifest, files)
