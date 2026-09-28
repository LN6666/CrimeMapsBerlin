"""Local, source-versioned review ledger for model-assisted extraction checks."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

REVIEW_VERSION = 1
VERDICTS = {"supported", "needs_correction", "uncertain"}
TAGS = {
    "violent_assault", "robbery", "threat", "sexual_offence", "property_offence",
    "possible_hate_crime",
}
HATE_BASES = {"police_motive_suspected", "reported_bias_language_or_behavior"}


def fingerprint(event: dict) -> str:
    """Invalidate a review when any extracted field changes."""
    payload = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    # Serialize schema migration when a builder and reviewer start together.
    db.execute("BEGIN IMMEDIATE")
    db.execute(
        """CREATE TABLE IF NOT EXISTS reviews (
        city TEXT NOT NULL, article_id TEXT NOT NULL, source_sha256 TEXT NOT NULL,
        extraction_sha256 TEXT NOT NULL, review_version INTEGER NOT NULL,
        verdict TEXT NOT NULL, evidence_quote TEXT NOT NULL, note TEXT NOT NULL,
        reviewer TEXT NOT NULL, reviewed_at TEXT NOT NULL, tags_json TEXT NOT NULL DEFAULT '[]',
        PRIMARY KEY(city, article_id, source_sha256, extraction_sha256, review_version))"""
    )
    if "tags_json" not in {row[1] for row in db.execute("PRAGMA table_info(reviews)")}:
        db.execute("ALTER TABLE reviews ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'")
    db.execute(
        """CREATE TABLE IF NOT EXISTS owner_approvals (
        city TEXT NOT NULL, decision_digest TEXT NOT NULL,
        approved_by TEXT NOT NULL, note TEXT NOT NULL, approved_at TEXT NOT NULL,
        PRIMARY KEY(city, decision_digest))"""
    )
    db.commit()
    return db


def review_status(db: sqlite3.Connection, city: str, event: dict) -> str:
    row = db.execute(
        """SELECT verdict FROM reviews WHERE city=? AND article_id=? AND source_sha256=?
        AND extraction_sha256=? AND review_version=?""",
        (city, event["id"], event["source_sha256"], fingerprint(event), REVIEW_VERSION),
    ).fetchone()
    return row["verdict"] if row else "pending"


def review_summary(db: sqlite3.Connection, city: str, events: list[dict]) -> dict:
    counts = {"supported": 0, "needs_correction": 0, "uncertain": 0, "pending": 0}
    for event in events:
        counts[review_status(db, city, event)] += 1
    return counts


def record_reviews(
    db: sqlite3.Connection, city: str, events: list[dict], bodies: dict[str, str],
    decisions: list[dict],
) -> int:
    """Accept only decisions tied to the current body and candidate extraction."""
    from datetime import datetime, timezone

    current = {event["id"]: event for event in events}
    seen = set()
    prepared = []
    for decision in decisions:
        ident = str(decision["id"])
        if ident in seen or ident not in current:
            raise ValueError(f"Duplicate or unknown review ID: {ident}")
        seen.add(ident)
        event = current[ident]
        source_sha = event["source_sha256"]
        extraction_sha = fingerprint(event)
        if (decision.get("source_sha256"), decision.get("extraction_sha256")) != (
            source_sha, extraction_sha
        ):
            raise ValueError(f"Stale review for {ident}")
        verdict = decision.get("verdict")
        if verdict not in VERDICTS:
            raise ValueError(f"Unknown verdict for {ident}")
        evidence = " ".join(decision.get("evidence_quote", "").split())
        note = " ".join(decision.get("note", "").split())
        reviewer = " ".join(decision.get("reviewer", "").split())
        body = " ".join(bodies.get(ident, "").split())
        if not body or not reviewer or not note:
            raise ValueError(f"Missing body, reviewer or explanation for {ident}")
        if hashlib.sha256(body.encode()).hexdigest() != source_sha:
            raise ValueError(f"Source changed after candidate extraction for {ident}")
        if verdict == "supported" and (len(evidence) < 15 or evidence not in body):
            raise ValueError(f"Supported review lacks a verbatim source excerpt for {ident}")
        if evidence and evidence not in body:
            raise ValueError(f"Evidence quote does not occur in the source for {ident}")
        tags = decision.get("tags", [])
        if (
            not isinstance(tags, list)
            or not all(isinstance(tag, dict) for tag in tags)
            or len({tag.get("tag") for tag in tags}) != len(tags)
        ):
            raise ValueError(f"Invalid or duplicate tags for {ident}")
        if verdict != "supported" and tags:
            raise ValueError(f"Unresolved review cannot publish tags for {ident}")
        for tag in tags:
            name = tag.get("tag")
            quote = " ".join(tag.get("evidence_quote", "").split())
            if name not in TAGS or not 15 <= len(quote) <= 240 or quote not in body:
                raise ValueError(f"Tag lacks allowed name or verbatim evidence for {ident}")
            if name == "possible_hate_crime" and tag.get("basis") not in HATE_BASES:
                raise ValueError(f"Hate-crime tag lacks explicit-bias basis for {ident}")
        prepared.append(
            (city, ident, source_sha, extraction_sha, REVIEW_VERSION, verdict,
             evidence, note, reviewer, datetime.now(timezone.utc).isoformat(),
             json.dumps(tags, ensure_ascii=False, sort_keys=True))
        )
    with db:
        db.executemany(
            """INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(city,article_id,source_sha256,extraction_sha256,review_version)
            DO UPDATE SET verdict=excluded.verdict,evidence_quote=excluded.evidence_quote,
            note=excluded.note,reviewer=excluded.reviewer,reviewed_at=excluded.reviewed_at,
            tags_json=excluded.tags_json""",
            prepared,
        )
    return len(prepared)


def reviewed_tags(db: sqlite3.Connection, city: str, event: dict) -> list[dict]:
    row = db.execute(
        """SELECT tags_json FROM reviews WHERE city=? AND article_id=? AND source_sha256=?
        AND extraction_sha256=? AND review_version=? AND verdict='supported'""",
        (city, event["id"], event["source_sha256"], fingerprint(event), REVIEW_VERSION),
    ).fetchone()
    return json.loads(row["tags_json"]) if row else []


def review_packet(
    db: sqlite3.Connection, city: str, events: list[dict],
    changed_locations: list[dict] | None = None,
) -> dict:
    """Bind an owner's inspection to every current candidate and AI decision."""
    rows = []
    for event in sorted(events, key=lambda item: item["id"]):
        row = db.execute(
            """SELECT verdict,evidence_quote,note,reviewer,reviewed_at,tags_json
            FROM reviews WHERE city=? AND article_id=? AND source_sha256=?
            AND extraction_sha256=? AND review_version=?""",
            (city, event["id"], event["source_sha256"], fingerprint(event), REVIEW_VERSION),
        ).fetchone()
        if row is None or row["verdict"] != "supported":
            raise ValueError("Every current announcement needs a supported review before owner approval")
        review = {key: row[key] for key in (
            "verdict", "evidence_quote", "note", "reviewer", "reviewed_at"
        )}
        review["tags"] = json.loads(row["tags_json"])
        rows.append(dict(
            id=event["id"], source_url=event["source_url"],
            source_sha256=event["source_sha256"], extraction_sha256=fingerprint(event),
            category=event.get("category"), location_label=event.get("location_label"),
            coordinates=event.get("coordinates"),
            geocode_method=event.get("geocode_method"),
            geocode_evidence=event.get("geocode_evidence"),
            review=review,
        ))
    changes = sorted(changed_locations or [], key=lambda row: (row["id"], row["reason"]))
    # The comparison list is for inspection. After this candidate is published,
    # its previous-map comparison changes, but the approved candidate does not.
    digest = hashlib.sha256(json.dumps(
        dict(city=city, review_version=REVIEW_VERSION, rows=rows),
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    return dict(city=city, decision_digest=digest, count=len(rows),
                changed_locations=changes, items=rows)


def owner_approved(
    db: sqlite3.Connection, city: str, events: list[dict],
    changed_locations: list[dict] | None = None,
) -> bool:
    try:
        digest = review_packet(db, city, events, changed_locations)["decision_digest"]
    except ValueError:
        return False
    return db.execute(
        "SELECT 1 FROM owner_approvals WHERE city=? AND decision_digest=?",
        (city, digest),
    ).fetchone() is not None


def record_owner_approval(
    db: sqlite3.Connection, city: str, events: list[dict], approval: dict,
    changed_locations: list[dict] | None = None,
) -> str:
    """Record the owner's explicit signoff after inspecting and questioning a packet."""
    from datetime import datetime, timezone

    packet = review_packet(db, city, events, changed_locations)
    if approval.get("city") != city or approval.get("decision_digest") != packet["decision_digest"]:
        raise ValueError("Approval is for a different or stale review packet")
    approver = " ".join(str(approval.get("approved_by", "")).split())
    note = " ".join(str(approval.get("note", "")).split())
    if not approver or not note:
        raise ValueError("Owner approval needs an approver and review note")
    with db:
        db.execute(
            "INSERT OR REPLACE INTO owner_approvals VALUES(?,?,?,?,?)",
            (city, packet["decision_digest"], approver, note,
             datetime.now(timezone.utc).isoformat()),
        )
    return packet["decision_digest"]
