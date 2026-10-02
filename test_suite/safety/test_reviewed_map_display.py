import hashlib
import json
from copy import deepcopy

import pytest

from crimemapsberlin import reviewed_map_display as display


def _inputs(tmp_path):
    article = {"source_id": "1", "source_sha256": "a" * 64, "decision_sha256": "b" * 64}
    inventory = {"city": "hamburg", "inventory_digest": "i" * 64, "articles": [article]}
    event = {
        "id": "1",
        "source_sha256": "a" * 64,
        "source_review_sha256": "b" * 64,
        "map_decision_sha256": "c" * 64,
        "map_review_note": "Original reviewed note",
        "scene_locations": [
            {
                "scene_id": "1:location:1",
                "incident_ids": ["1:incident:1"],
                "coordinates": None,
                "primary_for_count": False,
            }
        ],
    }
    core = {k: None for k in display.RELATION_CORE}
    core.update(
        schema_version=1,
        city="hamburg",
        decisions=[],
        confirmed_occurrence_groups=[],
        announcement_count_references=[],
        source_decision_set_digest=display._digest(
            [{"source_id": "1", "source_sha256": "a" * 64, "decision_sha256": "b" * 64}]
        ),
    )
    ledger = {**core, "draft_sha256": display._digest(core)}
    path = tmp_path / "relations.json"
    path.write_text(json.dumps(ledger))
    packet = {
        "schema_version": 1,
        "city": "hamburg",
        "inventory_digest": "i" * 64,
        "geometry_ledger_sha256": "g" * 64,
        "map_ledger_sha256": "m" * 64,
        "reviewer": "Explicit test reviewer",
        "reviewed_at": "2026-10-02T00:00:00+00:00",
        "owner_approved": False,
        "publication_ready": False,
        "metadata": {},
        "publication_blocks": [],
        "relation_ledger": {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
        "entries": [
            {
                "source_id": "1",
                "source_sha256": "a" * 64,
                "source_review_sha256": "b" * 64,
                "map_decision_sha256": "c" * 64,
                "original_map_review_note": event["map_review_note"],
                "fields": {"map_review_note": "Previously authored current display note"},
            }
        ],
    }
    return [event], packet, inventory


def _apply(events, packet, inventory):
    display.apply_reviewed_display(
        events,
        packet,
        inventory=inventory,
        geometry_ledger={"ledger_sha256": "g" * 64},
        map_ledger={"ledger_sha256": "m" * 64},
    )


def test_reviewed_display_can_change_wording_without_changing_coordinates_or_counts(tmp_path):
    events, packet, inventory = _inputs(tmp_path)
    _apply(events, packet, inventory)
    assert events[0]["map_review_note"] == packet["entries"][0]["fields"]["map_review_note"]
    assert events[0]["scene_locations"][0]["coordinates"] is None
    assert events[0]["scene_locations"][0]["primary_for_count"] is False


@pytest.mark.parametrize(
    "change", ["coordinate", "stale_source", "stale_original_note", "protected_metadata"]
)
def test_invalid_display_is_rejected_before_any_event_mutation(tmp_path, change):
    events, packet, inventory = _inputs(tmp_path)
    original = deepcopy(events)
    if change == "coordinate":
        packet["entries"][0]["fields"]["coordinates"] = [10, 53.55]
    elif change == "stale_source":
        packet["entries"][0]["source_review_sha256"] = "z" * 64
    elif change == "stale_original_note":
        packet["entries"][0]["original_map_review_note"] = "Different decision"
    else:
        packet["metadata"]["primary_count_points"] = 200
    with pytest.raises(ValueError):
        _apply(events, packet, inventory)
    assert events == original


def test_resources_cannot_overwrite_canonical_map_payload(tmp_path):
    events, packet, inventory = _inputs(tmp_path)
    packet["resources"] = {"search.json": packet["relation_ledger"]}
    with pytest.raises(ValueError, match="protected display resource"):
        _apply(events, packet, inventory)


def test_historical_comparison_preserves_original_binding_and_uses_current_primary_review(
    tmp_path, monkeypatch
):
    events, packet, inventory = _inputs(tmp_path)
    pair = {
        "parent_source_id": "1",
        "target_source_id": "2",
        "parent_review_sha256": "old" * 21,
        "target_review_sha256": "d" * 64,
        "review_note": "Authored historical comparison",
    }
    monkeypatch.setattr(
        display,
        "_references",
        lambda _: (
            {"2": {"decision": {"source_sha256": "e" * 64}, "decision_sha256": "d" * 64}},
            {("1", "2"): pair},
        ),
    )
    packet["entries"][0]["fields"]["source_reference_comparisons"] = [deepcopy(pair)]
    _apply(events, packet, inventory)
    projected = events[0]["source_reference_comparisons"][0]
    assert projected["parent_review_sha256"] == "b" * 64
    assert projected["original_parent_review_sha256"] == pair["parent_review_sha256"]
    assert projected["presentation_primary_review_sha256"] == "b" * 64
    assert events[0]["scene_locations"][0]["coordinates"] is None
