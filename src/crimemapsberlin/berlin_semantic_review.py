"""Fail-closed contract for the complete Berlin semantic re-review.

This module does not make narrative decisions.  It prepares source-first work
packets and validates decisions made after reading the current official body.
Unlike the generic city-review schema, an omitted event-time, transit or POI
field is never interpreted as an empty reviewed result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from .multiple_scenes import (
    EVENT_TIME_PRECISIONS,
    POI_CONTEXT_SCOPES,
    SCENE_PRECISIONS,
    SCENE_ROLES,
    TRANSIT_EXTENTS,
    TRANSIT_MODES,
)
from .source_review_pack import read_checkpoint

CITY = "berlin"
SCHEMA_VERSION = 1
FROZEN_ARTICLE_COUNT = 1100
LOCATION_SCOPES = {"in_city", "out_of_city", "uncertain"}
TIME_STATUSES = {"sourced", "reviewed_unknown"}
TRANSIT_STATUSES = {
    "not_applicable",
    "reviewed_non_transit_route",
    "reviewed_route",
}
SIX_RULE_KEYS = {
    "discovery_role_checked",
    "moving_transit_checked",
    "all_independent_events_checked",
    "original_event_times_checked",
    "all_location_roles_checked",
    "poi_context_only_checked",
}
POI_KIND = re.compile(r"^[a-z][a-z0-9_:-]*$")


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _normalized(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _exact_keys(value: object, expected: set[str], label: str) -> dict:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    missing = expected - set(value)
    extra = set(value) - expected
    if missing or extra:
        raise ValueError(f"{label} has missing fields {sorted(missing)} or unknown fields {sorted(extra)}")
    return value


def _quotes(value: object, body: str, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} needs source evidence")
    result = []
    for raw in value:
        quote = _normalized(raw)
        if len(quote) < 15 or quote not in body:
            raise ValueError(f"{label} evidence is absent from the current source body")
        result.append(quote)
    if len(result) != len(set(result)):
        raise ValueError(f"{label} contains duplicate evidence")
    return result


def _reviewed_at(value: object, label: str) -> str:
    text = _normalized(value)
    if not text:
        raise ValueError(f"{label} needs reviewed_at")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{label} has invalid reviewed_at") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} reviewed_at must include a timezone")
    return text


def _event_time(value: object, body: str, label: str) -> dict:
    item = _exact_keys(
        value,
        {"status", "display", "date", "precision", "evidence_quotes", "review_note"},
        label,
    )
    status = item["status"]
    note = _normalized(item["review_note"])
    if status not in TIME_STATUSES or not note:
        raise ValueError(f"{label} needs an explicit time-review status and note")
    evidence = _quotes(item["evidence_quotes"], body, label)
    display = _normalized(item["display"])
    precision = item["precision"]
    event_date = item["date"]
    if status == "reviewed_unknown":
        if display or event_date is not None or precision != "unknown":
            raise ValueError(f"{label} reviewed_unknown must not invent a time")
    else:
        if not display or precision not in EVENT_TIME_PRECISIONS - {"unknown"}:
            raise ValueError(f"{label} sourced time is incomplete")
        if event_date is not None:
            if not isinstance(event_date, str):
                raise ValueError(f"{label} has invalid event date")
            try:
                datetime.fromisoformat(event_date)
            except ValueError as exc:
                raise ValueError(f"{label} has invalid event date") from exc
    return {
        "status": status,
        "display": display,
        "date": event_date,
        "precision": precision,
        "evidence_quotes": evidence,
        "review_note": note,
    }


def _transit_review(value: object, body: str, precision: str, label: str) -> dict:
    item = _exact_keys(
        value,
        {"status", "mode", "line", "extent", "evidence_quotes", "review_note"},
        label,
    )
    status = item["status"]
    note = _normalized(item["review_note"])
    if status not in TRANSIT_STATUSES or not note:
        raise ValueError(f"{label} needs an explicit transit-review status and note")
    evidence = _quotes(item["evidence_quotes"], body, label)
    mode = item["mode"]
    line = _normalized(item["line"])
    extent = item["extent"]
    if status == "not_applicable":
        if precision == "route" or any(value is not None for value in (mode, extent)) or line:
            raise ValueError(f"{label} not_applicable conflicts with route data")
    elif status == "reviewed_non_transit_route":
        if precision != "route" or any(value is not None for value in (mode, extent)) or line:
            raise ValueError(f"{label} non-transit route review is inconsistent")
    elif precision != "route" or mode not in TRANSIT_MODES or not line or extent not in TRANSIT_EXTENTS:
        raise ValueError(f"{label} reviewed route is incomplete")
    return {
        "status": status,
        "mode": mode,
        "line": line,
        "extent": extent,
        "evidence_quotes": evidence,
        "review_note": note,
    }


def _poi_contexts(value: object, body: str, label: str) -> list[dict]:
    if not isinstance(value, list):
        raise TypeError(f"{label} must be an explicitly reviewed list")
    result = []
    seen = set()
    for number, raw in enumerate(value, start=1):
        item_label = f"{label} item {number}"
        item = _exact_keys(
            raw,
            {"kind", "scope", "radius_m", "evidence_quotes", "review_note"},
            item_label,
        )
        kind = item["kind"]
        scope = item["scope"]
        radius = item["radius_m"]
        note = _normalized(item["review_note"])
        key = (kind, scope, radius)
        if (
            not isinstance(kind, str)
            or not POI_KIND.fullmatch(kind)
            or scope not in POI_CONTEXT_SCOPES
            or type(radius) not in {int, float}
            or not 0 <= radius <= 500
            or (scope == "near_geometry" and radius == 0)
            or (scope != "near_geometry" and radius != 0)
            or not note
            or key in seen
        ):
            raise ValueError(f"{item_label} is invalid")
        seen.add(key)
        result.append(
            {
                "kind": kind,
                "scope": scope,
                "radius_m": radius,
                "evidence_quotes": _quotes(item["evidence_quotes"], body, item_label),
                "review_note": note,
                "association": "source_reviewed_context_only",
            }
        )
    return result


def validate_article(value: object, source: dict, prior_audit: dict) -> dict:
    """Validate one current-body-bound article review under all six owner rules."""
    item = _exact_keys(
        value,
        {
            "schema_version",
            "city",
            "source_id",
            "source_url",
            "source_sha256",
            "reviewer",
            "reviewed_at",
            "source_read_complete",
            "six_rule_checks",
            "announcement_kind",
            "event_relationship",
            "minimum_independent_events",
            "incidents_complete",
            "formal_locations_complete",
            "event_times_complete",
            "transit_review_complete",
            "poi_context_review_complete",
            "incidents",
            "formal_locations",
            "linked_source_ids",
            "uncertainty",
        },
        f"Berlin review {source['source_id']}",
    )
    ident = source["source_id"]
    label = f"Berlin review {ident}"
    if (
        item["schema_version"] != SCHEMA_VERSION
        or item["city"] != CITY
        or item["source_id"] != ident
        or item["source_url"] != source["source_url"]
        or item["source_sha256"] != source["source_sha256"]
    ):
        raise ValueError(f"{label} has stale or mismatched source identity")
    if item["source_read_complete"] is not True:
        raise ValueError(f"{label} does not declare the current body fully read")
    checks = _exact_keys(item["six_rule_checks"], SIX_RULE_KEYS, f"{label} six rules")
    if any(checks[key] is not True for key in SIX_RULE_KEYS):
        raise ValueError(f"{label} has an incomplete six-rule review")
    for field in (
        "incidents_complete",
        "formal_locations_complete",
        "event_times_complete",
        "transit_review_complete",
        "poi_context_review_complete",
    ):
        if item[field] is not True:
            raise ValueError(f"{label} does not declare {field}")
    reviewer = _normalized(item["reviewer"])
    announcement_kind = _normalized(item["announcement_kind"])
    relationship = _normalized(item["event_relationship"])
    if not reviewer or not announcement_kind or not relationship:
        raise ValueError(f"{label} needs reviewer and narrative classification")
    minimum = item["minimum_independent_events"]
    audit_minimum = prior_audit.get("minimum_independent_events")
    if type(minimum) is not int or minimum < 0 or minimum != audit_minimum:
        raise ValueError(f"{label} changed the source-first audit minimum")
    body = _normalized(source["source_body"])

    locations = item["formal_locations"]
    if not isinstance(locations, list):
        raise TypeError(f"{label} formal_locations must be a list")
    normalized_locations = []
    location_ids = set()
    for number, raw in enumerate(locations, start=1):
        location_label = f"{label} location {number}"
        location = _exact_keys(
            raw,
            {
                "location_id",
                "label",
                "role",
                "precision",
                "city_scope",
                "evidence_quotes",
                "details",
                "event_time_review",
                "transit_review",
                "poi_contexts",
            },
            location_label,
        )
        location_id = location["location_id"]
        if (
            not isinstance(location_id, str)
            or not location_id.startswith(f"{ident}:location:")
            or location_id in location_ids
        ):
            raise ValueError(f"{location_label} has an invalid or duplicate ID")
        location_ids.add(location_id)
        name = _normalized(location["label"])
        details = _normalized(location["details"])
        if not name or not details:
            raise ValueError(f"{location_label} needs a label and details")
        role = location["role"]
        precision = location["precision"]
        if role not in SCENE_ROLES or precision not in SCENE_PRECISIONS:
            raise ValueError(f"{location_label} has an invalid role or precision")
        if location["city_scope"] not in LOCATION_SCOPES:
            raise ValueError(f"{location_label} has invalid city scope")
        normalized_locations.append(
            {
                "location_id": location_id,
                "label": name,
                "role": role,
                "precision": precision,
                "city_scope": location["city_scope"],
                "evidence_quotes": _quotes(location["evidence_quotes"], body, location_label),
                "details": details,
                "event_time_review": _event_time(location["event_time_review"], body, location_label),
                "transit_review": _transit_review(
                    location["transit_review"], body, precision, location_label
                ),
                "poi_contexts": _poi_contexts(
                    location["poi_contexts"], body, f"{location_label} POI contexts"
                ),
            }
        )

    incidents = item["incidents"]
    if not isinstance(incidents, list) or len(incidents) < minimum:
        raise ValueError(f"{label} omits independent events from the prior source audit")
    normalized_incidents = []
    incident_ids = set()
    for number, raw in enumerate(incidents, start=1):
        incident_label = f"{label} incident {number}"
        incident = _exact_keys(
            raw,
            {
                "incident_id",
                "evidence_quotes",
                "formal_location_ids",
                "details",
                "event_time_review",
            },
            incident_label,
        )
        incident_id = incident["incident_id"]
        if (
            not isinstance(incident_id, str)
            or not incident_id.startswith(f"{ident}:incident:")
            or incident_id in incident_ids
        ):
            raise ValueError(f"{incident_label} has an invalid or duplicate ID")
        incident_ids.add(incident_id)
        references = incident["formal_location_ids"]
        if (
            not isinstance(references, list)
            or any(ref not in location_ids for ref in references)
            or len(references) != len(set(references))
        ):
            raise ValueError(f"{incident_label} has invalid location references")
        details = _normalized(incident["details"])
        if not details:
            raise ValueError(f"{incident_label} needs event details")
        normalized_incidents.append(
            {
                "incident_id": incident_id,
                "evidence_quotes": _quotes(incident["evidence_quotes"], body, incident_label),
                "formal_location_ids": references,
                "details": details,
                "event_time_review": _event_time(incident["event_time_review"], body, incident_label),
            }
        )

    linked = item["linked_source_ids"]
    uncertainty = item["uncertainty"]
    if (
        not isinstance(linked, list)
        or any(not isinstance(value, str) or not value for value in linked)
        or len(linked) != len(set(linked))
        or not isinstance(uncertainty, list)
        or any(not _normalized(value) for value in uncertainty)
    ):
        raise ValueError(f"{label} has invalid links or uncertainty notes")
    return {
        **{key: item[key] for key in ("schema_version", "city", "source_id", "source_url", "source_sha256")},
        "reviewer": reviewer,
        "reviewed_at": _reviewed_at(item["reviewed_at"], label),
        "source_read_complete": True,
        "six_rule_checks": {key: True for key in sorted(SIX_RULE_KEYS)},
        "announcement_kind": announcement_kind,
        "event_relationship": relationship,
        "minimum_independent_events": minimum,
        "incidents_complete": True,
        "formal_locations_complete": True,
        "event_times_complete": True,
        "transit_review_complete": True,
        "poi_context_review_complete": True,
        "incidents": normalized_incidents,
        "formal_locations": normalized_locations,
        "linked_source_ids": linked,
        "uncertainty": [_normalized(value) for value in uncertainty],
    }


def _audit_index(audit_root: Path) -> dict[str, dict]:
    rows = []
    for path in sorted(audit_root.glob("source-[0-9][0-9][0-9].json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows.extend(payload.get("items", []))
    crosslink = audit_root / "source-crosslink-001.json"
    if crosslink.is_file():
        rows.extend(json.loads(crosslink.read_text(encoding="utf-8")).get("items", []))
    indexed = {str(row.get("id")): row for row in rows if isinstance(row, dict)}
    if len(rows) != FROZEN_ARTICLE_COUNT or len(indexed) != FROZEN_ARTICLE_COUNT:
        raise ValueError("Prior Berlin source audit must contain 1,100 unique articles")
    return indexed


def frozen_sources(db_path: Path, audit_root: Path) -> tuple[list[dict], dict[str, dict]]:
    sources, _coverage = read_checkpoint(db_path)
    source_by_id = {row["source_id"]: row for row in sources}
    audit = _audit_index(audit_root)
    missing = set(audit) - set(source_by_id)
    if missing:
        raise ValueError(f"Current checkpoint is missing frozen sources: {sorted(missing)[:5]}")
    frozen = [source_by_id[ident] for ident in sorted(audit)]
    return frozen, audit


def prepare_packets(*, db_path: Path, audit_root: Path, out_dir: Path, batch_size: int = 10) -> dict:
    """Write ignored raw-body work packets; all decisions remain pending."""
    if not 1 <= batch_size <= 25:
        raise ValueError("Berlin semantic review batch size must be from 1 to 25")
    sources, audit = frozen_sources(db_path, audit_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    packet_hashes = {}
    for number, start in enumerate(range(0, len(sources), batch_size), start=1):
        path = out_dir / f"source-review-{number:04d}.json"
        articles = []
        for source in sources[start : start + batch_size]:
            ident = source["source_id"]
            articles.append(
                {
                    "source": source,
                    "prior_source_audit": audit[ident],
                    "decision_status": "pending",
                }
            )
        payload = {
            "schema_version": SCHEMA_VERSION,
            "city": CITY,
            "batch": number,
            "articles": articles,
        }
        path.write_bytes(_json_bytes(payload) + b"\n")
        packet_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "city": CITY,
        "frozen_articles": len(sources),
        "batch_size": batch_size,
        "batches": len(packet_hashes),
        "source_ids_sha256": _digest([source["source_id"] for source in sources]),
        "packet_sha256": packet_hashes,
        "reviewed_articles": 0,
        "pending_articles": len(sources),
        "owner_approved": False,
        "publication_ready": False,
    }
    manifest_path = out_dir / "MANIFEST.json"
    manifest_path.write_bytes(_json_bytes(manifest) + b"\n")
    return manifest


def validate_review_parts(
    *, db_path: Path, audit_root: Path, reviews_dir: Path, require_complete: bool
) -> dict:
    sources, audit = frozen_sources(db_path, audit_root)
    source_by_id = {row["source_id"]: row for row in sources}
    decisions = {}
    errors = []
    for path in sorted(reviews_dir.glob("review-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        articles = payload.get("articles") if isinstance(payload, dict) else None
        if not isinstance(articles, list):
            errors.append(f"{path.name}: missing article list")
            continue
        for raw in articles:
            ident = raw.get("source_id") if isinstance(raw, dict) else None
            if not isinstance(ident, str) or ident not in source_by_id or ident in decisions:
                errors.append(f"{path.name}: invalid, unknown or duplicate source_id {ident!r}")
                continue
            try:
                decisions[ident] = validate_article(raw, source_by_id[ident], audit[ident])
            except (TypeError, ValueError) as exc:
                errors.append(f"{path.name}:{ident}: {exc}")
    pending = sorted(set(source_by_id) - set(decisions))
    if require_complete and pending:
        errors.append(f"complete validation has {len(pending)} pending articles")
    return {
        "schema_version": SCHEMA_VERSION,
        "city": CITY,
        "frozen_articles": len(sources),
        "reviewed_articles": len(decisions),
        "pending_articles": len(pending),
        "pending_source_ids": pending,
        "errors": errors,
        "passed": not errors,
        "complete": not errors and not pending,
        "decision_set_sha256": _digest([decisions[key] for key in sorted(decisions)]),
        "owner_approved": False,
        "publication_ready": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    validate = subparsers.add_parser("validate")
    for child in (prepare, validate):
        child.add_argument("--db", type=Path, required=True)
        child.add_argument("--audit-root", type=Path, required=True)
    prepare.add_argument("--out", type=Path, required=True)
    prepare.add_argument("--batch-size", type=int, default=10)
    validate.add_argument("--reviews-dir", type=Path, required=True)
    validate.add_argument("--require-complete", action="store_true")
    validate.add_argument("--status-out", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare_packets(
            db_path=args.db,
            audit_root=args.audit_root,
            out_dir=args.out,
            batch_size=args.batch_size,
        )
    else:
        result = validate_review_parts(
            db_path=args.db,
            audit_root=args.audit_root,
            reviews_dir=args.reviews_dir,
            require_complete=args.require_complete,
        )
        if args.status_out:
            runtime = (Path.cwd() / ".runtime").resolve()
            output = args.status_out.resolve()
            if not output.is_relative_to(runtime):
                parser.error("Berlin semantic review status must remain under .runtime/")
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_suffix(output.suffix + ".tmp")
            temporary.write_bytes(_json_bytes(result) + b"\n")
            temporary.replace(output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "validate" and not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
