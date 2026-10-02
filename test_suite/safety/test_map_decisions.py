import copy
import hashlib
import json

import pytest
from shapely.geometry import Point, mapping

from crimemapsberlin.map_decisions import build_review_pack, compile_map_decisions, displayable_article

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


def test_compile_map_decisions_counts_identical_articles_only_once():
    sources, inventory, geometry, envelope = _inputs()
    second = copy.deepcopy(sources[0])
    second["source_id"] = "source-2"
    second["source_url"] = "https://example.invalid/source-2"
    sources.append(second)

    article = copy.deepcopy(inventory["articles"][0])
    article["source_id"] = second["source_id"]
    article["source_url"] = second["source_url"]
    for incident in article["incidents"]:
        incident["incident_id"] = incident["incident_id"].replace("source-1", "source-2")
        incident["formal_location_ids"] = [
            value.replace("source-1", "source-2") for value in incident["formal_location_ids"]
        ]
    for location in article["formal_locations"]:
        location["location_id"] = location["location_id"].replace("source-1", "source-2")
    inventory["articles"].append(article)

    geometry_row = copy.deepcopy(geometry["decisions"][0])
    geometry_row["request"]["source_id"] = "source-2"
    geometry_row["request"]["location_id"] = "source-2:location:1"
    geometry["decisions"].append(geometry_row)
    geometry["request_count"] = 2
    _rehash_geometry(geometry)

    decision = copy.deepcopy(envelope["decisions"][0])
    decision["source_id"] = "source-2"
    decision["primary_count_incident_id"] = "source-2:incident:1"
    decision["primary_count_location_id"] = "source-2:location:1"
    decision["incident_categories"][0]["incident_id"] = "source-2:incident:1"
    envelope["decisions"].append(decision)
    envelope["geometry_ledger_sha256"] = geometry["ledger_sha256"]

    with pytest.raises(ValueError, match="identical source articles twice"):
        compile_map_decisions(
            city="dusseldorf",
            source_rows=sources,
            inventory=inventory,
            geometry_ledger=geometry,
            decision_envelope=envelope,
        )

    decision["primary_count_incident_id"] = None
    decision["primary_count_location_id"] = None
    result = compile_map_decisions(
        city="dusseldorf",
        source_rows=sources,
        inventory=inventory,
        geometry_ledger=geometry,
        decision_envelope=envelope,
    )
    assert result["primary_count"] == 1


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


def _unlocated_berlin_inputs():
    from crimemapsberlin.berlin_semantic_review import SIX_RULE_KEYS

    sources, inventory, geometry, envelope = _inputs()
    for row in (inventory, geometry, envelope, envelope["decisions"][0]):
        row["city"] = "berlin"
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
    _rehash_geometry(geometry)
    envelope["geometry_ledger_sha256"] = geometry["ledger_sha256"]
    envelope["decisions"][0].update(
        primary_count_incident_id=None, primary_count_location_id=None,
        review_note="Retain the reviewed uncertainty without a municipal count point.",
    )
    return sources, inventory, geometry, envelope


def test_berlin_review_pack_retains_reviewed_unlocated_articles_without_count_candidates(monkeypatch):
    sources, inventory, geometry, _ = _unlocated_berlin_inputs()
    monkeypatch.setattr("crimemapsberlin.map_decisions.read_checkpoint", lambda _path: (sources, {}))
    pack = build_review_pack(city="berlin", source_db=None, inventory=inventory, geometry_ledger=geometry)
    assert pack["mappable_articles"] == 1
    assert pack["excluded_scope_counts"] == {}
    assert pack["articles"][0]["scope_verdict"] == "uncertain"
    assert all(not row["count_point_available"] for row in pack["articles"][0]["formal_locations"])
    assert all(row["city_scope"] == "uncertain" for row in pack["articles"][0]["formal_locations"])


def test_berlin_uncertain_article_requires_map_semantics_but_cannot_count():
    sources, inventory, geometry, envelope = _unlocated_berlin_inputs()
    result = compile_map_decisions(
        city="berlin", source_rows=sources, inventory=inventory,
        geometry_ledger=geometry, decision_envelope=envelope,
    )
    assert result["decision_count"] == result["mappable_article_count"] == 1
    assert result["primary_count"] == 0
    assert result["owner_approved"] is False
    assert result["publication_ready"] is False
    envelope["decisions"][0].update(
        primary_count_incident_id="source-1:incident:1", primary_count_location_id="source-1:location:1",
    )
    with pytest.raises(ValueError, match="non-countable"):
        compile_map_decisions(
            city="berlin", source_rows=sources, inventory=inventory,
            geometry_ledger=geometry, decision_envelope=envelope,
        )


@pytest.mark.parametrize("change", ["other_city", "missing_six_rule_check", "outside_scope", "claimed_city_point"])
def test_berlin_uncertain_retention_does_not_relax_other_scope_or_review_gates(change):
    _, inventory, _, _ = _unlocated_berlin_inputs()
    article = inventory["articles"][0]
    assert displayable_article(inventory, article)
    if change == "other_city":
        inventory["city"] = "dusseldorf"
    elif change == "missing_six_rule_check":
        article["audit"]["six_rule_checks"]["all_location_roles_checked"] = False
    elif change == "outside_scope":
        article["scope_verdict"] = "out_of_city"
    else:
        article["formal_locations"][0]["coordinates"] = [13.4, 52.5]
    assert not displayable_article(inventory, article)
