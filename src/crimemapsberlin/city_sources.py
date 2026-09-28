"""Read first-group source checkpoints into a common extraction input.

The issuing police authority is wider than a municipality. Cologne and
Frankfurt reports require a full-text LLM municipality decision bound to the
current source hash before they can enter a geocoding candidate batch.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .city_contract import CITY_SPECS
from .city_scope import scope_decisions, valid_scope_verdict


@dataclass(frozen=True)
class SourceSelection:
    reports: list[dict]
    coverage: dict[str, int]
    archive_complete: bool


PARSER_VERSIONS = {"hamburg": 3, "frankfurt": 3}


def frankfurt_scope(_title: str, _body: str) -> str:
    """Return only the technical gate; source meaning is decided by the LLM."""
    return "needs_review"


def _archive_complete(db: sqlite3.Connection, city: str) -> bool:
    if city != "hamburg" or db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='archive_coverage'"
    ).fetchone() is None:
        # Existing cross-city cursors do not yet prove that every required year
        # and native supplement was scanned.
        return False
    years = [
        row[0] for row in db.execute(
            "SELECT DISTINCT CAST(substr(published,1,4) AS INTEGER) FROM reports"
        )
    ]
    if not years:
        return False
    for year in years:
        coverage = db.execute(
            "SELECT complete,checked FROM archive_coverage WHERE year=?", (year,)
        ).fetchone()
        if coverage is None or not coverage["complete"]:
            return False
        newer = db.execute(
            "SELECT 1 FROM reports WHERE published LIKE ? AND first_seen>? LIMIT 1",
            (f"{year}-%", coverage["checked"]),
        ).fetchone()
        if newer is not None:
            return False
    current_parser = PARSER_VERSIONS[city]
    incomplete = db.execute(
        """SELECT 1 FROM reports
           WHERE body IS NULL OR error IS NOT NULL OR parser_version<? LIMIT 1""",
        (current_parser,),
    ).fetchone()
    return incomplete is None


def read_city_source(city: str, path: Path) -> SourceSelection:
    spec = CITY_SPECS[city]
    if spec.source_schema == "polizeikarte_munich":
        raise ValueError(
            "Munich uses its direct POLIZEIKARTE candidate adapter, not the official-archive schema"
        )
    if not path.is_file():
        raise FileNotFoundError(f"Missing {city} official announcement checkpoint")
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN")
        if spec.source_schema == "cologne_native":
            rows = db.execute(
                """SELECT source_id AS id,source_url AS url,title,published,
                   '' AS district,body,sha256,revision,NULL AS http_status,error,
                   city_scope FROM reports ORDER BY published,source_url"""
            ).fetchall()
        else:
            columns = {row[1] for row in db.execute("PRAGMA table_info(reports)")}
            parser_version = (
                "parser_version" if "parser_version" in columns else "NULL AS parser_version"
            )
            rows = db.execute(
                f"""SELECT id,url,title,published,district,body,sha256,revision,
                   http_status,error,{parser_version} FROM reports ORDER BY published,id"""
            ).fetchall()
        counts = {
            "discovered": len(rows), "fetched": 0, "pending": 0, "failed": 0,
            "selected": 0, "outside": 0, "deferred": 0,
        }
        decisions = scope_decisions(db) if city in {"cologne", "frankfurt"} else {}
        selected = []
        for row in rows:
            report = dict(row)
            parsed_with = report.pop("parser_version", None)
            if report["error"]:
                counts["failed"] += 1
            if report["body"] is None or (
                parsed_with is not None and parsed_with < PARSER_VERSIONS.get(city, 0)
            ):
                counts["pending"] += 1
                continue
            counts["fetched"] += 1
            if city in {"cologne", "frankfurt"}:
                report.pop("city_scope", None)
                scope = valid_scope_verdict(
                    decisions.get(report["id"]), report["body"], report["sha256"]
                )
            else:
                scope = "in_city"
            if scope == "in_city":
                counts["selected"] += 1
                selected.append(report)
            elif scope == "out_of_city":
                counts["outside"] += 1
            else:
                counts["deferred"] += 1
        return SourceSelection(selected, counts, _archive_complete(db, city))
    finally:
        db.close()


def normalized_event_db(reports: list[dict]) -> sqlite3.Connection:
    """Use the existing extractor against an ephemeral, normalized read view."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(
        """CREATE TABLE reports (
           id TEXT PRIMARY KEY,url TEXT,title TEXT,published TEXT,district TEXT,
           body TEXT,sha256 TEXT,revision INTEGER,http_status INTEGER,error TEXT)"""
    )
    db.executemany(
        "INSERT INTO reports VALUES(:id,:url,:title,:published,:district,:body,:sha256,:revision,:http_status,:error)",
        reports,
    )
    return db
