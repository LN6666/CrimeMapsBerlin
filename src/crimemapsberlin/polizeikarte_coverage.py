"""Audit POLIZEIKARTE coverage against a hash-checked official corpus.

POLIZEIKARTE is an independent project that adds categories and public map
locations to police reports.  This module checkpoints only the structured map
payload needed to measure overlap with an already collected official corpus.
It does not accept the upstream semantics, create LLM review decisions, or
grant publication authority.

The ten category pages form a fail-closed partition: every page must report the
same overall total, its map payload must equal the category total, and entry IDs
must not overlap across categories.  Matching to the official SQLite database
uses only canonical URLs and exact Presseportal article IDs.  Titles, dates,
districts and coordinates are deliberately not used as automatic matches.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx

from .polizeikarte_munich import CATEGORIES, _declared_counts, _map_events, _occurred_at

ORIGIN = "https://polizeikarte.de"
ROBOTS_URL = ORIGIN + "/robots.txt"
WINDOW_DAYS = 365
SCHEMA_VERSION = 1
USER_AGENT = "CrimeMapsBerlin/0.1 (POLIZEIKARTE coverage audit)"
SELECTED_CITY_SLUGS = {
    "berlin",
    "hamburg",
    "muenchen",
    "koeln",
    "frankfurt",
    "duesseldorf",
    "stuttgart",
    "leipzig",
    "dortmund",
    "bremen",
    "essen",
    "dresden",
    "hannover",
    "nuernberg",
}
PRECISIONS = {"CITY", "DISTRICT", "STREET", "ADDRESS", "PLACE", "POINT"}
PRESSPORTAL_PATH = re.compile(r"/blaulicht/pm/(\d+)/(\d+)/?")
SHA256 = re.compile(r"[0-9a-f]{64}")


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _listing_url(city: str, category: str) -> str:
    if city not in SELECTED_CITY_SLUGS:
        raise ValueError(f"Unsupported selected city: {city}")
    if category not in CATEGORIES:
        raise ValueError(f"Unknown POLIZEIKARTE category: {category}")
    return f"{ORIGIN}/{city}?" + urlencode(
        {"zeitraum": WINDOW_DAYS, "kategorie": category}
    )


def _canonical_url(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("Source URL must be a string")
    parsed = urlparse(value.strip())
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("Source URL must be an absolute fragment-free HTTPS URL")
    host = parsed.hostname.lower() if parsed.hostname else ""
    if parsed.port not in {None, 443}:
        host = f"{host}:{parsed.port}"
    path = parsed.path.rstrip("/") or "/"
    return urlunparse(("https", host, path, "", parsed.query, ""))


def _presseportal_article_id(value: str) -> str | None:
    parsed = urlparse(value)
    if parsed.hostname not in {"presseportal.de", "www.presseportal.de"}:
        return None
    match = PRESSPORTAL_PATH.fullmatch(parsed.path)
    return match[2] if match else None


def _validate_response(response: httpx.Response, requested_url: str) -> str:
    response.raise_for_status()
    if response.status_code != 200 or str(response.url) != requested_url:
        raise ValueError("POLIZEIKARTE returned an unexpected status or redirect")
    if "text/html" not in response.headers.get("content-type", ""):
        raise ValueError("POLIZEIKARTE category page did not return HTML")
    if len(response.content) > 12_000_000:
        raise ValueError("POLIZEIKARTE category page exceeded the bounded response size")
    return response.text


def _robots_status(client: httpx.Client, city: str) -> dict[str, object]:
    response = client.get(ROBOTS_URL)
    response.raise_for_status()
    if response.status_code != 200 or str(response.url) != ROBOTS_URL:
        raise ValueError("Missing or unexpected POLIZEIKARTE robots.txt response")
    robots = RobotFileParser()
    robots.parse(response.text.splitlines())
    allowed = all(
        robots.can_fetch(USER_AGENT, _listing_url(city, category))
        for category in CATEGORIES
    )
    return {
        "robots_url": ROBOTS_URL,
        "listing_allowed": allowed,
        "crawl_delay": robots.crawl_delay(USER_AGENT),
        "robots_sha256": hashlib.sha256(response.content).hexdigest(),
    }


def _normalized_event(value: object, category: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("POLIZEIKARTE map event must be an object")
    entry_id = value.get("id")
    if type(entry_id) is not int or entry_id < 1:
        raise ValueError("POLIZEIKARTE map event has an invalid ID")
    if value.get("category") != category:
        raise ValueError("POLIZEIKARTE category payload mixed categories")
    title = " ".join(str(value.get("title") or "").split())
    if not title:
        raise ValueError("POLIZEIKARTE map event has an empty title")
    precision = value.get("public_precision")
    if precision not in PRECISIONS:
        raise ValueError("POLIZEIKARTE map event has an unknown location precision")
    latitude, longitude = value.get("lat"), value.get("lng")
    if (latitude is None) != (longitude is None):
        raise ValueError("POLIZEIKARTE map event has a partial coordinate")
    if latitude is not None and (
        type(latitude) not in {int, float}
        or type(longitude) not in {int, float}
        or not -90 <= float(latitude) <= 90
        or not -180 <= float(longitude) <= 180
    ):
        raise ValueError("POLIZEIKARTE map event has an invalid coordinate")
    district = " ".join(str(value.get("district") or "").split()) or None
    return {
        "entry_id": entry_id,
        "title": title,
        "category": category,
        "occurred_at": _occurred_at(str(value.get("occurred_at") or "")),
        "district": district,
        "public_precision": precision,
        "latitude": float(latitude) if latitude is not None else None,
        "longitude": float(longitude) if longitude is not None else None,
        "official_url": _canonical_url(value.get("source_url")),
    }


def collect_snapshot(
    city: str,
    *,
    delay: float = 1.0,
    client: httpx.Client | None = None,
) -> dict[str, object]:
    """Collect a complete ten-category POLIZEIKARTE metadata snapshot."""
    if city not in SELECTED_CITY_SLUGS:
        raise ValueError(f"Unsupported selected city: {city}")
    if not 0 <= delay <= 60:
        raise ValueError("Delay must be between 0 and 60 seconds")
    owns_client = client is None
    if client is None:
        client = httpx.Client(
            timeout=30,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
        )
    try:
        permission = _robots_status(client, city)
        if not permission["listing_allowed"]:
            raise PermissionError(f"POLIZEIKARTE robots.txt disallows the {city} listing")
        effective_delay = max(delay, float(permission["crawl_delay"] or 0))
        declared_overall: set[int] = set()
        all_entries: list[dict[str, object]] = []
        pages: list[dict[str, object]] = []
        for index, category in enumerate(CATEGORIES):
            if index:
                time.sleep(effective_delay)
            url = _listing_url(city, category)
            page = _validate_response(client.get(url), url)
            category_count, overall_count = _declared_counts(page)
            declared_overall.add(overall_count)
            if category_count:
                raw_events = _map_events(page)
            else:
                raw_events = []
            entries = [_normalized_event(event, category) for event in raw_events]
            if len(entries) != category_count:
                raise ValueError(
                    "POLIZEIKARTE map payload count differs from the declared category total"
                )
            all_entries.extend(entries)
            pages.append(
                {
                    "category": category,
                    "url": url,
                    "sha256": hashlib.sha256(page.encode()).hexdigest(),
                    "declared_count": category_count,
                }
            )
        if len(declared_overall) != 1:
            raise ValueError("POLIZEIKARTE categories disagree on the overall total")
        expected_total = declared_overall.pop()
        entry_ids = [entry["entry_id"] for entry in all_entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError("POLIZEIKARTE categories overlap or contain duplicate IDs")
        if len(all_entries) != expected_total:
            raise ValueError("POLIZEIKARTE category totals do not equal the overall total")
        payload: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "provider": "POLIZEIKARTE",
            "provider_status": "independent_project_not_police_authority",
            "city": city,
            "window_days": WINDOW_DAYS,
            "fetched_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "robots": permission,
            "expected_total": expected_total,
            "pages": pages,
            "entries": sorted(all_entries, key=lambda row: int(row["entry_id"])),
            "upstream_semantics_accepted": False,
            "llm_review_bypassed": False,
            "publication_ready": False,
        }
        payload["snapshot_sha256"] = _digest(payload)
        return payload
    finally:
        if owns_client:
            client.close()


def _read_official_reports(path: Path | str) -> list[dict[str, object]]:
    db_path = Path(path)
    if not db_path.is_file():
        raise ValueError(f"Official source database does not exist: {db_path}")
    with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='reports'"
        ).fetchone()
        if table is None:
            raise ValueError("Official source database has no reports table")
        rows = db.execute(
            "SELECT id,url,title,published,body,sha256,error FROM reports ORDER BY id"
        ).fetchall()
    if not rows:
        raise ValueError("Official source database contains no reports")
    output: list[dict[str, object]] = []
    ids: set[str] = set()
    urls: set[str] = set()
    for row in rows:
        ident = str(row["id"])
        url = _canonical_url(row["url"])
        body = row["body"]
        supplied = row["sha256"]
        if ident in ids or url in urls:
            raise ValueError("Official source database contains duplicate IDs or URLs")
        if not isinstance(body, str) or not body.strip() or row["error"]:
            raise ValueError(f"Official report {ident} has no verified current body")
        calculated = hashlib.sha256(body.encode()).hexdigest()
        if not isinstance(supplied, str) or not SHA256.fullmatch(supplied) or supplied != calculated:
            raise ValueError(f"Official report {ident} has a stale or invalid body hash")
        ids.add(ident)
        urls.add(url)
        output.append(
            {
                "source_id": ident,
                "source_url": url,
                "title": " ".join(str(row["title"] or "").split()),
                "published": str(row["published"] or ""),
                "source_sha256": supplied,
            }
        )
    return output


def audit_against_official(
    snapshot: dict[str, object], official_db: Path | str
) -> dict[str, object]:
    """Match an upstream snapshot to official reports without semantic inference."""
    supplied_digest = snapshot.get("snapshot_sha256")
    unsigned = {key: value for key, value in snapshot.items() if key != "snapshot_sha256"}
    if not isinstance(supplied_digest, str) or supplied_digest != _digest(unsigned):
        raise ValueError("POLIZEIKARTE snapshot digest mismatch")
    entries = snapshot.get("entries")
    if not isinstance(entries, list) or len(entries) != snapshot.get("expected_total"):
        raise ValueError("POLIZEIKARTE snapshot is structurally incomplete")
    reports = _read_official_reports(official_db)

    by_url = {str(row["source_url"]): row for row in reports}
    by_presseportal: dict[str, list[dict[str, object]]] = {}
    for report in reports:
        article_id = _presseportal_article_id(str(report["source_url"]))
        if article_id:
            by_presseportal.setdefault(article_id, []).append(report)

    matches: list[dict[str, object]] = []
    unmatched_entries: list[dict[str, object]] = []
    matched_source_ids: set[str] = set()
    for raw in entries:
        if not isinstance(raw, dict):
            raise TypeError("POLIZEIKARTE snapshot entry must be an object")
        upstream_url = _canonical_url(raw.get("official_url"))
        report = by_url.get(upstream_url)
        method = "canonical_url"
        if report is None:
            article_id = _presseportal_article_id(upstream_url)
            candidates = by_presseportal.get(article_id or "", [])
            if len(candidates) == 1:
                report = candidates[0]
                method = "presseportal_article_id"
            elif len(candidates) > 1:
                raise ValueError("Official corpus has an ambiguous Presseportal article ID")
        if report is None:
            unmatched_entries.append(
                {
                    "entry_id": raw.get("entry_id"),
                    "official_url": upstream_url,
                    "category": raw.get("category"),
                    "occurred_at": raw.get("occurred_at"),
                    "title": raw.get("title"),
                }
            )
            continue
        source_id = str(report["source_id"])
        matched_source_ids.add(source_id)
        matches.append(
            {
                "entry_id": raw.get("entry_id"),
                "upstream_official_url": upstream_url,
                "source_id": source_id,
                "source_url": report["source_url"],
                "source_sha256": report["source_sha256"],
                "match_method": method,
            }
        )

    counts_by_source: dict[str, int] = {}
    for match in matches:
        source_id = str(match["source_id"])
        counts_by_source[source_id] = counts_by_source.get(source_id, 0) + 1
    duplicate_groups = [
        {"source_id": source_id, "upstream_entry_count": count}
        for source_id, count in sorted(counts_by_source.items())
        if count > 1
    ]
    report_ids = {str(row["source_id"]) for row in reports}
    audit: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "city": snapshot.get("city"),
        "snapshot_sha256": supplied_digest,
        "official_db": str(Path(official_db).resolve()),
        "coverage": {
            "official_reports_total": len(reports),
            "official_source_hashes_verified": len(reports),
            "upstream_entries_total": len(entries),
            "upstream_entries_directly_matched": len(matches),
            "upstream_entries_without_direct_match": len(unmatched_entries),
            "official_reports_directly_matched": len(matched_source_ids),
            "official_reports_without_direct_upstream_match": len(report_ids - matched_source_ids),
            "official_reports_with_multiple_upstream_entries": len(duplicate_groups),
        },
        "matching_basis": "canonical_url_or_exact_presseportal_article_id_only",
        "matches": matches,
        "unmatched_upstream_entries": unmatched_entries,
        "duplicate_upstream_groups": duplicate_groups,
        "upstream_semantics_accepted": False,
        "llm_review_bypassed": False,
        "owner_approval_required": True,
        "publication_ready": False,
    }
    audit["audit_sha256"] = _digest(audit)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit POLIZEIKARTE metadata coverage against an official source corpus"
    )
    parser.add_argument("--city", required=True, choices=sorted(SELECTED_CITY_SLUGS))
    parser.add_argument("--official-db", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    runtime = (Path.cwd() / ".runtime").resolve()
    if not args.out.resolve().is_relative_to(runtime):
        parser.error("Audit output must be under the current repository's .runtime directory")
    snapshot = collect_snapshot(args.city, delay=args.delay)
    audit = audit_against_official(snapshot, args.official_db)
    payload = {"snapshot": snapshot, "official_overlap_audit": audit}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "city": args.city,
                "output": str(args.out),
                "snapshot_sha256": snapshot["snapshot_sha256"],
                "audit_sha256": audit["audit_sha256"],
                **dict(audit["coverage"]),
                "publication_ready": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
