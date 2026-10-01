import hashlib
import json
import math
from copy import deepcopy

import pytest
from shapely.geometry import Point, box, mapping

from crimemapsberlin.payload import compact
from crimemapsberlin.reviewed_poi_product import _digest, validate_reviewed_poi_product
from crimemapsberlin.tiles import DX, DY


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _product(root):
    source, ident = "a" * 64, "osm/node/1"
    raw = {
        "city": "hamburg",
        "source_pbf_sha256": source,
        "records": [{"object_id": ident, "source_pbf_sha256": source}],
    }
    record = raw["records"][0]
    record["native_record_sha256"] = _digest(record)
    raw_sha = _write(root / "records.json", raw)
    policy = {"city": "hamburg", "source_pbf_sha256": source, "raw_capture_sha256": raw_sha}
    policy_sha = _write(root / "policy.json", policy)
    choices = {
        "city": "hamburg",
        "policy_sha256": policy_sha,
        "choices": [
            {
                "object_id": ident,
                "native_record_sha256": record["native_record_sha256"],
                "context_kinds_to_add": ["school"],
            }
        ],
    }
    choices_sha = _write(root / "choices.json", choices)
    catalog = root / "catalog.json"
    catalog_sha = _write(catalog, {"poi_types": {"park": {}, "school": {}}})
    point = mapping(Point(10.001, 53.551))
    feature = {
        "type": "Feature",
        "geometry": point,
        "location_geometry": point,
        "properties": {
            "id": ident,
            "name": "Reviewed place",
            "aliases": [],
            "kind": "park",
            "context_kinds": ["park", "school"],
            "center": [10.001, 53.551],
            "source_url": "https://www.openstreetmap.org/node/1",
            "native_type_addition_binding": {
                "record_sha256": record["native_record_sha256"],
                "policy_sha256": policy_sha,
                "source_pbf_sha256": source,
                "kinds": ["school"],
                "mapped_reference_only": True,
                "source_venue_identity_verified": False,
                "whole_compound_or_legal_boundary_verified": False,
            },
        },
    }
    index = {"type": "FeatureCollection", "features": [feature]}
    index_sha = _write(root / "poi-index.json", index)
    key = f"{math.floor(10.001 / DX)}_{math.floor(53.551 / DY)}"
    keys = [f"{kind}/{key}" for kind in ("park", "school")]
    for tile in keys:
        _write(root / "pois" / f"{tile}.json", compact(index))
    _write(
        root / "search.json",
        [{k: feature["properties"][k] for k in ("id", "name", "aliases", "kind", "context_kinds", "center")}],
    )
    _write(
        root / "boundary.geojson",
        {
            "id": "osm/relation/1",
            "source_pbf_sha256": source,
            "geometry": mapping(box(9.9, 53.4, 10.1, 53.7)),
        },
    )
    contract = {
        "schema_version": 2,
        "city": "hamburg",
        "epsg": 25832,
        "tile_size": [DX, DY],
        "status": "local_poi_only_unpublished",
        "publication_ready": False,
        "source_pbf_sha256": source,
        "boundary_source_id": "osm/relation/1",
        "poi_count": 1,
        "catalog_sha256": catalog_sha,
        "native_followup_policy_sha256": policy_sha,
        "native_followup_choices_sha256": choices_sha,
        "tile_index": {"pois": keys},
    }
    contract_sha = _write(root / "poi-contract.json", contract)
    binding = {
        "schema_version": 1,
        "city": "hamburg",
        "inventory_digest": "b" * 64,
        "status": "local_reviewed_context_membership_candidate_unpublished",
        "owner_approved": False,
        "publication_ready": False,
        "source_pbf_sha256": source,
        "poi_count": 1,
        "poi_index_sha256": index_sha,
        "poi_contract_sha256": contract_sha,
        "catalog_sha256": catalog_sha,
        "native_taxonomy_policy_sha256": policy_sha,
        "review_files": {
            k: {"path": str(root / name), "sha256": sha}
            for k, name, sha in (
                ("native_policy", "policy.json", policy_sha),
                ("native_choices", "choices.json", choices_sha),
                ("native_records", "records.json", raw_sha),
            )
        },
    }
    return binding, catalog, index, keys


def _validate(root, binding, catalog):
    return validate_reviewed_poi_product(
        city="hamburg", poi_root=root, catalog_path=catalog, binding=binding, inventory_digest="b" * 64
    )


def test_one_reviewed_native_object_can_belong_to_two_types_without_two_objects(tmp_path):
    binding, catalog, _, _ = _product(tmp_path)
    result = _validate(tmp_path, binding, catalog)
    assert result["poi_count"] == 1
    assert result["context_memberships"] == {"park": 1, "school": 1}
    assert result["tile_count"] == 2
    assert result["owner_approved"] is result["publication_ready"] is False


def test_tile_tampering_is_detected_even_when_index_binding_is_unchanged(tmp_path):
    binding, catalog, index, keys = _product(tmp_path)
    index["features"][0]["geometry"]["coordinates"] = [10.02, 53.55]
    _write(tmp_path / "pois" / f"{keys[0]}.json", compact(index))
    with pytest.raises(ValueError, match="tile differs"):
        _validate(tmp_path, binding, catalog)


@pytest.mark.parametrize("change", ["invented_venue", "missing_binding", "unknown_type"])
def test_rehashed_index_cannot_upgrade_or_omit_individually_reviewed_native_evidence(tmp_path, change):
    binding, catalog, index, _ = _product(tmp_path)
    p = index["features"][0]["properties"]
    if change == "invented_venue":
        p["native_type_addition_binding"]["source_venue_identity_verified"] = True
    elif change == "missing_binding":
        del p["native_type_addition_binding"]
    else:
        p["context_kinds"].append("invented_type")
    binding["poi_index_sha256"] = _write(tmp_path / "poi-index.json", index)
    with pytest.raises(ValueError, match="membership|binding"):
        _validate(tmp_path, binding, catalog)


def test_stale_inventory_cannot_reuse_previously_successful_poi_validation(tmp_path):
    binding, catalog, _, _ = _product(tmp_path)
    stale = deepcopy(binding)
    stale["inventory_digest"] = "c" * 64
    with pytest.raises(ValueError, match="Stale or invalid"):
        _validate(tmp_path, stale, catalog)
