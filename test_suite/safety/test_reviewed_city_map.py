import hashlib
import json

import pytest
from shapely.geometry import LineString, Point, mapping

from crimemapsberlin import reviewed_city_map

GEOMETRY_CORE_KEYS = (
    "schema_version",
    "city",
    "inventory_digest",
    "submitted_inventory_digest",
    "geometry_index_sha256",
    "decisions",
)


def _geometry_digest(geometry):
    core = {key: geometry.get(key) for key in GEOMETRY_CORE_KEYS}
    return hashlib.sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _inputs():
    body = "Am Nordmarkt wurde ein Mann beraubt. Die Festnahme erfolgte am Hauptbahnhof."
    source_hash = hashlib.sha256(body.encode()).hexdigest()
    sources = [
        {
            "source_id": "source-1",
            "source_url": "https://example.invalid/source-1",
            "title": "Raub am Nordmarkt",
            "published": "2026-09-29T12:00:00+02:00",
            "source_body": body,
            "source_sha256": source_hash,
            "revision": 1,
        }
    ]
    locations = [
        {
            "location_id": "source-1:location:1",
            "label": "Nordmarkt",
            "role": "incident",
            "precision": "place",
            "city_scope": "in_city",
            "evidence_quotes": ["Am Nordmarkt wurde ein Mann beraubt."],
            "coordinates": None,
        },
        {
            "location_id": "source-1:location:2",
            "label": "Hauptbahnhof",
            "role": "arrest",
            "precision": "place",
            "city_scope": "in_city",
            "evidence_quotes": ["Die Festnahme erfolgte am Hauptbahnhof."],
            "coordinates": None,
        },
    ]
    inventory = {
        "schema_version": 1,
        "city": "dusseldorf",
        "inventory_digest": "a" * 64,
        "all_current_reviews_supported": True,
        "articles": [
            {
                "source_id": "source-1",
                "source_url": sources[0]["source_url"],
                "source_sha256": source_hash,
                "decision_sha256": "b" * 64,
                "scope_verdict": "in_city",
                "incident_count": 1,
                "incidents": [
                    {
                        "incident_id": "source-1:incident:1",
                        "evidence_quotes": ["Am Nordmarkt wurde ein Mann beraubt."],
                        "formal_location_ids": ["source-1:location:1"],
                    }
                ],
                "formal_locations": locations,
            }
        ],
    }
    geometry = {
        "schema_version": 1,
        "city": "dusseldorf",
        "inventory_digest": inventory["inventory_digest"],
        "ledger_sha256": "c" * 64,
        "geometry_review_complete": True,
        "pending_count": 0,
        "request_count": 2,
        "decisions": [
            {
                "request": {
                    "source_id": "source-1",
                    "location_id": "source-1:location:1",
                    "incident_ids": ["source-1:incident:1"],
                },
                "decision": {"verdict": "resolved", "method": "osm_point"},
                "derived_geometry": {
                    "type": "Point",
                    "geometry": mapping(Point(6.77, 51.23)),
                    "geometry_sha256": "d" * 64,
                    "source_object_ids": ["osm/node/1"],
                },
            },
            {
                "request": {
                    "source_id": "source-1",
                    "location_id": "source-1:location:2",
                    "incident_ids": [],
                },
                "decision": {"verdict": "resolved", "method": "osm_line"},
                "derived_geometry": {
                    "type": "LineString",
                    "geometry": mapping(LineString([(6.76, 51.22), (6.78, 51.24)])),
                    "geometry_sha256": "e" * 64,
                    "source_object_ids": ["osm/way/2"],
                },
            },
        ],
    }
    geometry["ledger_sha256"] = _geometry_digest(geometry)
    decision = {
        "schema_version": 1,
        "city": "dusseldorf",
        "source_id": "source-1",
        "source_sha256": source_hash,
        "source_review_sha256": "b" * 64,
        "article_category": "raub",
        "is_crime_report": True,
        "classification_evidence_quotes": ["Am Nordmarkt wurde ein Mann beraubt."],
        "incident_categories": [
            {
                "incident_id": "source-1:incident:1",
                "category": "raub",
                "evidence_quotes": ["Am Nordmarkt wurde ein Mann beraubt."],
            }
        ],
        "primary_count_incident_id": "source-1:incident:1",
        "primary_count_location_id": "source-1:location:1",
        "review_note": "The incident has one checked primary point.",
        "reviewer": "test-reviewer",
        "reviewed_at": "2026-09-29T13:00:00+02:00",
    }
    map_ledger = {
        "schema_version": 1,
        "city": "dusseldorf",
        "inventory_digest": inventory["inventory_digest"],
        "geometry_ledger_sha256": geometry["ledger_sha256"],
        "ledger_sha256": "f" * 64,
        "map_review_complete": True,
        "pending_count": 0,
        "decisions": [
            {
                "decision": decision,
                "map_decision_sha256": reviewed_city_map._digest(decision),
            }
        ],
    }
    map_core = {
        key: map_ledger.get(key)
        for key in (
            "schema_version",
            "city",
            "inventory_digest",
            "geometry_ledger_sha256",
            "decisions",
        )
    }
    map_ledger["ledger_sha256"] = reviewed_city_map._digest(map_core)
    return sources, inventory, geometry, map_ledger


def _write_poi_product(root, catalog_path):
    source_hash = "9" * 64
    poi = {
        "type": "Feature",
        "geometry": mapping(Point(6.77, 51.23)),
        "properties": {
            "id": "osm/node/1",
            "name": "Nordmarkt",
            "kind": "park",
            "geometry_mode": "footprint_missing",
            "center": [6.77, 51.23],
        },
    }
    boundary = {
        "id": "osm/relation/1",
        "source_pbf_sha256": source_hash,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[6.6, 51.1], [6.9, 51.1], [6.9, 51.4], [6.6, 51.4], [6.6, 51.1]]],
        },
    }
    values = {
        "poi-contract.json": {
            "schema_version": 2,
            "city": "dusseldorf",
            "status": "local_poi_only_unpublished",
            "epsg": 25832,
            "poi_count": 1,
            "source_pbf_sha256": source_hash,
            "boundary_source_id": "osm/relation/1",
            "catalog_sha256": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
            "tile_size": [0.04, 0.025],
            "tile_index": {"pois": ["park/1_1"]},
        },
        "validation.json": {
            "passed": True,
            "errors": [],
            "poi_count": 1,
            "epsg": 25832,
            "source_sha256": source_hash,
            "boundary_source_id": "osm/relation/1",
        },
        "boundary.geojson": boundary,
        "poi-index.json": {"type": "FeatureCollection", "features": [poi]},
        "search.json": [],
    }
    for name, value in values.items():
        (root / name).write_text(json.dumps(value), encoding="utf-8")
    tile = root / "pois" / "park" / "1_1.json"
    tile.parent.mkdir(parents=True)
    tile.write_text(
        json.dumps({"type": "FeatureCollection", "features": [poi]}),
        encoding="utf-8",
    )


def test_prepare_events_keeps_all_scenes_but_counts_only_explicit_primary():
    sources, inventory, geometry, map_ledger = _inputs()
    events, audit, latest = reviewed_city_map._prepare_events(
        city="dusseldorf",
        source_rows=sources,
        inventory=inventory,
        geometry_ledger=geometry,
        map_ledger=map_ledger,
    )
    assert latest.isoformat() == "2026-09-29T12:00:00+02:00"
    assert audit["formal_locations"] == 2
    assert audit["resolved_display_geometries"] == 2
    assert audit["primary_count_points"] == 1
    event = events[0]
    assert event["coordinates"] == [6.77, 51.23]
    assert event["event_date"] is None
    assert event["time_basis"] == "event_time_unknown_publication_month_filter"
    assert [scene["primary_for_count"] for scene in event["scene_locations"]] == [True, False]
    assert event["scene_locations"][1]["geometry"]["type"] == "LineString"


def test_publication_month_filter_keeps_original_event_date_and_phase_details():
    sources, inventory, geometry, map_ledger = _inputs()
    incident = inventory["articles"][0]["incidents"][0]
    incident["event_time"] = {"display": "30.01.2023", "date": "2023-01-30"}
    incident["details"] = "Previously reviewed details"
    events, _, _ = reviewed_city_map._prepare_events(
        city="dusseldorf", source_rows=sources, inventory=inventory,
        geometry_ledger=geometry, map_ledger=map_ledger, month_basis="publication_month",
    )
    assert events[0]["event_date"] == "2023-01-30"
    assert events[0]["month"] == "2026-09"
    assert events[0]["source_incidents"] == [incident]


@pytest.mark.parametrize("clock", ["2026-03-29T02:30:00", "2026-10-25T02:30:00"])
def test_explicit_publication_timezone_rejects_nonexistent_or_ambiguous_clocks(clock):
    with pytest.raises(ValueError, match="ambiguous or nonexistent"):
        reviewed_city_map._published(clock, timezone_name="Europe/Berlin")


def test_display_reference_keeps_native_point_geometry_without_a_generated_count_point():
    _, inventory, geometry, _ = _inputs()
    row = geometry["decisions"][0]
    row["derived_geometry"]["geometry_usage"] = "source_junction_reference_only"
    location = inventory["articles"][0]["formal_locations"][0]
    scene = reviewed_city_map._scene(location, row, {}, {}, None)
    assert scene["coordinates"] is None
    assert scene["geometry"]["type"] == "Point"
    assert scene["primary_for_count"] is False
    with pytest.raises(ValueError, match="cannot be a primary"):
        reviewed_city_map._scene(location, row, {}, {}, location["location_id"])


def test_prepare_events_uses_reviewed_original_incident_date_instead_of_publication_date():
    sources, inventory, geometry, map_ledger = _inputs()
    inventory["articles"][0]["incidents"][0]["event_time"] = {
        "display": "30. Januar 2023 gegen 16:10 Uhr",
        "date": "2023-01-30",
        "precision": "approximate",
        "evidence_quote": "Am Nordmarkt wurde ein Mann beraubt.",
    }
    events, _, _ = reviewed_city_map._prepare_events(
        city="dusseldorf",
        source_rows=sources,
        inventory=inventory,
        geometry_ledger=geometry,
        map_ledger=map_ledger,
    )
    event = events[0]
    assert (event["event_date"], event["month"], event["time_basis"]) == (
        "2023-01-30", "2023-01", "reviewed_incident_time",
    )
    assert event["scene_locations"][0]["incidents"][0]["event_time"]["display"] == (
        "30. Januar 2023 gegen 16:10 Uhr"
    )


def test_prepare_events_rejects_a_stale_or_incomplete_map_ledger():
    sources, inventory, geometry, map_ledger = _inputs()
    map_ledger["map_review_complete"] = False
    with pytest.raises(ValueError, match="stale or incomplete"):
        reviewed_city_map._prepare_events(
            city="dusseldorf",
            source_rows=sources,
            inventory=inventory,
            geometry_ledger=geometry,
            map_ledger=map_ledger,
        )


def test_prepare_events_rejects_tampered_map_ledger():
    sources, inventory, geometry, map_ledger = _inputs()
    map_ledger["decisions"][0]["decision"]["article_category"] = "gewalt"
    with pytest.raises(ValueError, match="Map decision ledger digest"):
        reviewed_city_map._prepare_events(
            city="dusseldorf",
            source_rows=sources,
            inventory=inventory,
            geometry_ledger=geometry,
            map_ledger=map_ledger,
        )


def test_build_candidate_is_browser_shaped_and_remains_unapproved(tmp_path, monkeypatch):
    sources, inventory, geometry, map_ledger = _inputs()
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"poi_types": {}}), encoding="utf-8")
    poi_root = tmp_path / "poi"
    poi_root.mkdir()
    _write_poi_product(poi_root, catalog)
    paths = {}
    for name, value in {
        "inventory": inventory,
        "geometry": geometry,
        "map": map_ledger,
    }.items():
        paths[name] = tmp_path / f"{name}.json"
        paths[name].write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(
        reviewed_city_map,
        "read_checkpoint",
        lambda _path: (
            sources,
            {
                "discovered": 1,
                "bodies_in_pack": 1,
                "missing_bodies": 0,
                "source_errors": 0,
                "channel_scan_complete": True,
            },
        ),
    )
    output = tmp_path / "candidate"
    audit = reviewed_city_map.build_candidate(
        city="dusseldorf",
        source_db=tmp_path / "unused.sqlite",
        inventory_path=paths["inventory"],
        geometry_ledger_path=paths["geometry"],
        map_ledger_path=paths["map"],
        poi_root=poi_root,
        catalog_path=catalog,
        output=output,
    )
    manifest = json.loads((output / "manifest.json").read_text())
    month = json.loads((output / manifest["generation"] / "months" / "2026-09.json").read_text())
    assert audit["primary_count_points"] == 1
    assert sum(feature["properties"]["count"] for feature in month["hex"]["detail"]["features"]) == 1
    assert len(month["events"][0]["scene_locations"]) == 2
    assert month["links"] == []
    assert manifest["owner_approved"] is False
    assert manifest["publication_ready"] is False
    assert manifest["metadata"]["excluded_scope_counts"] == {}
