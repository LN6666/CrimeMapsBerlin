"""Both the canonical source ledger and geometry handoff preserve authored judgments."""
import copy
import json

import pytest

from crimemapsberlin import review_decisions as R
from crimemapsberlin.reviewed_scenes import build_inventory
from test_reviewed_scenes import BODY, _decision_files, _source_db


def test_explicit_judgments_survive_source_and_geometry_hash_bindings(tmp_path):
    db_path = tmp_path / "sources.sqlite"
    digest = _source_db(db_path)
    review, scope, scene_path = _decision_files(tmp_path, digest)
    payload = json.loads(scene_path.read_text())
    location = payload["articles"][0]["formal_locations"][1]
    quote = location["evidence_quotes"]
    location.update(
        poi_contexts=[],
        poi_review={"status": "source_unknown", "note": "The nearby venue is unnamed in this source.", "evidence_quotes": quote},
        transit_review={"status": "not_applicable", "note": "The source describes a static private vehicle.", "evidence_quotes": quote},
    )
    scene_path.write_text(json.dumps(payload, ensure_ascii=False))
    R.import_decisions(db_path=db_path, city="cologne", review_path=review, scope_path=scope, scene_path=scene_path, imported_at=1)
    before = build_inventory(city="cologne", db_path=db_path)
    request = next(r for r in before["geometry_requests"]if r["location_id"] == location["location_id"])
    assert request["poi_review"] == location["poi_review"]
    assert request["transit_review"] == location["transit_review"]
    assert "poi_review" not in before["geometry_requests"][0]
    location["poi_review"]["note"] = "This exact static site remains unidentified; do not choose a nearby shop."
    scene_path.write_text(json.dumps(payload, ensure_ascii=False))
    R.import_decisions(db_path=db_path, city="cologne", review_path=review, scope_path=scope, scene_path=scene_path, imported_at=2)
    after = build_inventory(city="cologne", db_path=db_path)
    changed = next(r for r in after["geometry_requests"]if r["location_id"] == location["location_id"])
    assert request["decision_sha256"] != changed["decision_sha256"]
    assert request["geometry_request_sha256"] != changed["geometry_request_sha256"]
    assert before["inventory_digest"] != after["inventory_digest"]
    assert after["owner_approved"] is False and after["publication_ready"] is False


@pytest.mark.parametrize("mutation", ["empty_note", "stale_quote", "missing_contexts", "positive_without_context", "null_review", "route_without_metadata"])
def test_invalid_authored_judgments_fail_closed(tmp_path, mutation):
    digest = _source_db(tmp_path / "sources.sqlite")
    _, _, path = _decision_files(tmp_path, digest)
    payload = json.loads(path.read_text())["articles"][0]
    location = payload["formal_locations"][1]
    location.update(poi_contexts=[], poi_review={"status": "source_unknown", "note": "The actual private site is not identified.", "evidence_quotes": location["evidence_quotes"]})
    if mutation == "empty_note":
        location["poi_review"]["note"] = ""
    elif mutation == "stale_quote":
        location["poi_review"]["evidence_quotes"] = ["This claim came from a different source."]
    elif mutation == "missing_contexts":
        del location["poi_contexts"]
    elif mutation == "positive_without_context":
        location["poi_review"]["status"] = "context_only"
    elif mutation == "null_review":
        location["poi_review"] = None
    else:
        location["transit_review"] = {"status": "reviewed_route", "note": "The source names one reviewed bus carrier.", "evidence_quotes": location["evidence_quotes"]}
    with pytest.raises((ValueError, TypeError)):
        R._validate_scenes(copy.deepcopy(payload), R._normalized(BODY), "source-1", "source-1")
