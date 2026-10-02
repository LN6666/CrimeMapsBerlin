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


def test_scene_preserves_location_time_and_details_without_incident():
    location = {
        "location_id": "1:location:2", "label": "discovery sidewalk", "role": "discovery",
        "precision": "street", "city_scope": "in_city", "evidence_quotes": ["Found later on the sidewalk."],
        "event_time": {"display": "later discovery, original time unknown", "date": None,
                       "precision": "unknown", "evidence_quote": "Found later on the sidewalk."},
        "details": "Discovery only, not the assault location.",
    }
    scene = reviewed_city_map._scene(location, None, {}, {}, None)
    assert scene["event_time"] == location["event_time"]
    assert scene["details"] == location["details"]
    assert scene["incidents"] == []
    assert scene["primary_for_count"] is False


@pytest.mark.parametrize("reserved", ["reviewed_object_ids", "native_identity_review",
                                      "reviewed_street_poi_ids", "native_street_review"])
def test_source_inventory_cannot_inject_native_identity_without_its_separate_ledger(reserved):
    location = {"poi_contexts": [{reserved: ["osm/node/1"]}]}
    with pytest.raises(ValueError, match="separately validated identity ledger"):
        reviewed_city_map._scene(location, None, {}, {}, None)


def test_scene_preserves_geometry_fallback_note_and_unresolved_verdict():
    location = {
        "location_id": "1:location:1", "label": "unnamed flat on named road",
        "role": "incident", "precision": "place", "city_scope": "in_city",
        "evidence_quotes": ["In einer Wohnung an der Straße."],
    }
    geometry_row = {
        "decision": {"verdict": "resolved", "method": "osm_line",
                     "review_note": "Road reference only; exact building and flat unknown."},
        "derived_geometry": {"type": "LineString",
                             "geometry": mapping(LineString([(13.4, 52.5), (13.41, 52.51)]))},
    }
    scene = reviewed_city_map._scene(location, geometry_row, {}, {}, None)
    assert scene["geometry_review"] == geometry_row["decision"]
    assert scene["coordinates"] is None
    assert scene["primary_for_count"] is False
    geometry_row["decision"].update(verdict="unresolved", method="none",
                                    review_note="The source and checked OSM do not identify the place.")
    geometry_row["derived_geometry"] = None
    unresolved = reviewed_city_map._scene(location, geometry_row, {}, {}, None)
    assert unresolved["geometry_review"] == geometry_row["decision"]
    assert unresolved["geometry"] is None
    assert unresolved["coordinates"] is None


def _geometry_digest(geometry):
    core = {key: geometry.get(key) for key in GEOMETRY_CORE_KEYS}
    return hashlib.sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_scene_preserves_source_road_only_transit_geometry_without_full_line_claim():
    location = {
        "location_id": "1:location:1", "label": "moving bus on source road",
        "role": "incident", "precision": "route", "city_scope": "in_city",
        "evidence_quotes": ["A bus drove along the road."],
        "transit_route": {"mode": "bus", "line": "unknown", "extent": "source_segment"},
    }
    geometry_row = {
        "decision": {"verdict": "resolved", "method": "osm_transit_road_reference",
                     "review_note": "Road reference only; line and precise segment unknown."},
        "derived_geometry": {"type": "LineString", "geometry_usage": "source_road_reference_only",
                             "complete_transit_line": False,
                             "geometry": mapping(LineString([(13.4, 52.5), (13.41, 52.51)]))},
    }
    scene = reviewed_city_map._scene(location, geometry_row, {}, {}, None)
    assert scene["geometry_usage"] == "source_road_reference_only"
    assert scene["complete_transit_line"] is False
    assert scene["transit_route"] == location["transit_route"]
    assert scene["coordinates"] is None
    assert scene["primary_for_count"] is False


@pytest.mark.parametrize("usage,extra", [
    ("source_road_reference_only", {"source_road_extent": "native_endpoint_bounded"}),
    ("carrier_line_reference_only", {"actual_transit_extent_known": False}),
    ("source_footprint_reference_only", {}),
    ("source_footprint_reference_only", {"actual_non_transit_extent_known": False}),
    ("source_transit_corridor_reference_only", {"service_identity_known": False}),
])
def test_scene_preserves_reference_uncertainty_without_promoting_it_to_count(usage, extra):
    location = {"location_id": "1:location:1", "label": "source reference", "role": "operation",
                "precision": "route", "city_scope": "in_city", "evidence_quotes": ["Source reference."]}
    derived = {"type": "LineString", "geometry_usage": usage, **extra,
               "geometry": mapping(LineString([(13.4, 52.5), (13.41, 52.51)]))}
    row = {"decision": {"verdict": "resolved", "method": "reference", "review_note": "Actual position unknown."},
           "derived_geometry": derived}
    scene = reviewed_city_map._scene(location, row, {}, {}, None)
    assert scene["geometry_usage"] == usage
    for key, value in extra.items():
        assert scene[key] == value
    assert scene["coordinates"] is None and scene["primary_for_count"] is False
    if usage != "source_footprint_reference_only":
        assert scene["complete_transit_line"] is False


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


def test_prepare_events_retains_uncertain_frozen_berlin_scopes_without_geometry_or_count():
    from crimemapsberlin.berlin_semantic_review import SIX_RULE_KEYS
    from crimemapsberlin.map_decisions import compile_map_decisions

    sources, inventory, geometry, old_map = _inputs()
    inventory["city"] = geometry["city"] = "berlin"
    inventory["semantic_review_decision_set_sha256"] = "a" * 64
    inventory["coverage"] = {"scope": "frozen_owner_batch_not_full_crime_inventory"}
    article = inventory["articles"][0]
    article.update(
        scope_verdict="uncertain", scope_basis="explicit_reviewed_location_scopes_only",
        audit={"six_rule_checks": {key: True for key in SIX_RULE_KEYS}},
    )
    for location in article["formal_locations"]:
        location["city_scope"] = "uncertain"
    geometry.update(decisions=[], request_count=0)
    geometry["ledger_sha256"] = _geometry_digest(geometry)
    decision = old_map["decisions"][0]["decision"]
    decision.update(city="berlin", primary_count_incident_id=None, primary_count_location_id=None)
    ledger = compile_map_decisions(
        city="berlin", source_rows=sources, inventory=inventory, geometry_ledger=geometry,
        decision_envelope={
            "schema_version": 1, "city": "berlin", "inventory_digest": inventory["inventory_digest"],
            "geometry_ledger_sha256": geometry["ledger_sha256"], "decisions": [decision],
        },
    )
    events, audit, _ = reviewed_city_map._prepare_events(
        city="berlin", source_rows=sources, inventory=inventory,
        geometry_ledger=geometry, map_ledger=ledger,
    )
    assert len(events) == 1
    assert events[0]["source_scope_verdict"] == "uncertain"
    assert events[0]["source_status"] == (
        "frozen_owner_batch_decision_coverage_verified_not_full_acceptance"
    )
    assert events[0]["coordinates"] is None
    assert len(events[0]["scene_locations"]) == 2
    assert all(scene["geometry"] is None for scene in events[0]["scene_locations"])
    assert all(scene["location_scope"] == "uncertain" for scene in events[0]["scene_locations"])
    assert audit["retained_uncertain_scope_articles"] == 1
    assert audit["primary_count_points"] == 0


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
    assert month["events"][0]["source_status"] == (
        "source_geometry_map_decision_coverage_verified_not_full_acceptance"
    )
    assert manifest["metadata"]["review_status"] == (
        "DECISION_COVERAGE_VERIFIED_INDEPENDENT_ACCEPTANCE_REQUIRED"
    )
    assert manifest["metadata"]["independent_technical_acceptance"] == "not_established_by_this_builder"
    assert manifest["metadata"]["decision_coverage_does_not_imply_precise_geometry"] is True
    assert manifest["metadata"]["unresolved_display_locations"] == audit["unresolved_display_locations"]
    assert manifest["metadata"]["time_basis"] == (
        "reviewed_incident_time_or_explicit_publication_month_fallback"
    )
    assert manifest["publication_blocks"] == [
        "independent_full_technical_acceptance_not_established_by_builder",
        "owner_map_inspection_and_approval_missing",
    ]
    # Same source batch, new candidate format: do not reuse a stale browser generation.
    initial_generation = manifest["generation"]
    monkeypatch.setattr(reviewed_city_map, "CANDIDATE_FORMAT_VERSION", 3)
    changed = reviewed_city_map.build_candidate(
        city="dusseldorf", source_db=tmp_path / "unused.sqlite",
        inventory_path=paths["inventory"], geometry_ledger_path=paths["geometry"],
        map_ledger_path=paths["map"], poi_root=poi_root, catalog_path=catalog,
        output=tmp_path / "changed-format-candidate",
    )
    assert changed["generation"] != initial_generation
    assert manifest["metadata"]["poi_context_compatibility_sha256"]
    monkeypatch.setattr(reviewed_city_map, "context_compatibility_digest", lambda: "different-matching-policy")
    matching_output = tmp_path / "changed-matching-policy"
    reviewed_city_map.build_candidate(
        city="dusseldorf", source_db=tmp_path / "unused.sqlite",
        inventory_path=paths["inventory"], geometry_ledger_path=paths["geometry"],
        map_ledger_path=paths["map"], poi_root=poi_root,
        catalog_path=catalog, output=matching_output,
    )
    matching_manifest = json.loads((matching_output / "manifest.json").read_text())
    assert matching_manifest["generation"] != changed["generation"]

    from crimemapsberlin.poi_context_identities import identity_digest

    context = {"kind": "park", "scope": "named_object", "radius_m": 0,
               "evidence_quote": sources[0]["source_body"].split(" Die Festnahme")[0]}
    inventory["articles"][0]["formal_locations"][0]["poi_contexts"] = [context]
    paths["inventory"].write_text(json.dumps(inventory), encoding="utf-8")
    native = json.loads((poi_root / "poi-index.json").read_text())["features"][0]
    identities = {"schema_version": 1, "city": "dusseldorf", "inventory_digest": inventory["inventory_digest"],
                  "poi_contract_sha256": hashlib.sha256((poi_root / "poi-contract.json").read_bytes()).hexdigest(),
                  "decisions": [{"context_id": "source-1:location:1:poi:1", "source_id": "source-1",
                                 "source_url": sources[0]["source_url"], "source_sha256": sources[0]["source_sha256"],
                                 "context_sha256": identity_digest(context), "native_object_id": native["properties"]["id"],
                                 "poi_feature_sha256": identity_digest(native),
                                 "identity_evidence_quotes": [context["evidence_quote"]],
                                 "review_note": "Synthetic explicitly reviewed named park; no inferred incident coordinate."}]}
    identities["ledger_sha256"] = identity_digest(identities)
    identity_path = tmp_path / "identities.json"
    identity_path.write_text(json.dumps(identities), encoding="utf-8")
    kwargs = {"city": "dusseldorf", "source_db": tmp_path / "unused.sqlite", "inventory_path": paths["inventory"],
              "geometry_ledger_path": paths["geometry"], "map_ledger_path": paths["map"],
              "poi_root": poi_root, "catalog_path": catalog}
    without = reviewed_city_map.build_candidate(**kwargs, output=tmp_path / "without-identities")
    identity_output = tmp_path / "with-identities"
    with_identity = reviewed_city_map.build_candidate(**kwargs, output=identity_output,
                                                    poi_context_identities_path=identity_path)
    assert with_identity["generation"] != without["generation"]
    assert with_identity["named_poi_identity_review"]["decisions"] == 1
    identity_month = json.loads((identity_output / with_identity["generation"] / "months/2026-09.json").read_text())
    assert identity_month["links"][0]["mention_basis"] == "source_reviewed_context_only"
    assert identity_month["events"][0]["scene_locations"][0]["primary_for_count"] is True
    identity_manifest = json.loads((identity_output / "manifest.json").read_text())
    assert identity_manifest["owner_approved"] is identity_manifest["publication_ready"] is False
    identities["decisions"][0]["review_note"] += " Revised explicit identity review."
    identities["ledger_sha256"] = identity_digest({k: v for k, v in identities.items() if k != "ledger_sha256"})
    identity_path.write_text(json.dumps(identities), encoding="utf-8")
    revised = reviewed_city_map.build_candidate(**kwargs, output=tmp_path / "revised-identities",
                                               poi_context_identities_path=identity_path)
    assert revised["generation"] != with_identity["generation"]

    # A neutral native named area may share a tile with protected native POIs.
    # Its source-bound identity is separate from arrest/incident geometry.
    from shapely.geometry import Polygon

    ref_context = {"kind": "institution", "scope": "named_object", "radius_m": 0,
                   "evidence_quote": "Die Festnahme erfolgte am Hauptbahnhof."}
    inventory["articles"][0]["formal_locations"][1]["poi_contexts"] = [ref_context]
    paths["inventory"].write_text(json.dumps(inventory), encoding="utf-8")
    geometry["geometry_index_sha256"] = "i" * 64
    geometry["ledger_sha256"] = _geometry_digest(geometry)
    paths["geometry"].write_text(json.dumps(geometry), encoding="utf-8")
    map_ledger["geometry_ledger_sha256"] = geometry["ledger_sha256"]
    map_ledger["ledger_sha256"] = reviewed_city_map._digest({k: map_ledger.get(k) for k in
        ("schema_version", "city", "inventory_digest", "geometry_ledger_sha256", "decisions")})
    paths["map"].write_text(json.dumps(map_ledger), encoding="utf-8")
    catalog.write_text(json.dumps({"poi_types": {"context": {"color": "#555555", "label": "Neutral reference"}}}))
    contract_path = poi_root / "poi-contract.json"
    contract = json.loads(contract_path.read_text())
    contract.update(catalog_sha256=hashlib.sha256(catalog.read_bytes()).hexdigest(), poi_count=2,
                    tile_index={"pois": ["context/169_2049", "park/1_1"]})
    contract_path.write_text(json.dumps(contract))
    validation_path = poi_root / "validation.json"
    validation = json.loads(validation_path.read_text())
    validation["poi_count"] = 2
    validation_path.write_text(json.dumps(validation))
    existing_neutral = {"type": "Feature", "geometry": mapping(Point(6.773, 51.231)),
                        "properties": {"id": "osm/node/22", "name": "Existing native bench", "aliases": [],
                                       "kind": "context", "center": [6.773, 51.231], "geometry_mode": "footprint_missing"}}
    base_index = json.loads((poi_root / "poi-index.json").read_text())
    base_index["features"].append(existing_neutral)
    (poi_root / "poi-index.json").write_text(json.dumps(base_index))
    base_tile = poi_root / "pois/context/169_2049.json"
    base_tile.parent.mkdir(parents=True)
    base_tile.write_text(json.dumps({"type": "FeatureCollection", "features": [existing_neutral]}))
    base_tile_sha = hashlib.sha256(base_tile.read_bytes()).hexdigest()
    ref_geometry = mapping(Polygon([(6.77, 51.23), (6.774, 51.23), (6.774, 51.234), (6.77, 51.23)]))
    obj = {"id": "osm/way/99", "source_url": "https://www.openstreetmap.org/way/99", "roles": ["named_object"],
           "names": ["Hauptbahnhof reference"], "tags": {"name": "Hauptbahnhof reference"},
           "geometry": ref_geometry, "geometry_sha256": identity_digest(ref_geometry)}
    index_path = tmp_path / "reference-index.json"
    index_path.write_text(json.dumps({"objects": [obj]}, separators=(",", ":")))
    proof_path = tmp_path / "reference-index-proof.json"
    proof_path.write_text(json.dumps({"index_path": str(index_path), "index_sha256": "i" * 64,
        "index_file_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(), "source_pbf_sha256": "9" * 64,
        "readback_validation": {"passed": True, "errors": []}}))
    contract_sha = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    selections = {"schema_version": 1, "city": "dusseldorf", "inventory_digest": inventory["inventory_digest"],
        "poi_contract_sha256": contract_sha, "geometry_index_sha256": "i" * 64,
        "geometry_index_path": str(index_path), "index_proof_path": str(proof_path),
        "decisions": [{"context_id": "source-1:location:2:poi:1", "source_id": "source-1",
            "source_url": sources[0]["source_url"], "source_sha256": sources[0]["source_sha256"],
            "context_sha256": identity_digest(ref_context), "native_object_id": obj["id"],
            "native_object_sha256": identity_digest(obj), "identity_evidence_quotes": [ref_context["evidence_quote"]],
            "review_note": "Source-named native area only; exact arrest position and native venue subtype are not inferred."}]}
    selections["ledger_sha256"] = identity_digest(selections)
    selection_path = tmp_path / "reference-selections.json"
    selection_path.write_text(json.dumps(selections))
    identities["poi_contract_sha256"] = contract_sha
    identities["ledger_sha256"] = identity_digest({k: v for k, v in identities.items() if k != "ledger_sha256"})
    identity_path.write_text(json.dumps(identities))
    output = tmp_path / "native-reference-candidate"
    result = reviewed_city_map.build_candidate(**kwargs, output=output, poi_context_identities_path=identity_path,
                                               poi_reference_selections_path=selection_path)
    assert result["poi_count"] == 3 and result["source_selected_native_reference_count"] == 1
    assert result["primary_count_points"] == 1 and result["named_poi_identity_review"]["decisions"] == 2
    generated = output / result["generation"]
    tile = json.loads((generated / "pois/context/169_2049.json").read_text())
    assert {f["properties"]["id"] for f in tile["features"]} == {"osm/node/22", "osm/way/99"}
    assert hashlib.sha256(base_tile.read_bytes()).hexdigest() == base_tile_sha
    month = json.loads((generated / "months/2026-09.json").read_text())
    assert {r["poi_id"] for r in month["links"]} == {"osm/node/1", "osm/way/99"}
    assert month["events"][0]["scene_locations"][1]["role"] == "arrest"
    assert month["events"][0]["scene_locations"][1]["geometry"]["type"] == "LineString"
    assert month["events"][0]["scene_locations"][1]["primary_for_count"] is False
    before_files = {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()}
    again = reviewed_city_map.build_candidate(**kwargs, output=output, poi_context_identities_path=identity_path,
                                               poi_reference_selections_path=selection_path)
    assert again == result
    assert {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()} == before_files
    # Retained literal metadata is independently bound to the same validated
    # native selection; merging reference and metadata tiles preserves base.
    raw = tmp_path / "raw-native-metadata.json"
    raw_element = {"type": "node", "id": 22, "tags": {"memorial": "bench"}}
    raw.write_text(json.dumps({"elements": [raw_element]}, separators=(",", ":")))
    raw_sha = hashlib.sha256(raw.read_bytes()).hexdigest()
    metadata_proof = tmp_path / "metadata-product-proof.json"
    metadata_proof.write_text(json.dumps({"product_path": str(poi_root), "raw_native_selection_path": str(raw),
        "source_pbf_sha256": "9" * 64, "raw_native_selection_sha256": raw_sha,
        "product_file_hashes": {str(contract_path): contract_sha}, "validation": {"passed": True, "errors": []}}))
    metadata_ledger = {"schema_version": 1, "city": "dusseldorf", "poi_contract_sha256": contract_sha,
        "product_proof_path": str(metadata_proof),
        "product_proof_sha256": hashlib.sha256(metadata_proof.read_bytes()).hexdigest(),
        "raw_checkpoint_path": str(raw), "raw_checkpoint_sha256": raw_sha, "source_pbf_sha256": "9" * 64,
        "decisions": [{"poi_id": "osm/node/22", "native_object_id": "osm/node/22",
                       "poi_feature_sha256": identity_digest(existing_neutral),
                       "native_element_sha256": identity_digest(raw_element), "tags": {"memorial": "bench"}}]}
    metadata_ledger["ledger_sha256"] = identity_digest(metadata_ledger)
    metadata_path = tmp_path / "native-metadata.json"
    metadata_path.write_text(json.dumps(metadata_ledger))
    with_metadata = reviewed_city_map.build_candidate(**kwargs, output=output,
        poi_context_identities_path=identity_path, poi_reference_selections_path=selection_path,
        poi_native_metadata_path=metadata_path)
    assert with_metadata["generation"] != result["generation"]
    assert with_metadata["native_context_metadata_review"]["native_pois"] == 1
    assert with_metadata["primary_count_points"] == result["primary_count_points"]
    generated = output / with_metadata["generation"]
    changed_tile = json.loads((generated / "pois/context/169_2049.json").read_text())
    assert {f["properties"]["id"] for f in changed_tile["features"]} == {"osm/node/22", "osm/way/99"}
    updated = next(f for f in changed_tile["features"] if f["properties"]["id"] == "osm/node/22")
    assert updated["properties"]["native_context_metadata"]["tags"] == {"memorial": "bench"}
    assert hashlib.sha256(base_tile.read_bytes()).hexdigest() == base_tile_sha
    changed_month = json.loads((generated / "months/2026-09.json").read_text())
    assert changed_month == month
    metadata_files = {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()}
    repeated = reviewed_city_map.build_candidate(**kwargs, output=output,
        poi_context_identities_path=identity_path, poi_reference_selections_path=selection_path,
        poi_native_metadata_path=metadata_path)
    assert repeated == with_metadata
    assert {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*") if p.is_file()} == metadata_files
    base_index["features"][1]["properties"]["native_context_metadata"] = {"tags": {"memorial": "bench"}}
    (poi_root / "poi-index.json").write_text(json.dumps(base_index))
    with pytest.raises(ValueError, match="separately validated ledger"):
        reviewed_city_map.build_candidate(**kwargs, output=output)


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
