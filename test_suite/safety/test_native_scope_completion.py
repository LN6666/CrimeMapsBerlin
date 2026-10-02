import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import osmium
import pytest
from shapely.geometry import box, shape

MODULES = Path(__file__).parents[2] / "src/crimemapsberlin"
sys.path.insert(0, str(MODULES))
from poi_scope import digest
from poi_scope_completion import complete_background, display_feature, display_manifest_metadata
from poi_scope_validation import validate_completion_receipt

spec = importlib.util.spec_from_file_location("native_core13_candidate", MODULES / "native_core13.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
POLICY = json.loads((Path(__file__).parents[2] / "config/poi-scope.v1.json").read_text())


def point(ident, category="cafe"):
    geometry = {"type": "Point", "coordinates": [13.123456789, 52.123456789]}
    return {"type": "Feature", "geometry": geometry, "location_geometry": deepcopy(geometry),
            "properties": {"id": ident, "kind": category, "geometry_mode": "footprint_missing",
                           "osm_type_tags": {"amenity": category}, "scope_category": category,
                           "neutral_background_only": True, "does_not_locate_or_count_event": True}}


def test_explicit_alias_represents_native_id_without_name_or_geometry_merging():
    old = point("osm/node/1")
    old["properties"]["osm_alias_object_ids"] = ["osm/node/2"]
    missing = point("osm/node/3")
    # All three have identical labels and coordinates; identity alone decides.
    retained = {"type": "FeatureCollection", "features": [old]}
    eligible = {"type": "FeatureCollection", "features": [point("osm/node/1"), point("osm/node/2"), missing]}
    result, receipt = complete_background(retained=retained, eligible=eligible,
                   categories={"osm/node/1": "cafe"}, policy=POLICY)
    assert [f["properties"]["id"] for f in result["features"]] == ["osm/node/1", "osm/node/3"]
    assert result["features"][1] == missing
    assert receipt["eligible_represented_by_explicit_alias_count"] == 1
    assert receipt["added_neutral_count"] == 1 and receipt["supported_native_eligibility_coverage_verified"]
    assert receipt["source_links_or_count_points_created"] is False
    restored = deepcopy(result["features"][0])
    assert restored["properties"].pop("poi_scope_original_feature_sha256") == digest(old)
    assert restored == old and retained["features"][0] == old
    metadata = display_manifest_metadata(result, receipt)
    assert metadata["poi_count"] == 2 and metadata["poi_scope_groups"]["cafe"]["kinds"] == ["cafe"]
    assert "scope_category_by_native_id" not in metadata
    assert validate_completion_receipt(receipt, POLICY) == []
    receipt["added_neutral_count"] += 1
    assert "Supported eligibility coverage partition differs" in validate_completion_receipt(receipt, POLICY)
    receipt["added_neutral_count"] -= 1
    receipt["publication_ready"] = True
    assert "Background completion cannot claim publication_ready" in validate_completion_receipt(receipt, POLICY)


def test_source_only_original_semantics_geometry_survive_display_grouping():
    old = point("osm/node/1", "bench")
    old["properties"].pop("scope_category")
    old["properties"]["native_named_reference"] = {"actual_event_position_known": False,
        "source_context_bindings": [{"source_id": "a", "source_url": "https://official.example/a"}]}
    result = display_feature(old, "source_linked_context")
    assert result["geometry"] == old["geometry"] and result["location_geometry"] == old["location_geometry"]
    assert result["properties"]["native_named_reference"] == old["properties"]["native_named_reference"]
    assert result["properties"]["kind"] == "bench"
    with pytest.raises(ValueError, match="once"):
        display_feature(result, "source_linked_context")


def test_completion_rejects_ambiguous_alias_and_forged_neutral_semantics():
    old, other = point("osm/node/1"), point("osm/node/2")
    old["properties"]["osm_alias_object_ids"] = ["osm/node/2"]
    with pytest.raises(ValueError, match="ambiguous"):
        complete_background(retained={"type": "FeatureCollection", "features": [old, other]},
            eligible={"type": "FeatureCollection", "features": []},
            categories={"osm/node/1": "cafe", "osm/node/2": "cafe"}, policy=POLICY)
    forged = point("osm/node/3")
    forged["properties"]["does_not_locate_or_count_event"] = False
    with pytest.raises(ValueError, match="no source"):
        complete_background(retained={"type": "FeatureCollection", "features": []},
            eligible={"type": "FeatureCollection", "features": [forged]}, categories={}, policy=POLICY)


def test_real_pbf_keeps_untagged_geometry_members_and_unplaced_relations_unknown(tmp_path):
    xml = tmp_path / "tiny.osm"
    xml.write_text('''<osm version="0.6" generator="scope-test">
      <node id="1" version="1" lon="13.1" lat="52.1"><tag k="amenity" v="cafe"/></node>
      <node id="2" version="1" lon="13.2" lat="52.2"/>
      <node id="3" version="1" lon="13.3" lat="52.2"/>
      <node id="4" version="1" lon="13.3" lat="52.3"/>
      <node id="5" version="1" lon="13.2" lat="52.3"/>
      <node id="6" version="1" lon="14.5" lat="52.2"><tag k="shop" v="unusual_literal_type"/></node>
      <node id="7" version="1" lon="13.4" lat="52.4"><tag k="shop" v="vacant"/></node>
      <node id="8" version="1" lon="12.9" lat="52.2"/>
      <node id="9" version="1" lon="13.5" lat="52.2"/>
      <node id="10" version="1" lon="13.4" lat="52.4"><tag k="shop" v="unusual_literal_type"/></node>
      <way id="20" version="1"><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="5"/><nd ref="2"/>
        <tag k="shop" v="mall"/></way>
      <way id="21" version="1"><nd ref="8"/><nd ref="9"/><tag k="amenity" v="parking"/></way>
      <way id="22" version="1"><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="5"/><nd ref="2"/></way>
      <relation id="30" version="1"><member type="way" ref="22" role="outer"/>
        <tag k="type" v="multipolygon"/><tag k="leisure" v="park"/></relation>
      <relation id="31" version="1"><member type="node" ref="1" role="stop"/>
        <tag k="type" v="route"/><tag k="railway" v="station"/></relation>
    </osm>''')
    pbf = tmp_path / "tiny.osm.pbf"
    with osmium.SimpleWriter(str(pbf)) as writer:
        for item in osmium.FileProcessor(str(xml)):
            writer.add(item)
    border = box(13, 52, 14, 53)
    scanner = native.RegionCore(POLICY, {"berlin": border})
    scanner.apply_file(str(pbf), locations=True, idx="sparse_mem_array",
                       filters=[osmium.filter.KeyFilter(*native.FILTER_KEYS)])
    assert set(scanner.features["berlin"]) == {"osm/node/1", "osm/node/10", "osm/way/20", "osm/way/21", "osm/relation/30"}
    assert scanner.region_relations_without_area == {"osm/relation/31"}
    assert scanner.region_objects_without_geometry == {}
    assert scanner.features["berlin"]["osm/way/20"]["native_geometry"]["type"] == "Polygon"
    assert scanner.features["berlin"]["osm/way/21"]["native_geometry"]["type"] == "LineString"
    rows, _ = native.native_display_features("berlin", scanner.features["berlin"], border)
    assert len(rows) == 5
    for row in rows:
        assert native.geometry_covered_by(border, shape(row["geometry"]))
        assert native.geometry_covered_by(border, shape(row["location_geometry"]))
        assert row["properties"]["neutral_background_only"]
        assert row["properties"]["does_not_locate_or_count_event"]


def test_public_context_actions_use_generic_and_keep_raw_source_fields():
    policy = json.loads((Path(__file__).parents[2] / "config/public-context-policy.v1.json").read_text())
    assert policy["allowlist"]["cafe"]["label_key"] == "poi.cafe"
    assert "blood_sample_required" not in policy["allowlist"]
    assert policy["generic_label_key"] == "sourceContext.generic"
    assert policy["source_label_details_evidence_quote_preserved"]
    assert policy["changes_source_context_semantics_or_matching"] is False
