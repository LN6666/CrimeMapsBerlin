"""Project hash-bound, explicitly reviewed display notes without changing map facts.

Coordinates, phases, categories, times and count choices come only from the
canonical ledgers. Historical comparisons retain their original review binding
separately from the current primary review used by this presentation.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

from .article_source_references import _auxiliary_review, _capture, _json
from .review_decisions import validate_stored_decision
from .source_relation_draft import _digest

EVENT_FIELDS = {
    "current_claim_overlays",
    "historical_source_reviews",
    "source_reference_comparisons",
    "source_attachments",
    "historical112_service_evidence",
    "map_review_note",
}
METADATA_FIELDS = {
    "candidate_notice",
    "coverage_scope",
    "source_reference_review_url",
    "historical112_service_review_url",
    "source_relation_ledger_sha256",
    "primary_source_relation_ledger_sha256",
    "applied_relation_choices",
    "current_claim_overlays",
    "geometry_reference_count",
    "explicit_geometry_gap_count",
}
RELATION_CORE = (
    "schema_version",
    "city",
    "source_decision_set_digest",
    "relation_set_sha256",
    "map_draft_sha256",
    "decisions",
    "confirmed_occurrence_groups",
    "announcement_count_references",
)


def _file(ref: dict) -> Path:
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
        raise ValueError("Display evidence needs an explicit file and SHA-256")
    path = Path(ref["path"])
    if hashlib.sha256(path.read_bytes()).hexdigest() != ref["sha256"]:
        raise ValueError(f"Stale display evidence: {path.name}")
    return path


def _references(inventory: dict) -> tuple[dict, dict]:
    reviews, pairs = {}, {}
    manifests = {
        a["source_reference_binding"]["manifest_file"]: a["source_reference_binding"]["manifest_sha256"]
        for a in inventory["articles"]
        if a.get("source_reference_binding")
    }
    for path, sha in manifests.items():
        manifest = _json({"file": path, "sha256": sha})
        for row in _json(manifest["reference_reviews"])["reviews"]:
            sid = row["decision"]["source_id"]
            capture = _capture(sid, manifest["captures"][sid])
            _auxiliary_review(row, capture, sid)
            if sid in reviews and reviews[sid] != row:
                raise ValueError("Conflicting auxiliary source reviews")
            reviews[sid] = row
        for pair in _json(manifest["comparisons"])["comparisons"]:
            key = pair["parent_source_id"], pair["target_source_id"]
            if key in pairs and pairs[key] != pair:
                raise ValueError("Conflicting historical comparisons")
            pairs[key] = pair
    return reviews, pairs


def apply_reviewed_display(
    events: list[dict], display: dict, *, inventory: dict, geometry_ledger: dict, map_ledger: dict
) -> None:
    """Validate all notes and relations before applying any presentation changes."""
    if (
        display.get("schema_version") != 1
        or display.get("city") != inventory["city"]
        or display.get("inventory_digest") != inventory["inventory_digest"]
        or display.get("geometry_ledger_sha256") != geometry_ledger["ledger_sha256"]
        or display.get("map_ledger_sha256") != map_ledger["ledger_sha256"]
        or not display.get("reviewer")
        or not display.get("reviewed_at")
        or display.get("owner_approved") is not False
        or display.get("publication_ready") is not False
    ):
        raise ValueError("Stale or invalid reviewed display binding")
    if (
        not isinstance(display.get("metadata"), dict)
        or set(display["metadata"]) - METADATA_FIELDS
        or not isinstance(display.get("publication_blocks"), list)
        or any(not isinstance(b, str) or not b for b in display["publication_blocks"])
    ):
        raise ValueError("Display annotations cannot override canonical map metadata")
    for ref in display.get("evidence_artifacts", []):
        _file(ref)
    for name, ref in display.get("resources", {}).items():
        if Path(name).name != name or name in {
            "manifest.json",
            "search.json",
            "boundary.geojson",
            "roads-overview.json",
        }:
            raise ValueError("Unsafe or protected display resource name")
        if Path(name).suffix not in {".html", ".json"}:
            raise ValueError("Unsupported display evidence resource")
        _file(ref)
    auxiliary, comparisons = _references(inventory)
    articles = {a["source_id"]: a for a in inventory["articles"]}
    identities = {sid: (a["source_sha256"], a["decision_sha256"]) for sid, a in articles.items()}
    relation_source_ids = set(articles)
    extra_reviews = {}
    identities.update(
        {sid: (r["decision"]["source_sha256"], r["decision_sha256"]) for sid, r in auxiliary.items()}
    )
    for ref in display.get("auxiliary_relation_sources", []):
        value = json.loads(_file(ref).read_text())
        source, review = value["source"], value["review"]
        if (
            hashlib.sha256(source["source_body"].encode()).hexdigest() != source["source_sha256"]
            or review["source_id"] != source["source_id"]
            or review["source_review_sha256"] != _digest(review["decision"])
            or review["decision"]["source_sha256"] != source["source_sha256"]
        ):
            raise ValueError("Stale auxiliary relation source")
        identities[source["source_id"]] = source["source_sha256"], review["source_review_sha256"]
        relation_source_ids.add(source["source_id"])
        validate_stored_decision(
            review["decision"],
            city=inventory["city"],
            source_id=source["source_id"],
            source={
                "id": source["source_id"],
                "url": source["source_url"],
                "sha256": source["source_sha256"],
                "body": source["source_body"],
            },
        )
        extra_reviews[source["source_id"]] = value
    relations = json.loads(_file(display["relation_ledger"]).read_text())
    source_digest = _digest(
        [
            {"source_id": sid, "source_sha256": identities[sid][0], "decision_sha256": identities[sid][1]}
            for sid in sorted(relation_source_ids)
        ]
    )
    if (
        relations.get("city") != inventory["city"]
        or relations.get("source_decision_set_digest") != source_digest
        or relations.get("draft_sha256") != _digest({k: relations.get(k) for k in RELATION_CORE})
    ):
        raise ValueError("Stale or modified relation ledger")
    relations_by_incident = {}
    for row in relations["decisions"]:
        p = row["proposal"]
        for prefix, hash_key in (("", "source_review_sha256"), ("prior_", "prior_source_review_sha256")):
            sid = p[f"{prefix}source_id"]
            if identities.get(sid) != (p[f"{prefix}source_sha256"], row[hash_key]):
                raise ValueError("Relation carries a stale source review")
            relations_by_incident.setdefault(p[f"{prefix}incident_id"], []).append(row)
    entries = {e["source_id"]: e for e in display["entries"]}
    if len(entries) != len(display["entries"]) or set(entries) != {e["id"] for e in events}:
        raise ValueError("Display notes must cover unique current map announcements")
    prepared = {}
    for event in events:
        sid, entry = event["id"], entries[event["id"]]
        if (
            entry.get("source_sha256") != event["source_sha256"]
            or entry.get("source_review_sha256") != event["source_review_sha256"]
            or entry.get("map_decision_sha256") != event["map_decision_sha256"]
            or set(entry.get("fields", {})) - EVENT_FIELDS
        ):
            raise ValueError(f"Stale or unauthorized display fields: {sid}")
        fields = copy.deepcopy(entry["fields"])
        if "map_review_note" in fields and entry.get("original_map_review_note") != event["map_review_note"]:
            raise ValueError("Presentation correction lost its original map decision note")
        for history in fields.get("historical_source_reviews", []):
            ref_id = history["source_id"]
            if ref_id in extra_reviews:
                value = extra_reviews[ref_id]
                connected = any(
                    {r["proposal"]["source_id"], r["proposal"]["prior_source_id"]} == {sid, ref_id}
                    for r in relations["decisions"]
                )
                if (
                    not connected
                    or history.get("source_url") != value["source"]["source_url"]
                    or history.get("source_sha256") != value["source"]["source_sha256"]
                    or history.get("source_review_sha256") != value["review"]["source_review_sha256"]
                    or history.get("source_incidents")
                    != value["review"]["decision"]["scene_inventory"]["incidents"]
                ):
                    raise ValueError("Historical relation display changed its reviewed auxiliary source")
                continue
            reviewed = auxiliary.get(ref_id)
            if (
                reviewed is None
                or ref_id not in articles[sid].get("source_reference_binding", {}).get("source_ids", [])
                or history.get("source_sha256") != reviewed["decision"]["source_sha256"]
                or history.get("source_review_sha256") != reviewed["decision_sha256"]
                or history.get("source_url") != reviewed["decision"]["source_url"]
            ):
                raise ValueError("Historical display is not a current bound reference")
            stages = reviewed["decision"]["stages"]
            expected = [
                {
                    "incident_id": s["stage_id"],
                    "details": f"{s['label']}：{s['details']}",
                    **{
                        k: s[k]
                        for k in (
                            "event_time",
                            "formal_location_ids",
                            "evidence_quote",
                            "independent_crime_count",
                        )
                    },
                }
                for s in stages
            ]
            if history.get("source_incidents") != expected:
                raise ValueError("Historical display changed or omitted reviewed phases")
        for pair in fields.get("source_reference_comparisons", []):
            original = comparisons.get((pair["parent_source_id"], pair["target_source_id"]))
            if original is None or any(
                pair.get(k) != v for k, v in original.items() if k != "candidate_application_complete"
            ):
                raise ValueError("Historical display changed its authored comparison")
            parent_id = pair["parent_source_id"]
            pair["original_parent_review_sha256"] = original["parent_review_sha256"]
            pair["parent_review_sha256"] = identities[parent_id][1]
            pair["presentation_primary_source_id"] = sid
            pair["presentation_primary_review_sha256"] = event["source_review_sha256"]
        for attachment in fields.get("source_attachments", []):
            bundle = articles[sid].get("source_attachment_binding", {}).get("review_bundle")
            if not bundle:
                raise ValueError("Attachment display lacks its current source binding")
            manifest = _json(bundle["manifest"])
            capture = manifest["capture"]
            if (
                attachment["source_url"] != capture["url"]
                or attachment["source_sha256"] != capture["sha256"]
                or attachment["page_count"] != capture["page_count"]
            ):
                raise ValueError("Attachment display differs from the captured version")
            _json(bundle["review"])
            _file({"path": capture["file"], "sha256": capture["sha256"]})
        prepared[sid] = fields
    for event in events:
        event.update(prepared[event["id"]])
        # These fields came from the separately bound public-presentation input,
        # rather than being copied out of private source/geometry review notes.
        event["public_display_fields"] = sorted(set(event.get("public_display_fields", [])) | set(prepared[event["id"]]))
        article = articles[event["id"]]
        for scene in event["scene_locations"]:
            selected = {
                r["proposal"]["relation_id"]: r
                for iid in scene["incident_ids"]
                for r in relations_by_incident.get(iid, [])
            }
            scene["source_relations"] = list(selected.values())
            scene["confirmed_occurrence_groups"] = [
                g for g in relations["confirmed_occurrence_groups"] if set(g) & set(scene["incident_ids"])
            ]
            if article.get("source_reference_binding"):
                scene["source_reference_binding"] = article["source_reference_binding"]
                scene["presentation_source_review_sha256"] = article["decision_sha256"]


def copy_display_resources(display: dict, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name, ref in display.get("resources", {}).items():
        shutil.copy2(_file(ref), root / name)
