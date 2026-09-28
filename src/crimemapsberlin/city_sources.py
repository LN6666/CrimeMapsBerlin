"""Read first-group source checkpoints into a common extraction input.

The issuing police authority is wider than a municipality. Reports without
positive city evidence stay in the source checkpoint for later review, rather
than being geocoded into a city candidate batch.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .city_contract import CITY_SPECS


@dataclass(frozen=True)
class SourceSelection:
    reports: list[dict]
    coverage: dict[str, int]
    archive_complete: bool


FRANKFURT_CITY = re.compile(
    r"\b(?:in\s+Frankfurt(?:\s+am\s+Main)?|Frankfurt-[\wÄÖÜäöüß]+|"
    r"im\s+Frankfurter\s+Stadtteil|in\s+der\s+Frankfurter\s+Innenstadt)\b",
    re.I,
)
FRANKFURT_OUTSIDE = re.compile(
    r"\b(?:in|bei)\s+(?:Offenbach|Bad\s+Homburg|Hanau|Darmstadt|Wiesbaden|"
    r"Bad\s+Vilbel|Neu-Isenburg|Oberursel|Eschborn|Maintal|Hofheim|Kelsterbach|"
    r"Hattersheim|Mörfelden-Walldorf)\b",
    re.I,
)
FRANKFURT_BOILERPLATE = re.compile(r"^\s*Frankfurt(?:\s+am\s+Main)?\s*\(ots\)\s*[-–]?\s*", re.I)
RESPONSE_CONTEXT = re.compile(
    r"\b(?:festgenommen|festnahmen?|verhaftet|aufgegriffen|angetroffen|kontrolliert)\b|"
    r"\b(?:nahm|nahmen|nimmt|nehmen)\b.{0,100}\bfest\b|"
    r"\b(?:wohnt|wohnte|wohnhaft)\b",
    re.I,
)


def _scene_scope_match(pattern: re.Pattern, text: str):
    for sentence in re.split(r"(?<=[.!?;])\s+|\n+", text):
        match = pattern.search(sentence)
        if match and not RESPONSE_CONTEXT.search(sentence):
            return match
    return None


def frankfurt_scope(title: str, body: str) -> str:
    """A positive municipality mention is a review lead, not a scene finding."""
    narrative = FRANKFURT_BOILERPLATE.sub("", body)
    narrative = re.sub(r"\bPolizeipräsidium\s+Frankfurt\s+am\s+Main\b", "", narrative, flags=re.I)
    text = title + "\n" + narrative
    inside = _scene_scope_match(FRANKFURT_CITY, text)
    outside = _scene_scope_match(FRANKFURT_OUTSIDE, text)
    if inside and not outside:
        return "city_candidate"
    if outside and not inside:
        return "outside_candidate"
    return "needs_review"


def _archive_complete(db: sqlite3.Connection, city: str) -> bool:
    # Existing adapter cursors describe only the years already requested. They
    # cannot prove that every required year or native supplement was scanned.
    # Keep the cross-city audit fail-closed until an explicit coverage range is
    # stored and reconciled for each source.
    return False


def read_city_source(city: str, path: Path) -> SourceSelection:
    spec = CITY_SPECS[city]
    if spec.source_schema == "munich_unverified":
        raise ValueError(
            "Munich source is offline-supplied and unverified; robots.txt disallows automated crawling"
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
            rows = db.execute(
                """SELECT id,url,title,published,district,body,sha256,revision,
                   http_status,error FROM reports ORDER BY published,id"""
            ).fetchall()
        counts = dict(discovered=len(rows), fetched=0, pending=0, failed=0,
                      selected=0, outside=0, deferred=0)
        selected = []
        for row in rows:
            report = dict(row)
            if report["error"]:
                counts["failed"] += 1
            if report["body"] is None:
                counts["pending"] += 1
                continue
            counts["fetched"] += 1
            if city == "cologne":
                scope = report.pop("city_scope")
                if not report["id"]:
                    scope = "needs_review"
            elif city == "frankfurt":
                scope = frankfurt_scope(report["title"], report["body"])
            else:
                scope = "city_candidate"
            if scope in {"cologne_candidate", "city_candidate"}:
                counts["selected"] += 1
                selected.append(report)
            elif scope in {"outside_candidate", "outside"}:
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
