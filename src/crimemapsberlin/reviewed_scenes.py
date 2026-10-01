"""Build a local geometry work inventory from current source-bound LLM decisions.

This stage does not infer meaning or geocode a label. It revalidates stored
decisions, preserves every reviewed incident and formal location, and records
which checked geometry operation is still required. It never writes public map
data or grants owner approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path

from .review_decisions import REVIEW_VERDICTS, validate_stored_decision
from .source_review_pack import CANONICAL_CITY_SLUGS, read_checkpoint_connection

DECISION_TABLES = ("source_llm_review_decisions", "llm_review_decisions")
POINT_PRECISIONS = {"point", "address", "place"}


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _decision_table(db: sqlite3.Connection) -> str | None:
    tables = {
        row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    present = [table for table in DECISION_TABLES if table in tables]
    if len(present) > 1:
        raise ValueError("Checkpoint contains ambiguous LLM decision tables")
    return present[0] if present else None


def _geometry_task(location: dict) -> str:
    if location["coordinates"] is not None:
        return "review_point_requires_boundary_check"
    precision = location["precision"]
    if precision in POINT_PRECISIONS:
        return "checked_point_geocode_required"
    if precision == "street":
        return "checked_road_geometry_required"
    if precision == "route":
        return "checked_transit_route_geometry_required"
    if precision == "area":
        return "checked_area_geometry_required"
    if precision == "district":
        return "checked_district_geometry_required"
    return "unresolved_no_geometry"


def build_inventory(*, city: str, db_path: Path) -> dict:
    """Return a hash-bound local scene inventory without resolving geometry."""
    if city == "munich":
        raise ValueError("Munich uses the owner-accepted POLIZEIKARTE scene basis")
    if city not in CANONICAL_CITY_SLUGS:
        raise ValueError(f"Unsupported city slug: {city}")
    if not db_path.is_file():
        raise ValueError(f"SQLite checkpoint does not exist: {db_path}")

    with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        source_rows, coverage = read_checkpoint_connection(db)
        sources = {
            row["source_id"]: {
                "id": row["source_id"],
                "url": row["source_url"],
                "body": row["source_body"],
                "sha256": row["source_sha256"],
            }
            for row in source_rows
        }
        table = _decision_table(db)
        decisions = {}
        if table:
            decisions = {
                row["source_id"]: row
                for row in db.execute(
                    f"""SELECT source_id,source_url,source_sha256,decision_sha256,
                               decision_json,verdict,scope_verdict,incident_count
                        FROM {table} WHERE city=? ORDER BY source_id""",
                    (city,),
                )
            }

        counts = Counter(
            pending=coverage["missing_bodies"],
            supported=0,
            needs_correction=0,
            uncertain=0,
            stale=0,
        )
        articles = []
        geometry_requests = []
        current_decisions = []
        for source_id, source in sorted(sources.items()):
            row = decisions.get(source_id)
            if row is None:
                counts["pending"] += 1
                continue
            if (
                row["source_url"] != source["url"]
                or row["source_sha256"] != source["sha256"]
            ):
                counts["stale"] += 1
                continue
            try:
                stored = json.loads(row["decision_json"])
            except json.JSONDecodeError as exc:
                raise ValueError(f"Stored review decision is invalid: {source_id}") from exc
            decision = validate_stored_decision(
                stored, source=source, city=city, source_id=source_id
            )
            if (
                _digest(decision) != row["decision_sha256"]
                or row["verdict"] not in REVIEW_VERDICTS
                or row["verdict"] != decision["review"]["verdict"]
                or row["scope_verdict"] != decision["scope"]["scope_verdict"]
                or row["incident_count"]
                != decision["scene_inventory"]["incident_count"]
            ):
                raise ValueError(f"Stored review decision summary mismatch: {source_id}")
            counts[row["verdict"]] += 1
            current_decisions.append(
                {
                    "source_id": source_id,
                    "source_sha256": source["sha256"],
                    "decision_sha256": row["decision_sha256"],
                }
            )
            if row["verdict"] != "supported":
                continue

            scene_inventory = decision["scene_inventory"]
            article_scope = decision["scope"]["scope_verdict"]
            location_incidents: dict[str, list[str]] = {
                location["location_id"]: []
                for location in scene_inventory["formal_locations"]
            }
            for incident in scene_inventory["incidents"]:
                for location_id in incident["formal_location_ids"]:
                    location_incidents[location_id].append(incident["incident_id"])
            for location in scene_inventory["formal_locations"]:
                if (
                    article_scope in {"in_city", "mixed"}
                    and location["city_scope"] == "in_city"
                ):
                    request = {
                        "source_id": source_id,
                        "source_url": source["url"],
                        "source_sha256": source["sha256"],
                        "decision_sha256": row["decision_sha256"],
                        "location_id": location["location_id"],
                        "incident_ids": location_incidents[location["location_id"]],
                        "label": location["label"],
                        "role": location["role"],
                        "precision": location["precision"],
                        "city_scope": location["city_scope"],
                        "evidence_quotes": location["evidence_quotes"],
                        "coordinates": location["coordinates"],
                        "geometry_task": _geometry_task(location),
                    }
                    for key in ("transit_route", "poi_contexts", "poi_review", "transit_review"):
                        if key in location:
                            request[key] = location[key]
                    if "source_reference_binding" in decision:
                        request["source_reference_binding"] = decision["source_reference_binding"]
                    if "source_document_binding" in decision:
                        request["source_document_binding"] = decision["source_document_binding"]
                    if "source_attachment_binding" in decision:
                        request["source_attachment_binding"] = decision["source_attachment_binding"]
                    request["geometry_request_sha256"] = _digest(request)
                    geometry_requests.append(request)
            articles.append(
                {
                    "source_id": source_id,
                    "source_url": source["url"],
                    "source_sha256": source["sha256"],
                    "decision_sha256": row["decision_sha256"],
                    "scope_verdict": article_scope,
                    "incident_count": scene_inventory["incident_count"],
                    "incidents": scene_inventory["incidents"],
                    "formal_locations": scene_inventory["formal_locations"],
                    **({"source_attachment_binding": decision["source_attachment_binding"]}
                       if "source_attachment_binding" in decision else {}),
                    **({"source_document_binding": decision["source_document_binding"]}
                       if "source_document_binding" in decision else {}),
                    **({"source_reference_binding": decision["source_reference_binding"]}
                       if "source_reference_binding" in decision else {}),
                    **({"source_review_decision": decision}
                       if "source_reference_binding" in decision else {}),
                }
            )

    source_records = coverage["discovered"]
    if sum(counts.values()) != source_records:
        raise ValueError("Scene inventory does not cover the source checkpoint")
    task_counts = Counter(row["geometry_task"] for row in geometry_requests)
    inventory_core = {
        "city": city,
        "decision_set_digest": _digest(current_decisions),
        "articles": articles,
        "geometry_requests": geometry_requests,
    }
    all_supported = source_records > 0 and counts["supported"] == source_records
    return {
        "schema_version": 1,
        **inventory_core,
        "inventory_digest": _digest(inventory_core),
        "coverage": coverage,
        "review_counts": dict(counts),
        "reviewed_articles": len(articles),
        "reviewed_incidents": sum(row["incident_count"] for row in articles),
        "reviewed_formal_locations": sum(
            len(row["formal_locations"]) for row in articles
        ),
        "in_city_geometry_requests": len(geometry_requests),
        "geometry_task_counts": dict(sorted(task_counts.items())),
        "all_current_reviews_supported": all_supported,
        "geometry_complete": all_supported and not geometry_requests,
        "owner_approval_required": True,
        "owner_approved": False,
        "publication_ready": False,
        "publication_blocks": [
            *([] if all_supported else ["source_review_incomplete"]),
            *([] if not geometry_requests else ["checked_geometry_incomplete"]),
            "owner_approval_missing",
            "approved_map_build_absent",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--city",
        choices=[city for city in CANONICAL_CITY_SLUGS if city != "munich"],
        required=True,
    )
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    inventory = build_inventory(city=args.city, db_path=args.db)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    temporary.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(args.out)
    print(json.dumps({key: value for key, value in inventory.items() if key not in {
        "articles", "geometry_requests"
    }}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
