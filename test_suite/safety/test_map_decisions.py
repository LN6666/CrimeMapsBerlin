import copy
import hashlib
import json

import pytest
from shapely.geometry import Point, mapping

from crimemapsberlin.map_decisions import build_review_pack, compile_map_decisions

BODY = "Am Nordmarkt wurde ein Mann beraubt. Die Festnahme erfolgte am Hauptbahnhof."
GEOMETRY_CORE_KEYS = (
    "schema_version",
    "city",
    "inventory_digest",
    "submitted_inventory_digest",
    "geometry_index_sha256",
    "decisions",
)


def _rehash_geometry(geometry):
    core = {key: geometry.get(key) for key in GEOMETRY_CORE_KEYS}
    geometry["ledger_sha256"] = hashlib.sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _source_rows():
    return [
        {
            "source_id": "source-1",
            "source_url": "https://example.invalid/source-1",
            "title": "Raub am Nordmarkt",
            "published": "2026-09-29T12:00:00+02:00",
            "source_body": BODY,
            "source_sha256": hashlib.sha256(BODY.encode()).hexdigest(),
            "revision": 1,
            "review_status": "pending",
        }
    ]


def _inputs():
    source = _source_rows()[0]
    incident = {
        "incident_id": "source-1:incident:1",
        "evidence_quotes": ["Am Nordmarkt wurde ein Mann beraubt."],
        "formal_location_ids": ["source-1:location:1"],
    }
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
                "source_url": source["source_url"],
                "source_sha256": source["source_sha256"],
                "decision_sha256": "b" * 64,
                "scope_verdict": "in_city",
                "incident_count": 1,
                "incidents": [incident],
                "formal_locations": locations,
            }
        ],
        "geometry_requests": [],
    }
    request = {
        "source_id": "source-1",
        "source_sha256": source["source_sha256"],
        "decision_sha256": "b" * 64,
        "location_id": "source-1:location:1",
        "role": "incident",
        "precision": "place",
        "city_scope": "in_city",
    }
    geometry = {
        "schema_version": 1,
        "city": "dusseldorf",
        "inventory_digest": inventory["inventory_digest"],
        "ledger_sha256": "c" * 64,
        "geometry_review_complete": True,
        "pending_count": 0,
        "request_count": 1,
        "decisions": [
            {
                "request": request,
                "decision": {
                    "verdict": "resolved",
                    "method": "osm_point",
                    "review_note": "The source explicitly names this checked place.",
                },
                "derived_geometry": {
                    "type": "Point",
                    "geometry": mapping(Point(6.77, 51.23)),
                },
            }
        ],
    }
    _rehash_geometry(geometry)
    decision = {
        "schema_version": 1,
        "city": "dusseldorf",
        "source_id": "source-1",
        "source_sha256": source["source_sha256"],
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
        "review_note": "The robbery incident has one checked incident point.",
        "reviewer": "test-reviewer",
        "reviewed_at": "2026-09-29T13:00:00+02:00",
    }
    envelope = {
        "schema_version": 1,
        "city": "dusseldorf",
        "inventory_digest": inventory["inventory_digest"],
        "geometry_ledger_sha256": geometry["ledger_sha256"],
        "decisions": [decision],
    }
    return _source_rows(), inventory, geometry, envelope


def test_compile_map_decisions_uses_only_explicit_llm_category_and_primary():
    sources, inventory, geometry, envelope = _inputs()
    result = compile_map_decisions(
        city="dusseldorf",
        source_rows=sources,
        inventory=inventory,
        geometry_ledger=geometry,
        decision_envelope=envelope,
    )
    assert result["map_review_complete"] is True
    assert result["category_counts"] == {"raub": 1}
    assert result["incident_category_counts"] == {"raub": 1}
    assert result["primary_count"] == 1
    assert result["publication_ready"] is False
    assert result["decisions"][0]["decision"]["primary_count_location_id"] == ("source-1:location:1")


def test_compile_map_decisions_rejects_nonincident_or_nonpoint_primary():
    sources, inventory, geometry, envelope = _inputs()
    wrong_role = copy.deepcopy(envelope)
    wrong_role["decisions"][0]["primary_count_location_id"] = "source-1:location:2"
    with pytest.raises(ValueError, match="non-countable"):
        compile_map_decisions(
            city="dusseldorf",
            source_rows=sources,
            inventory=inventory,
            geometry_ledger=geometry,
            decision_envelope=wrong_role,
        )
    no_point = copy.deepcopy(geometry)
    no_point["decisions"][0]["derived_geometry"] = {
        "type": "LineString",
        "geometry": {"type": "LineString", "coordinates": [[6.7, 51.2], [6.8, 51.3]]},
    }
    _rehash_geometry(no_point)
    no_point_envelope = copy.deepcopy(envelope)
    no_point_envelope["geometry_ledger_sha256"] = no_point["ledger_sha256"]
    with pytest.raises(ValueError, match="non-countable"):
        compile_map_decisions(
            city="dusseldorf",
            source_rows=sources,
            inventory=inventory,
            geometry_ledger=no_point,
            decision_envelope=no_point_envelope,
        )


def test_compile_map_decisions_requires_every_incident_and_current_evidence():
    sources, inventory, geometry, envelope = _inputs()
    missing = copy.deepcopy(envelope)
    missing["decisions"][0]["incident_categories"] = []
    with pytest.raises(ValueError, match="every reviewed incident"):
        compile_map_decisions(
            city="dusseldorf",
            source_rows=sources,
            inventory=inventory,
            geometry_ledger=geometry,
            decision_envelope=missing,
        )
    absent = copy.deepcopy(envelope)
    absent["decisions"][0]["classification_evidence_quotes"] = [
        "This evidence does not occur in the official source."
    ]
    with pytest.raises(ValueError, match="absent"):
        compile_map_decisions(
            city="dusseldorf",
            source_rows=sources,
            inventory=inventory,
            geometry_ledger=geometry,
            decision_envelope=absent,
        )


def test_compile_map_decisions_rejects_tampered_geometry_ledger():
    sources, inventory, geometry, envelope = _inputs()
    geometry["decisions"][0]["derived_geometry"]["geometry"]["coordinates"] = [6.8, 51.3]
    with pytest.raises(ValueError, match="Geometry ledger digest"):
        compile_map_decisions(
            city="dusseldorf",
            source_rows=sources,
            inventory=inventory,
            geometry_ledger=geometry,
            decision_envelope=envelope,
        )


def test_review_pack_excludes_nonmappable_scope_and_never_selects_semantics(monkeypatch):
    sources, inventory, geometry, _ = _inputs()
    excluded = copy.deepcopy(inventory["articles"][0])
    excluded["source_id"] = "outside"
    excluded["scope_verdict"] = "out_of_city"
    inventory["articles"].append(excluded)
    monkeypatch.setattr(
        "crimemapsberlin.map_decisions.read_checkpoint",
        lambda _path: (sources, {"discovered": 2, "bodies_in_pack": 1}),
    )
    result = build_review_pack(
        city="dusseldorf",
        source_db=None,
        inventory=inventory,
        geometry_ledger=geometry,
    )
    assert result["mappable_articles"] == 1
    assert result["excluded_scope_counts"] == {"out_of_city": 1}
    article = result["articles"][0]
    assert "article_category" not in article
    assert article["formal_locations"][0]["count_point_available"] is True
    assert article["formal_locations"][0]["count_point_basis"] == "selected_osm_point"
    assert article["formal_locations"][0]["geometry_review_note"] == (
        "The source explicitly names this checked place."
    )
