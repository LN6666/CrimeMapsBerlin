"""Hash-bound LLM municipality decisions for first-group source checkpoints."""

from __future__ import annotations

import sqlite3

SCOPE_VERDICTS = {"in_city", "out_of_city", "mixed", "uncertain"}


def ensure_scope_table(db: sqlite3.Connection) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS city_scope_decisions (
             source_id TEXT PRIMARY KEY,
             source_sha256 TEXT NOT NULL,
             verdict TEXT NOT NULL,
             evidence TEXT NOT NULL,
             reviewed REAL NOT NULL
        )"""
    )
    db.commit()


def _source_columns(db: sqlite3.Connection) -> tuple[str, str]:
    columns = {row[1] for row in db.execute("PRAGMA table_info(reports)")}
    if {"id", "body", "sha256"} <= columns:
        return "id", "sha256"
    if {"source_id", "body", "sha256"} <= columns:
        return "source_id", "sha256"
    raise ValueError("Unsupported source checkpoint schema")


def record_city_scope(
    db: sqlite3.Connection,
    source_id: str,
    verdict: str,
    evidence: str,
    reviewed: float,
) -> None:
    """Store one full-text LLM decision against the current source hash."""
    if verdict not in SCOPE_VERDICTS:
        raise ValueError("Invalid city-scope verdict")
    evidence = " ".join(evidence.split())
    if len(evidence) < 20:
        raise ValueError("City-scope decision requires specific source evidence")
    id_column, _ = _source_columns(db)
    row = db.execute(
        f"SELECT body,sha256 FROM reports WHERE {id_column}=?", (source_id,)
    ).fetchone()
    if row is None or row["body"] is None or row["sha256"] is None:
        raise ValueError("City-scope decision requires a fetched source body")
    normalized_body = " ".join(row["body"].split())
    if evidence.casefold() not in normalized_body.casefold():
        raise ValueError("City-scope evidence must quote the fetched source body")
    ensure_scope_table(db)
    db.execute(
        """INSERT INTO city_scope_decisions
           (source_id,source_sha256,verdict,evidence,reviewed) VALUES(?,?,?,?,?)
           ON CONFLICT(source_id) DO UPDATE SET
           source_sha256=excluded.source_sha256,verdict=excluded.verdict,
           evidence=excluded.evidence,reviewed=excluded.reviewed""",
        (source_id, row["sha256"], verdict, evidence, reviewed),
    )
    db.commit()


def scope_decisions(db: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    table = db.execute(
        """SELECT 1 FROM sqlite_master
           WHERE type='table' AND name='city_scope_decisions'"""
    ).fetchone()
    if table is None:
        return {}
    return {
        row["source_id"]: row
        for row in db.execute(
            """SELECT source_id,source_sha256,verdict,evidence,reviewed
               FROM city_scope_decisions"""
        )
    }


def valid_scope_verdict(decision: sqlite3.Row | None, body: str, digest: str) -> str | None:
    if decision is None or decision["source_sha256"] != digest:
        return None
    if decision["verdict"] not in SCOPE_VERDICTS:
        return None
    evidence = " ".join(str(decision["evidence"]).split())
    if len(evidence) < 20 or evidence.casefold() not in " ".join(body.split()).casefold():
        return None
    return decision["verdict"]
