"""Synthetic references exercise rejected stale/borrowed/cross-body evidence."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from crimemapsberlin.article_source_references import (
    _digest,
    evidence_leaves,
    validate_source_referenced_decision,
)


def bound(path, value):
    raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
    path.write_bytes(raw)
    return {"file": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


@pytest.fixture
def reference_bundle(tmp_path):
    url = "https://www.presseportal.de/blaulicht/pm/6337/11"
    primary = {"id": "10", "url": "https://www.presseportal.de/blaulicht/pm/6337/10",
               "body": "Primary current incident report. Official reference: " + url}
    primary["sha256"] = hashlib.sha256(primary["body"].encode()).hexdigest()
    base = {"schema_version": 1, "city": "hamburg", "source_id": "10",
            "source_url": primary["url"], "source_sha256": primary["sha256"],
            "review": {"evidence_quotes": ["Primary current incident report."]},
            "scope": {"evidence_quotes": ["Primary current incident report."]},
            "scene_inventory": {"incidents": [{"incident_id": "10:incident:1",
                                                "evidence_quotes": ["Primary current incident report."]}]}}
    body = "The earlier incident happened outside the bus. No exact stop is established."
    html = (f'<article class="story"><p class="customer">Polizei Hamburg</p>'
            f'<h1>Synthetic</h1><p>{body}</p></article>').encode()
    raw = {"source_id": "11", "source_url": url, "response_url": url, "http_status": 200,
           "redirect_location": None, "robots_allowed": True, "publisher_verified": True,
           "expected_publisher": "Polizei Hamburg", "observed_publisher": "Polizei Hamburg",
           "html_sha256": hashlib.sha256(html).hexdigest(), "body": body,
           "source_sha256": hashlib.sha256(body.encode()).hexdigest()}
    review = {"schema_version": 1, "city": "hamburg", "source_id": "11", "source_url": url,
              "source_sha256": raw["source_sha256"], "html_sha256": raw["html_sha256"],
              "publisher": "Polizei Hamburg", "full_body_read": True,
              "all_distinct_source_stages_reviewed": True, "all_formal_locations_reviewed": True,
              "source_scene_review_complete": True, "primary_2026_archive_record": False,
              "primary_map_announcement": False, "program_semantic_inference": False,
              "owner_approved": False, "publication_ready": False,
              "stages": [{"stage_id": "11:reference-stage:1", "independent_crime_count": None,
                          "formal_location_ids": ["11:reference-location:1"],
                          "evidence_quote": "The earlier incident happened outside the bus.",
                          "event_time": {"date": None, "display": "unknown", "precision": "unknown",
                                         "evidence_quote": "No exact stop is established."}}],
              "formal_locations": [{"location_id": "11:reference-location:1", "coordinates": None,
                                    "evidence_quote": "The earlier incident happened outside the bus.",
                                    "poi_judgment": "Unknown individual venue",
                                    "transit_judgment": "Offboard, no inferred transit route"}]}
    pair = {"parent_source_id": "10", "target_source_id": "11",
            "parent_source_sha256": primary["sha256"], "parent_review_sha256": _digest(base),
            "target_source_url": url, "target_source_sha256": raw["source_sha256"],
            "target_review_sha256": _digest(review), "official_link_evidence_quote": url,
            "parent_stage_ids": ["10:incident:1"], "target_stage_ids": ["11:reference-stage:1"],
            "automatic_occurrence_merge": False, "primary_count_increase": 0}
    manifest = {"schema_version": 1, "city": "hamburg",
                "primary_sources": bound(tmp_path / "primary.json", [primary]),
                "primary_decisions": bound(tmp_path / "base.json", [{"source_id": "10", "decision": base,
                                                                        "decision_sha256": _digest(base)}]),
                "reference_reviews": bound(tmp_path / "review.json", {"reviews": [
                    {"decision": review, "decision_sha256": _digest(review)}]}),
                "comparisons": bound(tmp_path / "pairs.json", {"comparisons": [pair]}),
                "captures": {"11": {"capture": bound(tmp_path / "capture.json", raw),
                                    "html": bound(tmp_path / "article.html", html),
                                    "body": bound(tmp_path / "body.txt", body.encode()),
                                    "robots": bound(tmp_path / "robots.txt", b"User-agent: *\nAllow: /\n")}}}
    decision = copy.deepcopy(base)
    decision["scene_inventory"]["incidents"][0]["evidence_quotes"] = [
        "The earlier incident happened outside the bus."]
    origins = {p: "10" for p in evidence_leaves(decision)}
    origins["/scene_inventory/incidents/0/evidence_quotes/0"] = "11"
    spec = bound(tmp_path / "manifest.json", manifest)
    decision["source_reference_binding"] = {"manifest_file": spec["file"],
                                            "manifest_sha256": spec["sha256"],
                                            "source_ids": ["11"], "evidence_sources": origins}
    return decision, primary, manifest


def validate(bundle):
    decision, primary, _ = bundle
    return validate_source_referenced_decision(
        decision, source=primary, city="hamburg", source_id="10",
        primary_validator=lambda value, source, city, ident: value,
    )


def update_manifest(bundle):
    decision, _, manifest = bundle
    spec = bound(Path(decision["source_reference_binding"]["manifest_file"]), manifest)
    decision["source_reference_binding"]["manifest_sha256"] = spec["sha256"]


def test_accepts_individually_bound_evidence(reference_bundle):
    assert validate(reference_bundle) == reference_bundle[0]


@pytest.mark.parametrize("mutation", ["body", "html", "robots", "capture"])
def test_changed_capture_bytes_rejected(reference_bundle, mutation):
    path = Path(reference_bundle[2]["captures"]["11"][mutation]["file"])
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="Stale bound file"):
        validate(reference_bundle)


def test_quote_cannot_cross_article_boundaries(reference_bundle):
    decision = reference_bundle[0]
    decision["scene_inventory"]["incidents"][0]["evidence_quotes"] = [
        "6337/11 The earlier incident happened"]
    with pytest.raises(ValueError, match="declared individual source"):
        validate(reference_bundle)


def test_wrong_origin_and_missing_origin_rejected(reference_bundle):
    origins = reference_bundle[0]["source_reference_binding"]["evidence_sources"]
    path = "/scene_inventory/incidents/0/evidence_quotes/0"
    origins[path] = "10"
    with pytest.raises(ValueError, match="declared individual source"):
        validate(reference_bundle)
    del origins[path]
    with pytest.raises(ValueError, match="quotation origins"):
        validate(reference_bundle)


def test_primary_scope_cannot_borrow_reference(reference_bundle):
    reference_bundle[0]["scope"]["evidence_quotes"] = ["The earlier incident happened outside the bus."]
    reference_bundle[0]["source_reference_binding"]["evidence_sources"]["/scope/evidence_quotes/0"] = "11"
    with pytest.raises(ValueError, match="scope evidence cannot borrow"):
        validate(reference_bundle)


@pytest.mark.parametrize("mutation", ["publisher", "robots", "link", "stage", "review_hash"])
def test_rehashed_transport_does_not_override_source_validation(reference_bundle, mutation):
    manifest = reference_bundle[2]
    if mutation == "publisher":
        spec = manifest["captures"]["11"]["capture"]
        value = json.loads(Path(spec["file"]).read_text())
        value["observed_publisher"] = "Unofficial author"
        manifest["captures"]["11"]["capture"] = bound(Path(spec["file"]), value)
    elif mutation == "robots":
        spec = manifest["captures"]["11"]["robots"]
        manifest["captures"]["11"]["robots"] = bound(Path(spec["file"]), b"User-agent: *\nDisallow: /\n")
    else:
        spec = manifest["comparisons"]
        value = json.loads(Path(spec["file"]).read_text())
        if mutation == "link":
            value["comparisons"][0]["official_link_evidence_quote"] = "https://invalid.example/article"
        elif mutation == "stage":
            value["comparisons"][0]["target_stage_ids"] = ["11:reference-stage:404"]
        else:
            value["comparisons"][0]["target_review_sha256"] = "0" * 64
        manifest["comparisons"] = bound(Path(spec["file"]), value)
    update_manifest(reference_bundle)
    with pytest.raises(ValueError):
        validate(reference_bundle)


def test_current_primary_body_cannot_keep_old_hash(reference_bundle):
    reference_bundle[1]["body"] += " changed"
    with pytest.raises(ValueError, match="Current primary body changed"):
        validate(reference_bundle)


def test_reference_ids_must_match_complete_reviewed_graph(reference_bundle):
    reference_bundle[0]["source_reference_binding"]["source_ids"] = ["11", "12"]
    with pytest.raises(ValueError, match="selected reference IDs"):
        validate(reference_bundle)
