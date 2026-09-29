"""Prepare and validate source-bound LLM decisions for reviewed city maps.

Source review decides which incidents and formal locations occur in an
announcement. Geometry review binds those locations to checked source
coordinates or OSM objects. This module adds the remaining narrative choices
needed by the browser map: category labels and, when defensible, the single
incident/location pair allowed to count for one announcement.

No category or primary scene is inferred here. The program only creates a
compact review input and validates an explicit LLM decision against the exact
source, source-review and geometry hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from .source_review_pack import read_checkpoint

SCHEMA_VERSION = 1
MAPPABLE_SCOPES = {"in_city", "mixed"}
CATEGORIES = {
    "betrug",
    "brand",
    "diebstahl",
    "drogen",
    "einbruch",
    "gewalt",
    "raub",
    "sexualdelikte",
    "sonstige",
    "verkehr",
}
COUNT_ROLES = {"incident", "accident"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")

ENVELOPE_KEYS = {
    "schema_version",
    "city",
    "inventory_digest",
    "geometry_ledger_sha256",
    "decisions",
}
DECISION_KEYS = {
    "schema_version",
    "city",
    "source_id",
    "source_sha256",
    "source_review_sha256",
    "article_category",
    "is_crime_report",
    "classification_evidence_quotes",
    "incident_categories",
    "primary_count_incident_id",
    "primary_count_location_id",
    "review_note",
    "reviewer",
    "reviewed_at",
}
INCIDENT_CATEGORY_KEYS = {
    "incident_id",
    "category",
    "evidence_quotes",
}


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _load(path: Path, label: str) -> dict:
    if not path.is_file():
        raise ValueError(f"{label} does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return value


def _exact_keys(value: object, expected: set[str], label: str) -> dict:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    missing = expected - set(value)
    extra = set(value) - expected
    if missing or extra:
        raise ValueError(f"{label} has missing fields {sorted(missing)} or unknown fields {sorted(extra)}")
    return value


def _normalized(value: str) -> str:
    return " ".join(value.split())


def _quotes(value: object, source_text: str, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} needs at least one evidence quote")
    result = []
    for quote in value:
        normalized = _normalized(quote) if isinstance(quote, str) else ""
        if len(normalized) < 15 or normalized not in source_text:
            raise ValueError(f"{label} contains evidence absent from the current source")
        result.append(normalized)
    if len(result) != len(set(result)):
        raise ValueError(f"{label} contains duplicate evidence quotes")
    return result


def _reviewed_at(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} needs an ISO reviewed_at value")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} has an invalid reviewed_at value") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} reviewed_at needs a timezone")
    return parsed.isoformat()


def _validate_inputs(inventory: dict, geometry_ledger: dict, city: str) -> None:
    if inventory.get("schema_version") != 1 or inventory.get("city") != city:
        raise ValueError("Scene inventory belongs to another city or schema")
    if not inventory.get("all_current_reviews_supported"):
        raise ValueError("Map decisions require complete supported source review")
    if (
        geometry_ledger.get("schema_version") != 1
        or geometry_ledger.get("city") != city
        or geometry_ledger.get("inventory_digest") != inventory.get("inventory_digest")
        or geometry_ledger.get("geometry_review_complete") is not True
        or geometry_ledger.get("pending_count") != 0
    ):
        raise ValueError("Map decisions require the complete current geometry ledger")
    geometry_core = {
        key: geometry_ledger.get(key)
        for key in (
            "schema_version",
            "city",
            "inventory_digest",
            "submitted_inventory_digest",
            "geometry_index_sha256",
            "decisions",
        )
    }
    if geometry_ledger.get("ledger_sha256") != _digest(geometry_core):
        raise ValueError("Geometry ledger digest does not match its current contents")


def _geometry_by_location(geometry_ledger: dict) -> dict[str, dict]:
    indexed = {}
    for number, row in enumerate(geometry_ledger.get("decisions", []), start=1):
        if not isinstance(row, dict) or not isinstance(row.get("request"), dict):
            raise TypeError(f"Geometry ledger row {number} is invalid")
        location_id = row["request"].get("location_id")
        if not isinstance(location_id, str) or location_id in indexed:
            raise ValueError("Geometry ledger has a missing or duplicate location ID")
        indexed[location_id] = row
    if len(indexed) != geometry_ledger.get("request_count"):
        raise ValueError("Geometry ledger request count is inconsistent")
    return indexed


def _count_point(row: dict | None) -> list[float] | None:
    if row is None or row.get("decision", {}).get("verdict") != "resolved":
        return None
    derived = row.get("derived_geometry")
    if not isinstance(derived, dict):
        return None
    count_geometry = derived.get("count_point")
    if count_geometry is None and derived.get("type") == "Point":
        count_geometry = derived.get("geometry")
    coordinates = count_geometry.get("coordinates") if isinstance(count_geometry, dict) else None
    if (
        not isinstance(coordinates, (list, tuple))
        or len(coordinates) < 2
        or any(type(value) not in {int, float} for value in coordinates[:2])
    ):
        return None
    return [coordinates[0], coordinates[1]]


def build_review_pack(*, city: str, source_db: Path, inventory: dict, geometry_ledger: dict) -> dict:
    """Return a compact local pack for LLM category and primary-scene review."""
    _validate_inputs(inventory, geometry_ledger, city)
    source_rows, coverage = read_checkpoint(source_db)
    sources = {row["source_id"]: row for row in source_rows}
    if len(sources) != len(source_rows):
        raise ValueError("Source checkpoint has duplicate IDs")
    geometry = _geometry_by_location(geometry_ledger)
    articles = []
    excluded = Counter()
    for article in inventory.get("articles", []):
        scope = article.get("scope_verdict")
        if scope not in MAPPABLE_SCOPES:
            excluded[str(scope)] += 1
            continue
        source_id = article.get("source_id")
        source = sources.get(source_id)
        if (
            source is None
            or source["source_sha256"] != article.get("source_sha256")
            or source["source_url"] != article.get("source_url")
        ):
            raise ValueError(f"Scene inventory is stale for source {source_id}")
        locations = []
        for location in article.get("formal_locations", []):
            geometry_row = geometry.get(location["location_id"])
            locations.append(
                {
                    **location,
                    "incident_ids": [
                        incident["incident_id"]
                        for incident in article.get("incidents", [])
                        if location["location_id"] in incident["formal_location_ids"]
                    ],
                    "geometry_verdict": (
                        geometry_row.get("decision", {}).get("verdict")
                        if geometry_row is not None
                        else "not_requested"
                    ),
                    "geometry_method": (
                        geometry_row.get("decision", {}).get("method") if geometry_row is not None else "none"
                    ),
                    "geometry_type": (
                        geometry_row.get("derived_geometry", {}).get("type")
                        if isinstance(geometry_row and geometry_row.get("derived_geometry"), dict)
                        else None
                    ),
                    "count_point_available": _count_point(geometry_row) is not None,
                }
            )
        articles.append(
            {
                "source_id": source_id,
                "source_url": source["source_url"],
                "source_sha256": source["source_sha256"],
                "source_review_sha256": article["decision_sha256"],
                "title": source["title"],
                "published": source["published"],
                "source_body": source["source_body"],
                "scope_verdict": scope,
                "incidents": article.get("incidents", []),
                "formal_locations": locations,
            }
        )
    core = {
        "schema_version": SCHEMA_VERSION,
        "city": city,
        "inventory_digest": inventory["inventory_digest"],
        "geometry_ledger_sha256": geometry_ledger["ledger_sha256"],
        "articles": articles,
    }
    return {
        **core,
        "review_pack_sha256": _digest(core),
        "source_coverage": coverage,
        "mappable_articles": len(articles),
        "excluded_scope_counts": dict(sorted(excluded.items())),
        "categories": sorted(CATEGORIES),
        "instructions": {
            "semantic_reviewer": "Read the complete source body; do not classify from keywords alone.",
            "incident_categories": "Classify every reviewed incident exactly once.",
            "primary_count": (
                "Choose zero or one incident/location pair. A primary location must be an in-city "
                "incident or accident location linked to that incident and must have an available "
                "checked count point. Other formal locations remain displayed without another count."
            ),
            "non_inference": (
                "Do not infer a venue, offence, location, motive or incident from nearby POIs or identity."
            ),
        },
        "decision_template": {
            "schema_version": SCHEMA_VERSION,
            "city": city,
            "source_id": "copy from article",
            "source_sha256": "copy from article",
            "source_review_sha256": "copy from article",
            "article_category": "one allowed category",
            "is_crime_report": True,
            "classification_evidence_quotes": ["verbatim source excerpt"],
            "incident_categories": [
                {
                    "incident_id": "copy from article incident",
                    "category": "one allowed category",
                    "evidence_quotes": ["verbatim source excerpt"],
                }
            ],
            "primary_count_incident_id": None,
            "primary_count_location_id": None,
            "review_note": "explain classification and primary selection",
            "reviewer": "reviewer identity",
            "reviewed_at": "ISO-8601 timestamp with timezone",
        },
    }


def compile_map_decisions(
    *,
    city: str,
    source_rows: list[dict],
    inventory: dict,
    geometry_ledger: dict,
    decision_envelope: dict,
) -> dict:
    """Validate explicit LLM map decisions without adding semantic choices."""
    _validate_inputs(inventory, geometry_ledger, city)
    envelope = _exact_keys(decision_envelope, ENVELOPE_KEYS, "map decision envelope")
    if (
        envelope["schema_version"] != SCHEMA_VERSION
        or envelope["city"] != city
        or envelope["inventory_digest"] != inventory["inventory_digest"]
        or envelope["geometry_ledger_sha256"] != geometry_ledger["ledger_sha256"]
    ):
        raise ValueError("Map decision envelope is stale or belongs to another city")
    raw_decisions = envelope["decisions"]
    if not isinstance(raw_decisions, list):
        raise TypeError("Map decisions must be a list")

    sources = {row["source_id"]: row for row in source_rows}
    if len(sources) != len(source_rows):
        raise ValueError("Source checkpoint has duplicate IDs")
    articles = {
        row["source_id"]: row
        for row in inventory.get("articles", [])
        if row.get("scope_verdict") in MAPPABLE_SCOPES
    }
    geometry = _geometry_by_location(geometry_ledger)
    compiled = []
    seen = set()
    category_counts: Counter = Counter()
    incident_category_counts: Counter = Counter()
    primary_count = 0
    for number, raw in enumerate(raw_decisions, start=1):
        label = f"map decision {number}"
        decision = _exact_keys(raw, DECISION_KEYS, label)
        source_id = decision["source_id"]
        if not isinstance(source_id, str) or source_id in seen or source_id not in articles:
            raise ValueError(f"{label} has a duplicate or unknown source_id")
        seen.add(source_id)
        article = articles[source_id]
        source = sources.get(source_id)
        if source is None:
            raise ValueError(f"{label} has no current source body")
        if (
            decision["schema_version"] != SCHEMA_VERSION
            or decision["city"] != city
            or decision["source_sha256"] != source["source_sha256"]
            or decision["source_sha256"] != article["source_sha256"]
            or decision["source_review_sha256"] != article["decision_sha256"]
        ):
            raise ValueError(f"{label} differs from the current source or source review")
        category = decision["article_category"]
        if category not in CATEGORIES or type(decision["is_crime_report"]) is not bool:
            raise ValueError(f"{label} has an invalid article classification")
        source_text = _normalized(f"{source['title']} {source['source_body']}")
        classification_quotes = _quotes(
            decision["classification_evidence_quotes"], source_text, f"{label} classification"
        )

        incident_rows = decision["incident_categories"]
        if not isinstance(incident_rows, list):
            raise TypeError(f"{label} incident_categories must be a list")
        incidents = {row["incident_id"]: row for row in article.get("incidents", [])}
        normalized_incidents = []
        incident_seen = set()
        for incident_number, raw_incident in enumerate(incident_rows, start=1):
            incident_label = f"{label} incident category {incident_number}"
            item = _exact_keys(raw_incident, INCIDENT_CATEGORY_KEYS, incident_label)
            incident_id = item["incident_id"]
            if incident_id in incident_seen or incident_id not in incidents:
                raise ValueError(f"{incident_label} has a duplicate or unknown incident_id")
            incident_seen.add(incident_id)
            if item["category"] not in CATEGORIES:
                raise ValueError(f"{incident_label} has an invalid category")
            evidence = _quotes(item["evidence_quotes"], source_text, incident_label)
            normalized_incidents.append(
                {
                    "incident_id": incident_id,
                    "category": item["category"],
                    "evidence_quotes": evidence,
                }
            )
            incident_category_counts[item["category"]] += 1
        if incident_seen != set(incidents):
            raise ValueError(f"{label} does not classify every reviewed incident exactly once")

        primary_incident = decision["primary_count_incident_id"]
        primary_location = decision["primary_count_location_id"]
        if (primary_incident is None) != (primary_location is None):
            raise ValueError(f"{label} primary incident and location must both be set or both be null")
        if primary_incident is not None:
            incident = incidents.get(primary_incident)
            locations = {row["location_id"]: row for row in article.get("formal_locations", [])}
            location = locations.get(primary_location)
            if (
                incident is None
                or location is None
                or primary_location not in incident["formal_location_ids"]
                or location["role"] not in COUNT_ROLES
                or location["city_scope"] != "in_city"
                or _count_point(geometry.get(primary_location)) is None
            ):
                raise ValueError(f"{label} selects a non-countable primary incident/location pair")
            primary_count += 1

        note = _normalized(decision["review_note"]) if isinstance(decision["review_note"], str) else ""
        reviewer = _normalized(decision["reviewer"]) if isinstance(decision["reviewer"], str) else ""
        if not note or not reviewer:
            raise ValueError(f"{label} needs a review note and reviewer")
        normalized = {
            **decision,
            "classification_evidence_quotes": classification_quotes,
            "incident_categories": normalized_incidents,
            "review_note": note,
            "reviewer": reviewer,
            "reviewed_at": _reviewed_at(decision["reviewed_at"], label),
        }
        compiled.append(
            {
                "decision": normalized,
                "map_decision_sha256": _digest(normalized),
            }
        )
        category_counts[category] += 1

    pending = len(articles) - len(compiled)
    core = {
        "schema_version": SCHEMA_VERSION,
        "city": city,
        "inventory_digest": inventory["inventory_digest"],
        "geometry_ledger_sha256": geometry_ledger["ledger_sha256"],
        "decisions": compiled,
    }
    return {
        **core,
        "ledger_sha256": _digest(core),
        "mappable_article_count": len(articles),
        "decision_count": len(compiled),
        "pending_count": pending,
        "category_counts": dict(sorted(category_counts.items())),
        "incident_category_counts": dict(sorted(incident_category_counts.items())),
        "primary_count": primary_count,
        "map_review_complete": pending == 0,
        "owner_approved": False,
        "publication_ready": False,
        "publication_blocks": [
            *([] if pending == 0 else ["map_semantic_review_incomplete"]),
            "owner_approval_missing",
            "approved_map_build_absent",
        ],
    }


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(_json_bytes(value) + b"\n")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("pack", "compile"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--city", required=True)
        sub.add_argument("--db", type=Path, required=True)
        sub.add_argument("--inventory", type=Path, required=True)
        sub.add_argument("--geometry-ledger", type=Path, required=True)
        sub.add_argument("--out", type=Path, required=True)
        if command == "compile":
            sub.add_argument("--decisions", type=Path, required=True)
    args = parser.parse_args()
    inventory = _load(args.inventory, "scene inventory")
    geometry_ledger = _load(args.geometry_ledger, "geometry ledger")
    if args.command == "pack":
        result = build_review_pack(
            city=args.city,
            source_db=args.db,
            inventory=inventory,
            geometry_ledger=geometry_ledger,
        )
    else:
        source_rows, _ = read_checkpoint(args.db)
        result = compile_map_decisions(
            city=args.city,
            source_rows=source_rows,
            inventory=inventory,
            geometry_ledger=geometry_ledger,
            decision_envelope=_load(args.decisions, "map decisions"),
        )
    _write(args.out, result)
    print(
        json.dumps(
            {key: value for key, value in result.items() if key not in {"articles", "decisions"}},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
