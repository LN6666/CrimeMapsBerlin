import json

import pytest

from crimemapsberlin import munich_map


def _event(ident, coordinates, precision="street"):
    return {
        "id": f"polizeikarte:{ident}",
        "title": f"Event {ident}",
        "category": "raub",
        "published_at": None,
        "event_date": "2026-09-28",
        "month": "2026-09",
        "time_basis": "polizeikarte_occurred_at",
        "source_url": f"https://polizei.example/{ident}",
        "feed_url": f"https://polizeikarte.example/{ident}",
        "district": "",
        "poi_mentions": [],
        "mention_basis": "not_yet_analyzed",
        "outcome": "unknown",
        "source_status": "polizeikarte_complete_365_day_snapshot",
        "source_sha256": "a" * 64,
        "source_revision": 1,
        "coordinates": coordinates if precision == "street" else None,
        "location_precision": precision,
        "location_label": f"Place {ident}",
        "geocode_method": "polizeikarte_supplied_street_coordinate",
        "geocode_candidates": [],
        "geocode_version": "polizeikarte-upstream-1",
        "location_object_ids": [],
        "geocode_evidence": [],
        "source_summary": "Upstream summary",
        "upstream_category": "raub",
        "upstream_public_precision": precision.upper(),
        "upstream_coordinates": coordinates,
        "upstream_provider": "POLIZEIKARTE",
        "semantic_basis": munich_map.SEMANTIC_BASIS,
    }


def _poi_product(root, catalog_path):
    source_hash = "b" * 64
    boundary = {
        "id": "osm/relation/1",
        "source_pbf_sha256": source_hash,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[10, 47], [12, 47], [12, 49], [10, 49], [10, 47]]],
        },
    }
    catalog_hash = munich_map.hashlib.sha256(catalog_path.read_bytes()).hexdigest()
    values = {
        "poi-contract.json": {
            "schema_version": 2,
            "city": "munich",
            "status": "local_poi_only_unpublished",
            "publication_ready": False,
            "epsg": 25832,
            "poi_count": 0,
            "source_pbf_sha256": source_hash,
            "boundary_source_id": "osm/relation/1",
            "catalog_sha256": catalog_hash,
            "tile_size": [0.04, 0.025],
            "tile_index": {"pois": []},
        },
        "validation.json": {
            "passed": True,
            "errors": [],
            "poi_count": 0,
            "epsg": 25832,
            "source_sha256": source_hash,
            "boundary_source_id": "osm/relation/1",
        },
        "boundary.geojson": boundary,
        "poi-index.json": {"type": "FeatureCollection", "features": []},
        "search.json": [],
    }
    for name, value in values.items():
        (root / name).write_text(json.dumps(value), encoding="utf-8")
    (root / "pois").mkdir()


def test_build_candidate_uses_upstream_semantics_and_boundary_gate(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"poi_types": {}}), encoding="utf-8")
    poi_root = tmp_path / "poi"
    poi_root.mkdir()
    _poi_product(poi_root, catalog)
    events = [
        _event(1, [11.5, 48.1]),
        _event(2, [13.0, 48.1]),
        _event(3, [11.5, 48.1], "city"),
        _event(4, None, "district"),
    ]
    source_audit = {
        "archive_complete": True,
        "coverage": {"active": 4},
        "review_basis": munich_map.SEMANTIC_BASIS,
        "source_first_llm_rereview_required": False,
        "scan_id": "20260928T184246.237060Z",
        "signature": "c" * 64,
    }
    monkeypatch.setattr(
        munich_map, "candidate_snapshot", lambda _path: (events, source_audit)
    )
    output = tmp_path / "candidate"
    audit = munich_map.build_candidate(
        source_db=tmp_path / "unused.sqlite",
        poi_root=poi_root,
        catalog_path=catalog,
        output=output,
    )
    manifest = json.loads((output / "manifest.json").read_text())
    month_path = output / manifest["generation"] / "months" / "2026-09.json"
    month = json.loads(month_path.read_text())
    by_id = {event["id"]: event for event in month["events"]}
    assert audit["events"] == 4
    assert audit["point_entries_in_city"] == 1
    assert audit["known_outside_municipality"] == 1
    assert audit["in_city_nonpoint_representatives_withheld"] == 1
    assert audit["without_upstream_coordinate"] == 1
    assert by_id["polizeikarte:1"]["coordinates"] == [11.5, 48.1]
    assert by_id["polizeikarte:2"]["coordinates"] is None
    assert by_id["polizeikarte:2"]["upstream_coordinates"] == [13.0, 48.1]
    assert by_id["polizeikarte:2"]["location_scope"] == "outside_city"
    assert sum(feature["properties"]["count"] for feature in month["hex"]["detail"]["features"]) == 1
    assert month["links"] == []
    assert manifest["metadata"]["semantic_basis"] == munich_map.SEMANTIC_BASIS
    assert manifest["owner_approved"] is False
    assert manifest["publication_ready"] is False
    assert (output / manifest["generation"] / "roads-overview.json").is_file()


def test_rejects_a_count_point_that_differs_from_upstream_boundary_input():
    boundary = {
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[10, 47], [12, 47], [12, 49], [10, 49], [10, 47]]],
        }
    }
    event = _event(1, [11.5, 48.1])
    event["coordinates"] = [11.6, 48.1]
    with pytest.raises(ValueError, match="differs from upstream precision"):
        munich_map._prepare_events([event], boundary)
