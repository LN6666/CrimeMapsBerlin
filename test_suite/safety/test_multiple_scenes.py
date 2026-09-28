"""Source-bound LLM scene-decision contract tests."""

import pytest

from crimemapsberlin.multiple_scenes import (
    scene_decision_index,
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
        validated_scene_decision(row, dict(decision, scenes=[dict(scene, evidence_quote="absent evidence quote")]))
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
