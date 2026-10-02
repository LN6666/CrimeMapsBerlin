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
from collections import Counter
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
from .source_supplements import validate_source_supplements

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


def _source_explicit_additions(
    value: object, item: dict, before_ids: set[str], before_locations: set[str],
    body: str, label: str,
) -> list[dict]:
    """Require individual evidence for every genuinely new phase/context.

    Lowering an overcount must not discard another explicit source phase. This
    narrow extension does not accept inferred events or newly chosen geometry:
    each addition is declared by immutable ID with that row's exact evidence,
    and new location contexts must remain unlocated and without POI/transit.
    """
    incidents = {r.get("incident_id"): r for r in item["incidents"] if isinstance(r, dict)}
    locations = {r.get("location_id"): r for r in item["formal_locations"] if isinstance(r, dict)}
    expected = ({("incident", ident) for ident in set(incidents) - before_ids}
                | {("formal_location", ident) for ident in set(locations) - before_locations})
    if not isinstance(value, list) or not value or not expected:
        raise ValueError(f"{label} needs individual proof of actual source-explicit additions")
    declarations = []
    seen = set()
    for number, raw in enumerate(value, start=1):
        entry_label = f"{label} addition {number}"
        entry = _exact_keys(raw, {"kind", "record_id", "evidence_quotes", "review_note"}, entry_label)
        kind, ident = entry["kind"], entry["record_id"]
        if kind not in {"incident", "formal_location"} or not isinstance(ident, str):
            raise ValueError(f"{entry_label} has an invalid record identity")
        key = (kind, ident)
        if key in seen or key not in expected:
            raise ValueError(f"{entry_label} is duplicate or does not identify a new record")
        seen.add(key)
        row = (incidents if kind == "incident" else locations)[ident]
        evidence = _quotes(entry["evidence_quotes"], body, entry_label)
        if evidence != _quotes(row.get("evidence_quotes"), body, entry_label):
            raise ValueError(f"{entry_label} evidence differs from the added source record")
        note = _normalized(entry["review_note"])
        if not note:
            raise ValueError(f"{entry_label} needs a source-based addition judgment")
        if kind == "formal_location":
            if (row.get("precision") != "unknown" or row.get("poi_contexts") != []
                    or not isinstance(row.get("transit_review"), dict)
                    or row["transit_review"].get("status") != "not_applicable"
                    or not any(ident in r.get("formal_location_ids", []) for r in incidents.values())):
                raise ValueError(f"{entry_label} must be an unlocated linked context without POI or transit")
        declarations.append({**entry, "evidence_quotes": evidence, "review_note": note})
    if seen != expected:
        raise ValueError(f"{label} must declare exactly all source-explicit additions")
    return declarations


def _minimum_correction(value: object, item: dict, source: dict, prior_audit: dict) -> dict:
    """Accept an explicit, recoverable source-backed correction, never a bare cut.

    An earlier audit can itself overcount inferred actions. Preserve its exact
    accepted review and all quoted evidence while allowing an identified
    unsupported incident row to be removed. Locations are retained unless an
    explicit retirement lists unlocated synthetic slots linked only to removed
    incidents; their originals remain in the hash-bound superseded review.
    Separately sourced omitted phases and unknown contexts may be added only
    with individual exact-body evidence declarations. This is a judgment
    supplied by the reviewer, not a programmatic inference from wound keywords.
    """
    label = f"Berlin review {source['source_id']} minimum correction"
    correction = _exact_keys(value, {
        "prior_audit_sha256", "prior_minimum", "corrected_minimum",
        "superseded_review_file", "superseded_review_sha256",
        "removed_incident_ids", "evidence_quotes", "review_note",
        "reviewer", "reviewed_at",
    } | ({key for key in ("retired_formal_location_ids", "source_explicit_additions")
          if isinstance(value, dict) and key in value}), label)
    prior_minimum = prior_audit.get("minimum_independent_events")
    corrected_minimum = correction["corrected_minimum"]
    if (
        correction["prior_audit_sha256"] != _digest(prior_audit)
        or type(correction["prior_minimum"]) is not int
        or correction["prior_minimum"] != prior_minimum
        or type(corrected_minimum) is not int
        or not 0 <= corrected_minimum < prior_minimum
        or corrected_minimum != item["minimum_independent_events"]
    ):
        raise ValueError(f"{label} differs from the bound prior audit or corrected minimum")
    filename = _normalized(correction["superseded_review_file"])
    if not filename:
        raise ValueError(f"{label} needs the superseded review")
    path = Path(filename)
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != correction["superseded_review_sha256"]:
        raise ValueError(f"{label} superseded review is missing or has a hash mismatch")
    previous = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(previous, dict) or "minimum_event_count_correction" in previous:
        raise ValueError(f"{label} requires the original accepted review, not a nested correction")
    accepted = validate_article(previous, source, prior_audit)
    if not isinstance(item["incidents"], list) or not isinstance(item["formal_locations"], list):
        raise TypeError(f"{label} requires explicit retained incidents and locations")
    before_ids = {row["incident_id"] for row in accepted["incidents"]}
    after_ids = {row.get("incident_id") for row in item["incidents"] if isinstance(row, dict)}
    before_locations = {row["location_id"]: row for row in accepted["formal_locations"]}
    after_locations = {row.get("location_id") for row in item["formal_locations"] if isinstance(row, dict)}
    body = _normalized(source["source_body"])
    additions = None
    if "source_explicit_additions" in correction:
        additions = _source_explicit_additions(correction["source_explicit_additions"], item,
                                              before_ids, set(before_locations), body, label)
    removed = correction["removed_incident_ids"]
    if (
        not isinstance(removed, list) or not removed
        or any(not isinstance(ident, str) for ident in removed)
        or len(removed) != len(set(removed))
        or set(removed) != before_ids - after_ids
        or (not after_ids <= before_ids and additions is None)
    ):
        raise ValueError(f"{label} does not identify exactly the removed incidents")
    retired = correction.get("retired_formal_location_ids", [])
    if (
        not isinstance(retired, list)
        or ("retired_formal_location_ids" in correction and not retired)
        or any(not isinstance(ident, str) for ident in retired)
        or len(retired) != len(set(retired))
        or set(before_locations) - after_locations != set(retired)
        or (not after_locations <= set(before_locations) and additions is None)
    ):
        raise ValueError(f"{label} must retain all locations or exactly list retired synthetic locations")
    for ident in retired:
        location = before_locations[ident]
        linked = {row["incident_id"] for row in accepted["incidents"]
                  if ident in row["formal_location_ids"]}
        if (
            location["role"] != "unknown" or location["precision"] != "unknown"
            or location["poi_contexts"] or location["transit_review"]["status"] != "not_applicable"
            or not linked or not linked <= set(removed)
        ):
            raise ValueError(f"{label} retirement is not an unlocated synthetic slot of removed incidents")
    evidence = _quotes(correction["evidence_quotes"], body, label)
    retained = set(evidence)
    for row in item["incidents"]:
        if isinstance(row, dict):
            retained.update(_quotes(row.get("evidence_quotes"), body, label))
    for row in item["formal_locations"]:
        if isinstance(row, dict):
            retained.update(_quotes(row.get("evidence_quotes"), body, label))
    if not {quote for row in accepted["incidents"] for quote in row["evidence_quotes"]} <= retained:
        raise ValueError(f"{label} loses previously reviewed incident evidence")
    if not {quote for ident in retired for quote in before_locations[ident]["evidence_quotes"]} <= retained:
        raise ValueError(f"{label} loses retired synthetic-location evidence")
    note = _normalized(correction["review_note"])
    reviewer = _normalized(correction["reviewer"])
    reviewed_at = _reviewed_at(correction["reviewed_at"], label)
    if not note or reviewer != _normalized(item["reviewer"]) or reviewed_at != item["reviewed_at"]:
        raise ValueError(f"{label} needs a current reviewer, review time and correction note")
    result = {**correction, "superseded_review_file": filename, "evidence_quotes": evidence,
              "review_note": note, "reviewer": reviewer, "reviewed_at": reviewed_at}
    if additions is not None:
        result["source_explicit_additions"] = additions
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
        } | ({key for key in ("source_supplement_refs", "minimum_event_count_correction")
              if isinstance(value, dict) and key in value}),
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
    if type(minimum) is not int or minimum < 0:
        raise ValueError(f"{label} changed the source-first audit minimum")
    correction = None
    if "minimum_event_count_correction" in item:
        correction = _minimum_correction(item["minimum_event_count_correction"], item, source, prior_audit)
    elif minimum != audit_minimum:
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
    result = {
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
    if "source_supplement_refs" in item:
        result["source_supplement_reviews"] = validate_source_supplements(
            item["source_supplement_refs"], source, quotes=_quotes,
            event_time=_event_time, reviewed_at=_reviewed_at,
        )
    if correction is not None:
        result["minimum_event_count_correction"] = correction
    return result


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


def _validated_parts(
    *, db_path: Path, audit_root: Path, reviews_dir: Path
) -> tuple[list[dict], dict[str, dict], list[str]]:
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
    return sources, decisions, errors


def validate_review_parts(
    *, db_path: Path, audit_root: Path, reviews_dir: Path, require_complete: bool
) -> dict:
    sources, decisions, errors = _validated_parts(
        db_path=db_path, audit_root=audit_root, reviews_dir=reviews_dir
    )
    pending = sorted({row["source_id"] for row in sources} - set(decisions))
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


def _display_time(review: dict) -> dict:
    """Adapt an already reviewed time without assigning a missing date."""
    return {
        "display": review["display"] or "Originalzeit in der Quelle nicht angegeben (geprüft)",
        "date": review["date"],
        "precision": review["precision"],
        "evidence_quote": review["evidence_quotes"][0],
    }


def build_geometry_inventory(*, db_path: Path, audit_root: Path, reviews_dir: Path) -> dict:
    """Export only complete current six-rule decisions, without touching a ledger.

    This is serialization of explicit review choices, not a second narrative
    analysis, geocoder, category classifier or geometry/count decision. Unknown
    dates, source scope and unlocated scenes remain explicit. Both the full
    review and the browser-compatible time representation survive the handoff.
    """
    sources, decisions, errors = _validated_parts(
        db_path=db_path, audit_root=audit_root, reviews_dir=reviews_dir
    )
    pending = sorted({row["source_id"] for row in sources} - set(decisions))
    if errors or pending:
        raise ValueError(
            f"Geometry inventory requires complete valid Berlin review: "
            f"{len(pending)} pending; {'; '.join(errors[:3])}"
        )
    articles, requests, current_decisions = [], [], []
    for ident, review in sorted(decisions.items()):
        decision_sha = _digest(review)
        locations = []
        for raw in review["formal_locations"]:
            location = {
                **raw,
                "coordinates": None,
                "event_time": _display_time(raw["event_time_review"]),
                "poi_contexts": [
                    {**context, "evidence_quote": context["evidence_quotes"][0]}
                    for context in raw["poi_contexts"]
                ],
            }
            transit = raw["transit_review"]
            if transit["status"] == "reviewed_route":
                location["transit_route"] = {
                    key: transit[key] for key in ("mode", "line", "extent")
                }
                location["transit_route"]["evidence_quote"] = transit["evidence_quotes"][0]
            locations.append(location)
        incidents = [
            {**raw, "event_time": _display_time(raw["event_time_review"])}
            for raw in review["incidents"]
        ]
        scopes = {location["city_scope"] for location in locations}
        scope = (
            ("in_city" if scopes == {"in_city"} else "mixed")
            if "in_city" in scopes
            else ("out_of_city" if scopes == {"out_of_city"} else "uncertain")
        )
        article = {
            "source_id": ident,
            "source_url": review["source_url"],
            "source_sha256": review["source_sha256"],
            "decision_sha256": decision_sha,
            "scope_verdict": scope,
            "scope_basis": "explicit_reviewed_location_scopes_only",
            "incident_count": len(incidents),
            "incident_count_basis": "reviewed_episode_records_not_independent_offence_total",
            "incidents": incidents,
            "formal_locations": locations,
            "audit": {
                key: review[key] for key in (
                    "announcement_kind", "event_relationship", "minimum_independent_events",
                    "uncertainty", "linked_source_ids", "six_rule_checks", "reviewer", "reviewed_at",
                )
            },
        }
        if "source_supplement_reviews" in review:
            article["audit"]["source_supplement_reviews"] = review["source_supplement_reviews"]
        if "minimum_event_count_correction" in review:
            article["audit"]["minimum_event_count_correction"] = review["minimum_event_count_correction"]
        articles.append(article)
        current_decisions.append({
            "source_id": ident, "source_sha256": review["source_sha256"],
            "decision_sha256": decision_sha,
        })
        for location in locations:
            if location["city_scope"] != "in_city":
                continue
            precision = location["precision"]
            task = {
                "point": "checked_point_geocode_required",
                "address": "checked_point_geocode_required",
                "place": "checked_point_geocode_required",
                "street": "checked_road_geometry_required",
                "route": (
                    "checked_transit_route_geometry_required"
                    if location["transit_review"]["status"] == "reviewed_route"
                    else "checked_non_transit_route_geometry_required"
                ),
                "area": "checked_area_geometry_required",
                "district": "checked_district_geometry_required",
                "unknown": "unresolved_no_geometry",
            }[precision]
            request = {
                "source_id": ident,
                "source_url": review["source_url"],
                "source_sha256": review["source_sha256"],
                "decision_sha256": decision_sha,
                "incident_ids": [
                    incident["incident_id"] for incident in incidents
                    if location["location_id"] in incident["formal_location_ids"]
                ],
                **{key: location[key] for key in (
                    "location_id", "label", "role", "precision", "city_scope",
                    "evidence_quotes", "coordinates", "event_time", "event_time_review",
                    "transit_review", "poi_contexts", "details",
                )},
                "geometry_task": task,
            }
            if "transit_route" in location:
                request["transit_route"] = location["transit_route"]
            request["geometry_request_sha256"] = _digest(request)
            requests.append(request)
    core = {
        "city": CITY,
        "decision_set_digest": _digest(current_decisions),
        "semantic_review_decision_set_sha256": _digest([decisions[key] for key in sorted(decisions)]),
        "articles": articles,
        "geometry_requests": requests,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        **core,
        "inventory_digest": _digest(core),
        "coverage": {
            "discovered": len(sources), "bodies_in_pack": len(sources),
            "missing_bodies": 0, "source_errors": 0,
            "scope": "frozen_owner_batch_not_full_crime_inventory",
        },
        "review_counts": {"supported": len(articles), "pending": 0, "stale": 0,
                          "needs_correction": 0, "uncertain": 0},
        "reviewed_articles": len(articles),
        "reviewed_incidents": sum(article["incident_count"] for article in articles),
        "incident_count_basis": "reviewed_episode_records_not_independent_offence_total",
        "reviewed_formal_locations": sum(len(article["formal_locations"]) for article in articles),
        "in_city_geometry_requests": len(requests),
        "geometry_task_counts": dict(sorted(Counter(row["geometry_task"] for row in requests).items())),
        "all_current_reviews_supported": True,
        "geometry_complete": not requests,
        "owner_approval_required": True, "owner_approved": False, "publication_ready": False,
        "publication_blocks": ["checked_geometry_incomplete", "map_review_incomplete",
                               "owner_approval_missing", "approved_map_build_absent"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    validate = subparsers.add_parser("validate")
    inventory = subparsers.add_parser("inventory")
    for child in (prepare, validate, inventory):
        child.add_argument("--db", type=Path, required=True)
        child.add_argument("--audit-root", type=Path, required=True)
    prepare.add_argument("--out", type=Path, required=True)
    prepare.add_argument("--batch-size", type=int, default=10)
    validate.add_argument("--reviews-dir", type=Path, required=True)
    validate.add_argument("--require-complete", action="store_true")
    validate.add_argument("--status-out", type=Path)
    inventory.add_argument("--reviews-dir", type=Path, required=True)
    inventory.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare_packets(
            db_path=args.db,
            audit_root=args.audit_root,
            out_dir=args.out,
            batch_size=args.batch_size,
        )
    elif args.command == "inventory":
        output = args.out.resolve()
        if not output.is_relative_to((Path.cwd() / ".runtime").resolve()):
            parser.error("Berlin semantic inventory must remain under .runtime/")
        result = build_geometry_inventory(
            db_path=args.db, audit_root=args.audit_root, reviews_dir=args.reviews_dir,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_bytes(_json_bytes(result) + b"\n")
        temporary.replace(output)
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
    print(json.dumps({key: value for key, value in result.items()
                      if key not in {"articles", "geometry_requests"}}, ensure_ascii=False, indent=2))
    if args.command == "validate" and not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
