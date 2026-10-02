"""Import source-bound LLM review decisions without making semantic decisions.

The three input files mirror the output names promised by the source-review
pack. This module only checks identity, current source bytes, verbatim
evidence and structural completeness. It never infers scope, incidents or
locations and never grants owner approval or publication authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from .city_contract import paths_for
from .city_scope import SCOPE_VERDICTS
from .multiple_scenes import (
    SCENE_PRECISIONS,
    SCENE_ROLES,
    _validate_event_time,
    _validate_poi_contexts,
    _validate_transit,
)
from .source_review_pack import read_checkpoint_connection

SCHEMA_VERSION = 1
REVIEW_REQUIRED_CITIES = {"berlin", "hamburg", "cologne", "frankfurt"}
REVIEW_VERDICTS = {"supported", "needs_correction", "uncertain"}
LOCATION_SCOPES = {"in_city", "out_of_city", "uncertain"}
NO_POINT_PRECISIONS = {"street", "area", "district", "route", "unknown"}
SHA256 = re.compile(r"[0-9a-f]{64}")

IDENTITY_KEYS = {"schema_version", "city", "source_id", "source_url", "source_sha256"}
REVIEW_KEYS = IDENTITY_KEYS | {
    "verdict",
    "evidence_quotes",
    "review_note",
    "reviewer",
    "reviewed_at",
}
SCOPE_KEYS = IDENTITY_KEYS | {"scope_verdict", "evidence_quotes"}
SCENE_KEYS = IDENTITY_KEYS | {
    "incident_count",
    "incidents_complete",
    "formal_locations_complete",
    "incidents",
    "formal_locations",
}
INCIDENT_KEYS = {"incident_id", "evidence_quotes", "formal_location_ids"}
INCIDENT_OPTIONAL_KEYS = {"event_time", "details"}
LOCATION_KEYS = {
    "location_id",
    "label",
    "role",
    "precision",
    "city_scope",
    "evidence_quotes",
    "coordinates",
}
LOCATION_OPTIONAL_KEYS = {"transit_route", "poi_contexts", "poi_review", "transit_review"}
DECISION_KEYS = IDENTITY_KEYS | {"review", "scope", "scene_inventory"}


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _normalized(value: str) -> str:
    return " ".join(value.split())


def _require_exact_keys(value: object, expected: set[str], label: str) -> dict:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    missing = expected - set(value)
    extra = set(value) - expected
    if missing or extra:
        raise ValueError(
            f"{label} has missing fields {sorted(missing)} or unknown fields {sorted(extra)}"
        )
    return value


def _require_core_keys(
    value: object, required: set[str], optional: set[str], label: str
) -> dict:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    missing = required - set(value)
    extra = set(value) - required - optional
    if missing or extra:
        raise ValueError(
            f"{label} has missing fields {sorted(missing)} or unknown fields {sorted(extra)}"
        )
    return value


def _read_ndjson(path: Path, label: str) -> list[dict]:
    if not path.is_file():
        raise ValueError(f"{label} file does not exist: {path}")
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} line {number} is not valid JSON") from exc
        if not isinstance(row, dict):
            raise TypeError(f"{label} line {number} must be an object")
        rows.append(row)
    if not rows:
        raise ValueError(f"{label} file contains no decisions")
    return rows


def _index(rows: list[dict], label: str) -> dict[str, dict]:
    indexed = {}
    for row in rows:
        ident = row.get("source_id")
        if not isinstance(ident, str) or not ident or ident in indexed:
            raise ValueError(f"{label} contains an invalid or duplicate source_id")
        indexed[ident] = row
    return indexed


def _read_scene_file(path: Path, city: str) -> dict[str, dict]:
    if not path.is_file():
        raise ValueError(f"scene decisions file does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("scene decisions file is not valid JSON") from exc
    payload = _require_exact_keys(
        payload, {"schema_version", "city", "articles"}, "scene decision envelope"
    )
    if payload["schema_version"] != SCHEMA_VERSION or payload["city"] != city:
        raise ValueError("scene decision envelope has the wrong schema version or city")
    if not isinstance(payload["articles"], list) or not payload["articles"]:
        raise ValueError("scene decisions need a nonempty article list")
    return _index(payload["articles"], "scene decisions")


def _quotes(value: object, body: str, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} needs at least one full-text evidence quote")
    normalized = []
    for raw in value:
        if not isinstance(raw, str):
            raise TypeError(f"{label} evidence quotes must be strings")
        quote = _normalized(raw)
        if len(quote) < 15 or quote not in body:
            raise ValueError(f"{label} evidence quote is absent from the current source body")
        normalized.append(quote)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{label} contains duplicate evidence quotes")
    return normalized


def _location_judgment(value: object, body: str, statuses: set[str], label: str) -> dict:
    """Validate an explicitly authored judgment; never create a missing one."""
    value = _require_exact_keys(value, {"status", "note", "evidence_quotes"}, label)
    note = _normalized(value["note"]) if isinstance(value["note"], str) else ""
    if value["status"] not in statuses or len(note) < 8:
        raise ValueError(f"{label} needs a valid status and substantive review note")
    return {
        "status": value["status"],
        "note": note,
        "evidence_quotes": _quotes(value["evidence_quotes"], body, label),
    }


def _location_judgments(raw: dict, normalized: dict, body: str, label: str) -> None:
    if "poi_review" in raw:
        review = _location_judgment(
            raw["poi_review"], body,
            {"context_only", "source_unknown", "not_applicable"}, f"{label} POI review",
        )
        contexts = normalized.get("poi_contexts")
        if contexts is None or (review["status"] == "context_only") != bool(contexts):
            raise ValueError(f"{label} POI judgment differs from its explicit contexts")
        normalized["poi_review"] = review
    if "transit_review" in raw:
        review = _location_judgment(
            raw["transit_review"], body,
            {"reviewed_route", "source_backed_context", "source_unknown", "not_applicable"},
            f"{label} transit review",
        )
        if (review["status"] == "reviewed_route") != ("transit_route" in normalized):
            raise ValueError(f"{label} transit judgment differs from its reviewed route")
        normalized["transit_review"] = review


def _identity(value: dict, city: str, source: dict, label: str) -> None:
    if value["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"{label} has an unsupported schema version")
    if value["city"] != city:
        raise ValueError(f"{label} belongs to another city")
    if value["source_id"] != source["id"] or value["source_url"] != source["url"]:
        raise ValueError(f"{label} has a mismatched source ID or URL")
    supplied = value["source_sha256"]
    if not isinstance(supplied, str) or not SHA256.fullmatch(supplied):
        raise ValueError(f"{label} has an invalid source SHA-256")
    if supplied != source["sha256"]:
        raise ValueError(f"{label} is stale for the current source body")


def _reviewed_at(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} needs reviewed_at")
    candidate = value.strip()
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{label} has an invalid reviewed_at") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} reviewed_at must include a timezone")
    return candidate


def _coordinates(value: object, precision: str, label: str) -> list[float] | None:
    if value is None:
        return None
    if precision in NO_POINT_PRECISIONS:
        raise ValueError(f"{label} precision {precision} must not have a generated point")
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(type(number) not in {int, float} or not math.isfinite(number) for number in value)
        or not -180 <= value[0] <= 180
        or not -90 < value[1] < 90
    ):
        raise ValueError(f"{label} has invalid WGS84 coordinates")
    return [float(value[0]), float(value[1])]


def _validate_review(value: dict, body: str, label: str) -> dict:
    _require_exact_keys(value, REVIEW_KEYS, label)
    if value["verdict"] not in REVIEW_VERDICTS:
        raise ValueError(f"{label} has an invalid review verdict")
    reviewer = _normalized(value["reviewer"]) if isinstance(value["reviewer"], str) else ""
    note = _normalized(value["review_note"]) if isinstance(value["review_note"], str) else ""
    if not reviewer or not note:
        raise ValueError(f"{label} needs a reviewer and review note")
    return {
        "verdict": value["verdict"],
        "evidence_quotes": _quotes(value["evidence_quotes"], body, label),
        "review_note": note,
        "reviewer": reviewer,
        "reviewed_at": _reviewed_at(value["reviewed_at"], label),
    }


def _validate_scope(value: dict, body: str, label: str) -> dict:
    _require_exact_keys(value, SCOPE_KEYS, label)
    if value["scope_verdict"] not in SCOPE_VERDICTS:
        raise ValueError(f"{label} has an invalid scope verdict")
    return {
        "scope_verdict": value["scope_verdict"],
        "evidence_quotes": _quotes(value["evidence_quotes"], body, label),
    }


def _validate_scenes(value: dict, body: str, ident: str, label: str) -> dict:
    _require_exact_keys(value, SCENE_KEYS, label)
    incident_count = value["incident_count"]
    incidents = value["incidents"]
    locations = value["formal_locations"]
    if type(incident_count) is not int or incident_count < 0:
        raise ValueError(f"{label} needs a nonnegative integer incident_count")
    if value["incidents_complete"] is not True or value["formal_locations_complete"] is not True:
        raise ValueError(f"{label} must explicitly declare incidents and formal locations complete")
    if not isinstance(incidents, list) or len(incidents) != incident_count:
        raise ValueError(f"{label} incident_count does not match the incident list")
    if not isinstance(locations, list):
        raise TypeError(f"{label} formal_locations must be a list")

    normalized_locations = []
    location_ids = set()
    for number, location in enumerate(locations, start=1):
        item_label = f"{label} formal location {number}"
        location = _require_core_keys(
            location, LOCATION_KEYS, LOCATION_OPTIONAL_KEYS, item_label
        )
        location_id = location["location_id"]
        if (
            not isinstance(location_id, str)
            or not location_id.startswith(f"{ident}:location:")
            or location_id in location_ids
        ):
            raise ValueError(f"{item_label} has an invalid or duplicate location_id")
        location_ids.add(location_id)
        location_name = _normalized(location["label"]) if isinstance(location["label"], str) else ""
        if not location_name:
            raise ValueError(f"{item_label} needs a location label")
        if location["role"] not in SCENE_ROLES:
            raise ValueError(f"{item_label} has an invalid role")
        if location["precision"] not in SCENE_PRECISIONS:
            raise ValueError(f"{item_label} has an invalid precision")
        if location["city_scope"] not in LOCATION_SCOPES:
            raise ValueError(f"{item_label} has an invalid city_scope")
        normalized_location = {
                "location_id": location_id,
                "label": location_name,
                "role": location["role"],
                "precision": location["precision"],
                "city_scope": location["city_scope"],
                "evidence_quotes": _quotes(location["evidence_quotes"], body, item_label),
                "coordinates": _coordinates(
                    location["coordinates"], location["precision"], item_label
                ),
            }
        transit = _validate_transit(
            location.get("transit_route"), body, ident, location["precision"]
        )
        if transit is not None:
            normalized_location["transit_route"] = transit
        contexts = _validate_poi_contexts(
            location.get("poi_contexts"), body, ident
        )
        if contexts is not None:
            normalized_location["poi_contexts"] = contexts
        _location_judgments(location, normalized_location, body, item_label)
        normalized_locations.append(normalized_location)

    normalized_incidents = []
    incident_ids = set()
    for number, incident in enumerate(incidents, start=1):
        item_label = f"{label} incident {number}"
        incident = _require_core_keys(
            incident, INCIDENT_KEYS, INCIDENT_OPTIONAL_KEYS, item_label
        )
        incident_id = incident["incident_id"]
        if (
            not isinstance(incident_id, str)
            or not incident_id.startswith(f"{ident}:incident:")
            or incident_id in incident_ids
        ):
            raise ValueError(f"{item_label} has an invalid or duplicate incident_id")
        incident_ids.add(incident_id)
        references = incident["formal_location_ids"]
        if (
            not isinstance(references, list)
            or any(not isinstance(ref, str) or ref not in location_ids for ref in references)
            or len(references) != len(set(references))
        ):
            raise ValueError(f"{item_label} references an unknown or duplicate formal location")
        normalized_incident = {
                "incident_id": incident_id,
                "evidence_quotes": _quotes(incident["evidence_quotes"], body, item_label),
                "formal_location_ids": references,
            }
        event_time = _validate_event_time(
            incident.get("event_time"), body, ident
        )
        if event_time is not None:
            normalized_incident["event_time"] = event_time
        if "details" in incident:
            details = _normalized(incident["details"]) if isinstance(incident["details"], str) else ""
            if not details:
                raise ValueError(f"{item_label} has invalid details")
            normalized_incident["details"] = details
        normalized_incidents.append(normalized_incident)
    return {
        "incident_count": incident_count,
        "incidents_complete": True,
        "formal_locations_complete": True,
        "incidents": normalized_incidents,
        "formal_locations": normalized_locations,
    }


def _revalidate_single_source_decision(
    value: object, source: dict, city: str, ident: str
) -> dict:
    decision = _require_exact_keys(value, DECISION_KEYS, f"stored decision for {ident}")
    _identity(decision, city, source, f"stored decision for {ident}")
    identity = {key: decision[key] for key in IDENTITY_KEYS}
    review = _require_exact_keys(
        decision["review"], REVIEW_KEYS - IDENTITY_KEYS, f"stored review for {ident}"
    )
    scope = _require_exact_keys(
        decision["scope"], SCOPE_KEYS - IDENTITY_KEYS, f"stored scope for {ident}"
    )
    scenes = _require_exact_keys(
        decision["scene_inventory"],
        SCENE_KEYS - IDENTITY_KEYS,
        f"stored scene inventory for {ident}",
    )
    body = _normalized(source["body"])
    normalized = {
        **identity,
        "review": _validate_review(
            {**identity, **review}, body, f"stored review for {ident}"
        ),
        "scope": _validate_scope(
            {**identity, **scope}, body, f"stored scope for {ident}"
        ),
        "scene_inventory": _validate_scenes(
            {**identity, **scenes}, body, ident, f"stored scene inventory for {ident}"
        ),
    }
    if normalized != decision:
        raise ValueError(f"Stored review decision is not canonical: {ident}")
    return normalized


def _revalidate_stored_decision(value, source, city, ident):
    if isinstance(value, dict) and "source_supporting_material_binding" in value:
        from .supporting_material_reviews import validate_supporting_decision
        return validate_supporting_decision(
            value, source=source, city=city, source_id=ident,
            primary_validator=_revalidate_stored_decision,
        )
    if isinstance(value, dict) and "source_attachment_binding" in value:
        from .official_attachment_reviews import validate_attachment_referenced_decision
        return validate_attachment_referenced_decision(
            value, source=source, city=city, source_id=ident,
            primary_validator=_revalidate_stored_decision,
        )
    if isinstance(value, dict) and "source_document_binding" in value:
        from .official_pdf_references import validate_pdf_referenced_decision
        return validate_pdf_referenced_decision(
            value, source=source, city=city, source_id=ident,
            primary_validator=_revalidate_single_source_decision,
        )
    if isinstance(value, dict) and "source_reference_binding" in value:
        from .article_source_references import validate_source_referenced_decision
        return validate_source_referenced_decision(
            value, source=source, city=city, source_id=ident,
            primary_validator=_revalidate_single_source_decision,
        )
    return _revalidate_single_source_decision(value, source, city, ident)


def validate_stored_decision(
    value: object, *, source: dict, city: str, source_id: str
) -> dict:
    """Revalidate one stored decision against the current normalized source.

    Later GIS stages use this public boundary instead of trusting a prior
    importer run or duplicating semantic validation.
    """
    return _revalidate_stored_decision(value, source, city, source_id)


def _validate_city(city: str) -> None:
    if city == "munich":
        raise ValueError(
            "Munich is excluded from source-body LLM review because the owner accepted "
            "POLIZEIKARTE upstream semantics"
        )
    if city not in REVIEW_REQUIRED_CITIES:
        raise ValueError(f"City is outside the first-group source-review contract: {city}")


def _load_sources(db: sqlite3.Connection, city: str) -> tuple[dict[str, dict], int]:
    """Reuse the source-pack normalization and body hash verification."""
    _validate_city(city)
    rows, coverage = read_checkpoint_connection(db)
    sources = {}
    for row in rows:
        ident = row.get("source_id")
        url = row.get("source_url")
        digest = row.get("source_sha256")
        body = row.get("source_body")
        if (
            not isinstance(ident, str)
            or not ident
            or ident in sources
            or not isinstance(url, str)
            or not url
            or not isinstance(digest, str)
            or not SHA256.fullmatch(digest)
            or not isinstance(body, str)
            or not body.strip()
        ):
            raise ValueError("Normalized source checkpoint contains an invalid source record")
        sources[ident] = {
            "id": ident,
            "url": url,
            "body": body,
            "sha256": digest,
        }
    source_records = coverage.get("discovered")
    if type(source_records) is not int or source_records < len(sources):
        raise ValueError("Normalized source checkpoint has inconsistent coverage counts")
    return sources, source_records


def ensure_review_tables(db: sqlite3.Connection) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS source_llm_review_decisions (
           city TEXT NOT NULL, source_id TEXT NOT NULL, source_url TEXT NOT NULL,
           source_sha256 TEXT NOT NULL, schema_version INTEGER NOT NULL,
           decision_sha256 TEXT NOT NULL, verdict TEXT NOT NULL,
           scope_verdict TEXT NOT NULL, incident_count INTEGER NOT NULL,
           decision_json TEXT NOT NULL, reviewer TEXT NOT NULL,
           reviewed_at TEXT NOT NULL, imported_at REAL NOT NULL,
           PRIMARY KEY(city,source_id))"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS source_llm_review_history (
           city TEXT NOT NULL, source_id TEXT NOT NULL, source_sha256 TEXT NOT NULL,
           decision_sha256 TEXT NOT NULL, decision_json TEXT NOT NULL,
           imported_at REAL NOT NULL,
           PRIMARY KEY(city,source_id,decision_sha256))"""
    )


def _source(sources: dict[str, dict], ident: str) -> dict:
    source = sources.get(ident)
    if source is None:
        raise ValueError(f"Review decision refers to an unknown source ID: {ident}")
    return source


def import_decisions(
    *,
    db_path: Path,
    city: str,
    review_path: Path,
    scope_path: Path,
    scene_path: Path,
    imported_at: float | None = None,
) -> dict:
    """Atomically import a delta after validating all three decision files."""
    _validate_city(city)
    db = _connect(db_path)
    try:
        db.execute("BEGIN IMMEDIATE")
        sources, source_records = _load_sources(db, city)
        reviews = _index(_read_ndjson(review_path, "review decisions"), "review decisions")
        scopes = _index(_read_ndjson(scope_path, "scope decisions"), "scope decisions")
        scenes = _read_scene_file(scene_path, city)
        if set(reviews) != set(scopes) or set(reviews) != set(scenes):
            raise ValueError("Review, scope and scene decision source ID sets differ")

        prepared = []
        for ident in sorted(reviews):
            source = _source(sources, ident)
            review_row = reviews[ident]
            scope_row = scopes[ident]
            scene_row = scenes[ident]
            for row, name, keys in (
                (review_row, "review decision", REVIEW_KEYS),
                (scope_row, "scope decision", SCOPE_KEYS),
                (scene_row, "scene decision", SCENE_KEYS),
            ):
                _require_exact_keys(row, keys, f"{name} for {ident}")
                _identity(row, city, source, f"{name} for {ident}")
            body = _normalized(source["body"])
            decision = {
                "schema_version": SCHEMA_VERSION,
                "city": city,
                "source_id": ident,
                "source_url": source["url"],
                "source_sha256": source["sha256"],
                "review": _validate_review(review_row, body, f"review decision for {ident}"),
                "scope": _validate_scope(scope_row, body, f"scope decision for {ident}"),
                "scene_inventory": _validate_scenes(
                    scene_row, body, ident, f"scene decision for {ident}"
                ),
            }
            prepared.append((decision, _digest(decision)))

        now = time.time() if imported_at is None else imported_at
        inserted = changed = unchanged = 0
        ensure_review_tables(db)
        for decision, decision_sha in prepared:
            old = db.execute(
                """SELECT decision_sha256 FROM source_llm_review_decisions
                   WHERE city=? AND source_id=?""",
                (city, decision["source_id"]),
            ).fetchone()
            if old is None:
                inserted += 1
            elif old["decision_sha256"] == decision_sha:
                unchanged += 1
            else:
                changed += 1
            payload = _json_bytes(decision).decode("utf-8")
            db.execute(
                """INSERT OR IGNORE INTO source_llm_review_history
                   (city,source_id,source_sha256,decision_sha256,decision_json,imported_at)
                   VALUES(?,?,?,?,?,?)""",
                (
                    city,
                    decision["source_id"],
                    decision["source_sha256"],
                    decision_sha,
                    payload,
                    now,
                ),
            )
            db.execute(
                """INSERT INTO source_llm_review_decisions
                   (city,source_id,source_url,source_sha256,schema_version,
                    decision_sha256,verdict,scope_verdict,incident_count,
                    decision_json,reviewer,reviewed_at,imported_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(city,source_id) DO UPDATE SET
                   source_url=excluded.source_url,source_sha256=excluded.source_sha256,
                   schema_version=excluded.schema_version,
                   decision_sha256=excluded.decision_sha256,verdict=excluded.verdict,
                   scope_verdict=excluded.scope_verdict,
                   incident_count=excluded.incident_count,
                   decision_json=excluded.decision_json,reviewer=excluded.reviewer,
                   reviewed_at=excluded.reviewed_at,imported_at=excluded.imported_at""",
                (
                    city,
                    decision["source_id"],
                    decision["source_url"],
                    decision["source_sha256"],
                    SCHEMA_VERSION,
                    decision_sha,
                    decision["review"]["verdict"],
                    decision["scope"]["scope_verdict"],
                    decision["scene_inventory"]["incident_count"],
                    payload,
                    decision["review"]["reviewer"],
                    decision["review"]["reviewed_at"],
                    now,
                ),
            )
        summary = _review_summary(db, city, sources, source_records)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return {
        "city": city,
        "validated": len(prepared),
        "inserted": inserted,
        "changed": changed,
        "unchanged": unchanged,
        **summary,
    }


def _review_summary(
    db: sqlite3.Connection, city: str, sources: dict[str, dict], source_records: int
) -> dict:
    """Report only decisions bound to each report's current source hash."""
    ensure_review_tables(db)
    counts = {
        "supported": 0,
        "needs_correction": 0,
        "uncertain": 0,
        "pending": source_records - len(sources),
        "stale": 0,
    }
    current = []
    for ident, source in sorted(sources.items()):
        row = db.execute(
            """SELECT source_url,source_sha256,decision_sha256,decision_json,verdict
               FROM source_llm_review_decisions WHERE city=? AND source_id=?""",
            (city, ident),
        ).fetchone()
        if row is None:
            counts["pending"] += 1
            continue
        if row["source_sha256"] != source["sha256"] or row["source_url"] != source["url"]:
            counts["stale"] += 1
            continue
        try:
            decision = json.loads(row["decision_json"])
        except json.JSONDecodeError as exc:
            raise ValueError(f"Stored review decision is invalid: {ident}") from exc
        decision = _revalidate_stored_decision(decision, source, city, ident)
        if (
            _digest(decision) != row["decision_sha256"]
            or row["verdict"] not in REVIEW_VERDICTS
            or decision.get("city") != city
            or decision.get("source_id") != ident
            or decision.get("source_url") != source["url"]
            or decision.get("source_sha256") != source["sha256"]
        ):
            raise ValueError(f"Stored review decision hash or identity mismatch: {ident}")
        counts[row["verdict"]] += 1
        current.append(
            {
                "source_id": ident,
                "source_sha256": source["sha256"],
                "decision_sha256": row["decision_sha256"],
            }
        )
    decision_set_digest = _digest(current)
    total = sum(counts.values())
    if total != source_records:
        raise ValueError("Review summary does not cover the normalized source checkpoint")
    return {
        "source_records": total,
        "review_counts": counts,
        "decision_set_digest": decision_set_digest,
        "all_current_reviews_supported": total > 0 and counts["supported"] == total,
        "owner_approval_required": True,
        "owner_approved": False,
        "publication_ready": False,
    }


def review_summary(*, db_path: Path, city: str) -> dict:
    _validate_city(city)
    db = _connect(db_path)
    try:
        db.execute("BEGIN IMMEDIATE")
        sources, source_records = _load_sources(db, city)
        result = _review_summary(db, city, sources, source_records)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def current_supported_decisions(*, db_path: Path, city: str) -> list[dict]:
    """Return structurally valid, current-hash supported decisions for later stages."""
    _validate_city(city)
    db = _connect(db_path)
    try:
        db.execute("BEGIN IMMEDIATE")
        sources, source_records = _load_sources(db, city)
        _review_summary(db, city, sources, source_records)
        decisions = []
        for row in db.execute(
            """SELECT source_id,source_url,source_sha256,decision_json
               FROM source_llm_review_decisions
               WHERE city=? AND verdict='supported' ORDER BY source_id""",
            (city,),
        ):
            source = sources.get(row["source_id"])
            if (
                source is not None
                and row["source_url"] == source["url"]
                and row["source_sha256"] == source["sha256"]
            ):
                decisions.append(json.loads(row["decision_json"]))
        db.commit()
        return decisions
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _default_db(city: str) -> Path:
    return paths_for(city, Path.cwd()).source_db


def _connect(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise ValueError(f"SQLite checkpoint does not exist: {path}")
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--city", choices=sorted(REVIEW_REQUIRED_CITIES | {"munich"}), required=True
    )
    parser.add_argument("--db", type=Path)
    parser.add_argument("--review-decisions", type=Path, required=True)
    parser.add_argument("--scope-decisions", type=Path, required=True)
    parser.add_argument("--scene-decisions", type=Path, required=True)
    args = parser.parse_args()
    try:
        _validate_city(args.city)
    except ValueError as exc:
        parser.error(str(exc))
    db_path = args.db or _default_db(args.city)
    if not db_path.is_file():
        parser.error(f"Local source checkpoint does not exist: {db_path}")
    try:
        result = import_decisions(
            db_path=db_path,
            city=args.city,
            review_path=args.review_decisions,
            scope_path=args.scope_decisions,
            scene_path=args.scene_decisions,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
