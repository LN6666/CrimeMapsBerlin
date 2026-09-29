"""Source-bound LLM scene-decision contract tests."""

import pytest

from crimemapsberlin.multiple_scenes import (
    scene_decision_index,
    validated_article_semantics,
    validated_scene_decision,
)


def test_llm_scene_decision_is_bound_to_source_hash_and_verbatim_evidence():
    quote = "An der Ecke Erste Straße wurde ein Mann beraubt."
    row = {"id": "42", "sha256": "abc", "body": quote}
    scene = {
        "scene_id": "42:1", "label": "Erste Straße", "role": "incident",
        "location_precision": "street", "geocode_method": "llm_reviewed_osm_point",
        "coordinates": [10.0, 53.5], "primary_for_count": True,
        "case_relation": "independent_case", "minimum_incidents": 1,
        "evidence_quote": quote,
    }
    decision = {"id": "42", "source_sha256": "abc", "scenes": [scene]}
    assert validated_scene_decision(row, decision) == [scene]
    assert decision["scenes"][0] is scene
    with pytest.raises(ValueError, match="Stale"):
        validated_scene_decision(dict(row, sha256="changed"), decision)
    with pytest.raises(ValueError, match="evidence"):
        validated_scene_decision(
            row,
            dict(decision, scenes=[dict(scene, evidence_quote="absent evidence quote")]),
        )
    with pytest.raises(ValueError, match="Non-independent"):
        validated_scene_decision(row, dict(decision, scenes=[dict(
            scene, primary_for_count=False, case_relation="same_case_phase",
        )]))
    unresolved = dict(
        scene, primary_for_count=False, case_relation="unresolved_relation",
    )
    unresolved.pop("minimum_incidents")
    assert validated_scene_decision(
        row, dict(decision, scenes=[unresolved])
    )[0]["case_relation"] == "unresolved_relation"


def test_linked_scene_decision_checks_current_related_source_hash():
    quote = "Zum früheren Bericht 7 wird auf die Ursprungsmeldung verwiesen."
    row = {"id": "42", "sha256": "current", "body": quote}
    scene = {
        "scene_id": "42:1", "label": "old scene", "role": "background",
        "location_precision": "unknown", "geocode_method": "llm_reviewed_unlocated_scene",
        "primary_for_count": False, "case_relation": "background_reference",
        "duplicate_of_source_id": "7", "duplicate_source_sha256": "old-hash",
        "evidence_quote": quote,
    }
    decision = {"id": "42", "source_sha256": "current", "scenes": [scene]}
    assert validated_scene_decision(row, decision, {"7": "old-hash"})[0][
        "duplicate_source_sha256"
    ] == "old-hash"
    with pytest.raises(ValueError, match="Stale linked"):
        validated_scene_decision(row, decision, {"7": "changed"})


def test_scene_decision_file_rejects_wrong_city_and_duplicate_articles():
    article = {"id": "42", "source_sha256": "abc", "scenes": []}
    payload = {"version": 1, "city": "hamburg", "articles": [article]}
    assert scene_decision_index(payload, city="hamburg") == {"42": article}
    with pytest.raises(ValueError, match="another city"):
        scene_decision_index(payload, city="berlin")
    with pytest.raises(ValueError, match="Duplicate"):
        scene_decision_index(dict(payload, articles=[article, article]), city="hamburg")


def test_reviewed_article_semantics_require_verbatim_evidence_and_linked_hash():
    row = {
        "id": "42", "sha256": "current",
        "title": "Aktualisierung der vorläufigen Bilanz",
        "body": "Die Übersicht nennt Straftaten und wiederholt den früheren Bericht.",
    }
    decision = {
        "classification": {
            "category": "Verkehr / sonstige Meldung", "is_crime_report": True,
            "evidence_quote": "Die Übersicht nennt Straftaten",
        },
        "followup": {
            "source_id": "7", "source_sha256": "old-hash",
            "evidence_quote": "Aktualisierung der vorläufigen Bilanz",
        },
    }
    assert validated_article_semantics(row, decision, {"7": "old-hash"}) == {
        "category": "Verkehr / sonstige Meldung", "is_crime_report": True,
        "followup_of_source_id": "7",
    }
    with pytest.raises(ValueError, match="classification"):
        validated_article_semantics(
            row,
            dict(decision, classification=dict(decision["classification"], evidence_quote="absent")),
            {"7": "old-hash"},
        )
    with pytest.raises(ValueError, match="followup"):
        validated_article_semantics(row, decision, {"7": "changed"})


def test_legacy_row_without_title_only_skips_absent_semantic_overrides():
    row = {"id": "42", "sha256": "current", "body": "Verbatim source body."}
    assert validated_article_semantics(row, {}) == {}
    with pytest.raises(ValueError, match="classification"):
        validated_article_semantics(row, {
            "classification": {
                "category": "Unklassifiziert", "is_crime_report": True,
                "evidence_quote": "evidence present only in a missing title",
            },
        })


def test_moving_transit_scene_keeps_route_time_details_and_context_without_count_point():
    quote = (
        "Gegen 23 Uhr sahen Zeugen in einer U-Bahn der Linie U8 einen Mann mit einer Waffe."
    )
    row = {"id": "u8", "sha256": "source", "body": quote}
    scene = {
        "scene_id": "u8:route", "label": "U8", "role": "incident",
        "location_precision": "route", "geocode_method": "osm_transit_route",
        "geometry": {
            "type": "LineString",
            "coordinates": [[13.3, 52.5], [13.5, 52.6]],
        },
        "primary_for_count": False, "case_relation": "independent_case",
        "minimum_incidents": 1, "evidence_quote": quote,
        "details": "The weapon threat occurred inside the moving train.",
        "event_time": {
            "display": "gegen 23 Uhr", "date": "2026-09-19",
            "precision": "approximate", "evidence_quote": quote,
        },
        "transit_route": {
            "mode": "subway", "line": "U8", "extent": "full_line",
            "evidence_quote": quote,
        },
        "poi_contexts": [{
            "kind": "station", "scope": "along_geometry", "radius_m": 0,
            "evidence_quote": quote,
        }],
    }
    reviewed = validated_scene_decision(
        row, {"id": "u8", "source_sha256": "source", "scenes": [scene]}
    )
    assert reviewed[0]["transit_route"]["extent"] == "full_line"
    assert reviewed[0]["event_time"]["date"] == "2026-09-19"
    assert reviewed[0]["primary_for_count"] is False


def test_discovery_scene_cannot_be_selected_as_offence_count_point():
    quote = "In der Nogatstraße versorgten Einsatzkräfte einen verletzten Mann."
    row = {"id": "found", "sha256": "source", "body": quote}
    scene = {
        "scene_id": "found:discovery", "label": "Nogatstraße",
        "role": "discovery", "location_precision": "point",
        "geocode_method": "reviewed_discovery", "coordinates": [13.44, 52.47],
        "primary_for_count": True, "case_relation": "independent_case",
        "minimum_incidents": 1, "evidence_quote": quote,
    }
    with pytest.raises(ValueError, match="Invalid primary scene"):
        validated_scene_decision(
            row, {"id": "found", "source_sha256": "source", "scenes": [scene]}
        )
