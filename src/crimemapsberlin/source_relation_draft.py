"""Validate explicit LLM occurrence relations and detect duplicate draft counts.

This is a local draft, including source questions when present. It never
classifies narratives, infers an identity from a relation label, replaces
source facts/locations, compiles a final map or grants publication approval.
Only an explicitly reviewed ``same_occurrence`` links occurrence identities.
Case updates, aggregates, phases and tentative connections stay separate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

from .map_decisions import _digest, _exact_keys, _normalized
from .review_decisions import validate_stored_decision
from .reviewed_scenes import _decision_table
from .source_review_pack import read_checkpoint

TREATMENTS = {
    "same_occurrence",
    "case_update",
    "aggregate_context",
    "planned_actual",
    "distinct_phase",
    "tentative_connection",
    "cumulative_status",
    "same_plan_revision",
}
DECISION_KEYS = {
    "relation_id",
    "treatment",
    "preferred_source_id",
    "supersedes_fields",
    "review_note",
    "reviewer",
    "reviewed_at",
}
SUPERSEDABLE_FIELDS = {"explanation", "location", "event_date"}


def compile_relation_draft(
    *,
    city: str,
    source_rows: list[dict],
    source_reviews: list[dict],
    proposals: list[dict],
    map_decisions: list[dict],
    decision_envelope: dict,
) -> dict:
    """Bind every relation choice to current source/semantic/map draft hashes.

    Count references are announcement-level choices, not proven crimes. This
    draft rejects duplicate selected references to one confirmed occurrence;
    it does not choose which source, scene, location or coordinate to keep.
    """
    sources = {row["source_id"]: row for row in source_rows}
    if len(sources) != len(source_rows) or not sources:
        raise ValueError("Source checkpoint has duplicate IDs or is empty")
    for source in sources.values():
        if hashlib.sha256(source["source_body"].encode()).hexdigest() != source["source_sha256"]:
            raise ValueError("Source body does not match its current hash")
    reviewed = {}
    nodes = set()
    for row in source_reviews:
        source_id = row["source_id"]
        if source_id in reviewed or source_id not in sources:
            raise ValueError("Source review has a duplicate or unknown source ID")
        source = sources[source_id]
        decision = validate_stored_decision(
            row["decision"],
            city=city,
            source_id=source_id,
            source={
                "id": source_id,
                "url": source["source_url"],
                "body": source["source_body"],
                "sha256": source["source_sha256"],
            },
        )
        if _digest(decision) != row["source_review_sha256"]:
            raise ValueError("Source review digest is stale")
        reviewed[source_id] = row
        nodes.update(x["incident_id"] for x in decision["scene_inventory"]["incidents"])
    if set(reviewed) != set(sources):
        raise ValueError("Relation draft requires every current source review")
    source_set_digest = _digest(
        [
            {
                "source_id": sid,
                "source_sha256": sources[sid]["source_sha256"],
                "decision_sha256": reviewed[sid]["source_review_sha256"],
            }
            for sid in sorted(sources)
        ]
    )
    envelope = _exact_keys(
        decision_envelope,
        {
            "schema_version",
            "city",
            "source_decision_set_digest",
            "relation_set_sha256",
            "map_draft_sha256",
            "decisions",
        },
        "relation decision envelope",
    )
    if (
        envelope["schema_version"] != 1
        or envelope["city"] != city
        or envelope["source_decision_set_digest"] != source_set_digest
        or envelope["relation_set_sha256"] != _digest(proposals)
        or envelope["map_draft_sha256"] != _digest(map_decisions)
    ):
        raise ValueError("Relation envelope is stale or belongs to another city")
    indexed = {}
    for proposal in proposals:
        ident = proposal["relation_id"]
        if ident in indexed or proposal["schema_version"] != 1 or proposal["city"] != city:
            raise ValueError("Relation proposal is duplicate or belongs to another city")
        for source_key, hash_key, incident_key in (
            ("source_id", "source_sha256", "incident_id"),
            ("prior_source_id", "prior_source_sha256", "prior_incident_id"),
        ):
            sid = proposal[source_key]
            if sid not in sources or sources[sid]["source_sha256"] != proposal[hash_key]:
                raise ValueError("Relation proposal has stale source bytes")
            scene_ids = {x["incident_id"] for x in reviewed[sid]["decision"]["scene_inventory"]["incidents"]}
            if proposal[incident_key] not in scene_ids:
                raise ValueError("Relation proposal refers to a missing scene")
        quote = _normalized(proposal["evidence_quote"])
        if len(quote) < 15 or quote not in _normalized(sources[proposal["source_id"]]["source_body"]):
            raise ValueError("Relation evidence is absent from the current source")
        if proposal["incident_id"] == proposal["prior_incident_id"]:
            raise ValueError("Relation must connect different source scenes")
        if ident != proposal["incident_id"] + "::" + proposal["prior_incident_id"]:
            raise ValueError("Relation identity does not match its scene endpoints")
        indexed[ident] = proposal

    parent = {node: node for node in nodes}

    def find(node):
        while node != parent[node]:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    compiled = []
    seen = set()
    for raw in envelope["decisions"]:
        choice = _exact_keys(raw, DECISION_KEYS, "relation choice")
        ident = choice["relation_id"]
        if ident in seen or ident not in indexed or choice["treatment"] not in TREATMENTS:
            raise ValueError("Relation choice is duplicate, unknown or invalid")
        seen.add(ident)
        proposal = indexed[ident]
        for key in ("review_note", "reviewer"):
            if not isinstance(choice[key], str) or not choice[key].strip():
                raise ValueError("Relation choice needs a review note and reviewer")
        if datetime.fromisoformat(choice["reviewed_at"]).tzinfo is None:
            raise ValueError("Relation review timestamp needs a timezone")
        fields = choice["supersedes_fields"]
        if (
            not isinstance(fields, list)
            or len(fields) != len(set(fields))
            or set(fields) - SUPERSEDABLE_FIELDS
        ):
            raise ValueError("Invalid superseded field selection")
        preferred = choice["preferred_source_id"]
        if preferred is not None and preferred not in {proposal["source_id"], proposal["prior_source_id"]}:
            raise ValueError("Preferred source is not a relation endpoint")
        if fields and (preferred is None or choice["treatment"] != "same_occurrence"):
            raise ValueError("Supersession needs an explicit same-occurrence source preference")
        if preferred is not None and choice["treatment"] not in {"same_occurrence", "same_plan_revision"}:
            raise ValueError("Context or tentative relations cannot select a preferred source")
        if choice["treatment"] == "same_occurrence":
            left, right = find(proposal["incident_id"]), find(proposal["prior_incident_id"])
            parent[max(left, right)] = min(left, right)
        compiled.append(
            {
                "proposal": proposal,
                "decision": choice,
                "source_review_sha256": reviewed[proposal["source_id"]]["source_review_sha256"],
                "prior_source_review_sha256": reviewed[proposal["prior_source_id"]]["source_review_sha256"],
            }
        )
    if seen != set(indexed):
        raise ValueError("An explicit choice is required for every relation proposal")

    references = []
    counted = {}
    seen_sources = set()
    for row in map_decisions:
        sid = row["source_id"]
        if sid in seen_sources or sid not in reviewed:
            raise ValueError("Map draft has duplicate or unknown source IDs")
        seen_sources.add(sid)
        if (
            row["source_sha256"] != sources[sid]["source_sha256"]
            or row["source_review_sha256"] != reviewed[sid]["source_review_sha256"]
        ):
            raise ValueError("Map draft source/review binding is stale")
        iid, lid = row["primary_count_incident_id"], row["primary_count_location_id"]
        if (iid is None) != (lid is None):
            raise ValueError("Map primary incident/location must both be present or absent")
        if iid is None:
            continue
        semantic = reviewed[sid]["decision"]
        scene = next((i for i in semantic["scene_inventory"]["incidents"] if i["incident_id"] == iid), None)
        location = next(
            (l for l in semantic["scene_inventory"]["formal_locations"] if l["location_id"] == lid), None
        )
        if (
            semantic["review"]["verdict"] != "supported"
            or scene is None
            or location is None
            or semantic["scope"]["scope_verdict"] not in {"in_city", "mixed"}
            or lid not in scene["formal_location_ids"]
            or location["role"] not in {"incident", "accident"}
            or location["city_scope"] != "in_city"
        ):
            raise ValueError("Map reference has an unsupported scene/location")
        group = find(iid)
        if group in counted:
            raise ValueError(f"Duplicate selected occurrence references: {counted[group]} and {sid}")
        counted[group] = sid
        references.append(
            {"source_id": sid, "incident_id": iid, "location_id": lid, "occurrence_group": group}
        )
    groups = {}
    for node in sorted(nodes):
        groups.setdefault(find(node), []).append(node)
    core = {
        "schema_version": 1,
        "city": city,
        "source_decision_set_digest": source_set_digest,
        "relation_set_sha256": envelope["relation_set_sha256"],
        "map_draft_sha256": envelope["map_draft_sha256"],
        "decisions": compiled,
        "confirmed_occurrence_groups": [members for members in groups.values() if len(members) > 1],
        "announcement_count_references": references,
    }
    return {
        **core,
        "draft_sha256": _digest(core),
        "relation_decisions": len(compiled),
        "treatment_counts": dict(sorted(Counter(x["decision"]["treatment"] for x in compiled).items())),
        "primary_reference_count": len(references),
        "duplicate_selected_occurrence_references": 0,
        "all_source_reviews_supported": all(
            x["decision"]["review"]["verdict"] == "supported" for x in reviewed.values()
        ),
        "geometry_eligibility_revalidated": False,
        "formal_map_compiled": False,
        "owner_approved": False,
        "publication_ready": False,
        "count_unit": "reviewed_announcement_reference_not_crime_total",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", required=True)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--relations", type=Path, required=True, help="Source-bound NDJSON proposals")
    parser.add_argument("--decisions", type=Path, required=True, help="Explicit LLM decision JSON envelope")
    parser.add_argument("--map-decisions", type=Path, required=True, help="Current map draft NDJSON")
    parser.add_argument("--out", type=Path, required=True, help="Local draft JSON; never publication data")
    args = parser.parse_args()
    source_rows, _ = read_checkpoint(args.source_db)
    with sqlite3.connect(f"file:{args.source_db.resolve()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        table = _decision_table(db)
        if table is None:
            raise ValueError("Source database has no semantic review table")
        reviews = [
            {
                "source_id": row["source_id"],
                "source_review_sha256": row["decision_sha256"],
                "decision": json.loads(row["decision_json"]),
            }
            for row in db.execute(
                f"SELECT source_id,decision_sha256,decision_json FROM {table} WHERE city=? ORDER BY source_id",
                (args.city,),
            )
        ]
    result = compile_relation_draft(
        city=args.city,
        source_rows=source_rows,
        source_reviews=reviews,
        proposals=[json.loads(x) for x in args.relations.read_text().splitlines() if x.strip()],
        map_decisions=[json.loads(x) for x in args.map_decisions.read_text().splitlines() if x.strip()],
        decision_envelope=json.loads(args.decisions.read_text()),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "relation_decisions",
                    "treatment_counts",
                    "primary_reference_count",
                    "duplicate_selected_occurrence_references",
                    "all_source_reviews_supported",
                    "formal_map_compiled",
                    "owner_approved",
                    "publication_ready",
                    "draft_sha256",
                )
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
