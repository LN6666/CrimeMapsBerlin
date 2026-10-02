import copy
import hashlib
import json

import pytest

from crimemapsberlin.review_decisions import validate_stored_decision
from crimemapsberlin.source_phase_evidence import validate_referenced_phase_quotes
from crimemapsberlin.supporting_material_reviews import visible_materials

PRIMARY = "Das Kinderfest fand auf dem Polizeigelände statt."
EXTRA = "Während des Festes wurde ein symbolischer Spendenscheck überreicht."


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def bound(path, value):
    raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
    path.write_bytes(raw)
    return {"file": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def fixture(root):
    source = {"id": "test", "url": "https://example.invalid/primary", "body": PRIMARY,
              "sha256": hashlib.sha256(PRIMARY.encode()).hexdigest()}
    primary = bound(root / "primary.json", {"source_id": "test", "source_url": source["url"],
                                            "source_body": PRIMARY})
    robots = bound(root / "robots.txt", b"User-agent: *\nAllow: /\n")
    html = bound(root / "page.html", f"<p>{EXTRA}</p><script>Ignored secret statement</script>".encode())
    capture = bound(root / "capture.json", {"records": [{
        "name": "festival", "result": "captured", "response_url": "https://example.invalid/festival",
        "hops": [{"url": "https://example.invalid/festival", "status": 200, **html,
                  "robots_allowed": True, "robots": {**robots, "status": 200}}],
    }]})
    review = bound(root / "review.json", {
        "schema_version": 1, "city": "hamburg", "reviewer": "synthetic LLM reviewer",
        "reviewed_at": "2026-10-02T00:00:00+00:00", "generated_coordinates": False,
        "owner_approved": False, "publication_ready": False,
        "capture_manifests": [{"path": capture["file"], "sha256": capture["sha256"]}],
        "source_cases": [{"source_id": "test", "primary_body_sha256": source["sha256"],
                          "primary": {"path": primary["file"], "sha256": primary["sha256"]},
                          "references": ["festival"]}],
    })
    specs = [primary, robots, html, capture, review]
    manifest = bound(root / "manifest.json", {
        "schema_version": 1, "city": "hamburg",
        "files": {s["file"].rsplit("/", 1)[-1]: s["sha256"] for s in specs},
    })
    presentation = bound(root / "presentation.json", {
        "schema_version": 1, "city": "hamburg", "sources": {"test": {
            "source_sha256": source["sha256"], "materials": [{
                "reference": "festival", "label": "Reviewed event recap",
                "note": "Display cheque; precise date and actual payment unknown.",
            }],
        }},
    })
    value = {"schema_version": 1, "city": "hamburg", "source_id": "test",
             "source_url": source["url"], "source_sha256": source["sha256"],
             "review": {"verdict": "supported", "evidence_quotes": [PRIMARY],
                        "review_note": "Primary and separate captured page read in full.",
                        "reviewer": "synthetic LLM reviewer", "reviewed_at": "2026-10-02T00:00:00+00:00"},
             "scope": {"scope_verdict": "in_city", "evidence_quotes": [PRIMARY]},
             "scene_inventory": {"incident_count": 2, "incidents_complete": True,
                                 "formal_locations_complete": True, "formal_locations": [],
                                 "incidents": [
                                     {"incident_id": "test:incident:1", "evidence_quotes": [PRIMARY, EXTRA],
                                      "formal_location_ids": []},
                                     {"incident_id": "test:incident:2", "evidence_quotes": [PRIMARY],
                                      "formal_location_ids": []},
                                 ]},
             "source_supporting_material_binding": {
                 "review": review, "packet_manifest": manifest, "presentation": presentation,
                 "evidence_sources": {"/scene_inventory/incidents/0/evidence_quotes/1": "festival"},
             }}
    return value, source


def validate(value, source):
    return validate_stored_decision(value, source=source, city="hamburg", source_id="test")


def test_primary_and_supporting_quotes_retain_individual_origin(tmp_path):
    value, source = fixture(tmp_path)
    assert validate(value, source) == value
    material = visible_materials(value["source_supporting_material_binding"], source=source)[0]
    assert material["source_url"] == "https://example.invalid/festival"
    article = {"source_id": "test", "city": "hamburg", "source_sha256": source["sha256"],
               "decision_sha256": digest(value), "source_review_decision": value}
    assert validate_referenced_phase_quotes([EXTRA], article=article, source=source,
                                           incident_id="test:incident:1", primary_validator=validate) == [EXTRA]
    with pytest.raises(ValueError, match="same phase"):
        validate_referenced_phase_quotes([EXTRA], article=article, source=source,
                                         incident_id="test:incident:2", primary_validator=validate)


@pytest.mark.parametrize("wrong_phase", [False, True])
def test_map_categories_revalidate_separate_material_against_the_same_phase(tmp_path, wrong_phase):
    from crimemapsberlin.map_decisions import _digest, compile_map_decisions

    value, source = fixture(tmp_path)
    review_sha = digest(value)
    article = {"source_id": "test", "source_sha256": source["sha256"],
               "decision_sha256": review_sha, "scope_verdict": "in_city",
               "incidents": value["scene_inventory"]["incidents"],
               "formal_locations": [], "source_review_decision": value,
               "source_supporting_material_binding": value["source_supporting_material_binding"]}
    inventory = {"schema_version": 1, "city": "hamburg", "inventory_digest": "a" * 64,
                 "all_current_reviews_supported": True, "articles": [article]}
    core = {"schema_version": 1, "city": "hamburg", "inventory_digest": "a" * 64,
            "submitted_inventory_digest": "a" * 64, "geometry_index_sha256": "b" * 64,
            "decisions": []}
    geometry = {**core, "ledger_sha256": _digest(core), "request_count": 0,
                "geometry_review_complete": True, "pending_count": 0}
    decision = {"schema_version": 1, "city": "hamburg", "source_id": "test",
                "source_sha256": source["sha256"], "source_review_sha256": review_sha,
                "article_category": "sonstige", "is_crime_report": False,
                "classification_evidence_quotes": [PRIMARY],
                "incident_categories": [
                    {"incident_id": "test:incident:1", "category": "sonstige", "evidence_quotes": [EXTRA]},
                    {"incident_id": "test:incident:2", "category": "sonstige",
                     "evidence_quotes": [EXTRA if wrong_phase else PRIMARY]}],
                "primary_count_incident_id": None, "primary_count_location_id": None,
                "review_note": "Separate captured material, no event point or extra count.",
                "reviewer": "synthetic reviewer", "reviewed_at": "2026-10-02T00:00:00+00:00"}
    envelope = {"schema_version": 1, "city": "hamburg", "inventory_digest": "a" * 64,
                "geometry_ledger_sha256": geometry["ledger_sha256"], "decisions": [decision]}
    args = {"city": "hamburg", "source_rows": [{"source_id": "test", "source_url": source["url"],
            "source_body": PRIMARY, "source_sha256": source["sha256"], "title": "Synthetic festival"}],
            "inventory": inventory, "geometry_ledger": geometry, "decision_envelope": envelope}
    if wrong_phase:
        with pytest.raises(ValueError, match="same phase"):
            compile_map_decisions(**args)
    else:
        result = compile_map_decisions(**args)
        assert result["map_review_complete"] is True
        assert result["decisions"][0]["decision"]["incident_categories"][0]["evidence_quotes"] == [EXTRA]
        assert result["primary_count"] == 0


@pytest.mark.parametrize("name", ["page.html", "robots.txt", "review.json", "primary.json"])
def test_changed_capture_or_review_bytes_are_rejected(tmp_path, name):
    value, source = fixture(tmp_path)
    (tmp_path / name).write_bytes((tmp_path / name).read_bytes() + b" ")
    with pytest.raises(ValueError, match="changed"):
        validate(value, source)


@pytest.mark.parametrize("change", ["foreign_source", "unreviewed_reference", "script_quote", "only_extra",
                                   "wrong_path", "scalar_date"])
def test_external_quotes_cannot_escape_primary_or_origin_gates(tmp_path, change):
    value, source = fixture(tmp_path)
    value = copy.deepcopy(value)
    binding = value["source_supporting_material_binding"]
    phase = value["scene_inventory"]["incidents"][0]
    if change == "foreign_source":
        source["sha256"] = "a" * 64
    elif change == "unreviewed_reference":
        binding["evidence_sources"]["/scene_inventory/incidents/0/evidence_quotes/1"] = "other"
    elif change == "script_quote":
        phase["evidence_quotes"][1] = "Ignored secret statement"
    elif change == "only_extra":
        phase["evidence_quotes"] = [EXTRA]
        binding["evidence_sources"] = {"/scene_inventory/incidents/0/evidence_quotes/0": "festival"}
    elif change == "wrong_path":
        binding["evidence_sources"] = {"/review/evidence_quotes/0": "festival"}
    elif change == "scalar_date":
        phase["event_time"] = {"date": "2026-07-14", "precision": "exact", "display": "Photo date",
                               "evidence_quote": EXTRA}
    with pytest.raises(ValueError):
        validate(value, source)


def test_denied_robots_remains_blocked_even_after_rebinding_hashes(tmp_path):
    value, source = fixture(tmp_path)
    robots = bound(tmp_path / "robots.txt", b"User-agent: *\nDisallow: /\n")
    capture = json.loads((tmp_path / "capture.json").read_text())
    capture["records"][0]["hops"][0]["robots"] = {**robots, "status": 200}
    cap = bound(tmp_path / "capture.json", capture)
    review = json.loads((tmp_path / "review.json").read_text())
    review["capture_manifests"] = [{"path": cap["file"], "sha256": cap["sha256"]}]
    rev = bound(tmp_path / "review.json", review)
    packet = json.loads((tmp_path / "manifest.json").read_text())
    for spec in [robots, cap, rev]:
        packet["files"][spec["file"].rsplit("/", 1)[-1]] = spec["sha256"]
    value["source_supporting_material_binding"].update(
        review=rev, packet_manifest=bound(tmp_path / "manifest.json", packet))
    with pytest.raises(ValueError, match="robots denies"):
        validate(value, source)
