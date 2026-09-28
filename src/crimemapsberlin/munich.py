"""Offline staging for Munich police daily reports.

The Bavarian Police currently disallow all automated paths in robots.txt. This
module deliberately has no archive crawler: its only network operation checks
robots.txt, and local source documents must be supplied separately. Nothing
staged here is a published crime or a geocoded point.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from .local_document import verify_local_document

ORIGIN = "https://www.polizei.bayern.de"
ROBOTS_URL = ORIGIN + "/robots.txt"
ARCHIVE_URL = ORIGIN + "/suche/presse/index.html"
USER_AGENT = "CrimeMapsBerlin/0.1 (public police archive index)"
ARTICLE_PATH = re.compile(r"/aktuelles/pressemitteilungen/(\d+)/index\.html")
DAILY_TITLE = re.compile(r"Medieninformation der Polizei München vom (\d{2}\.\d{2}\.\d{4})")
ITEM_HEADING = re.compile(r"(?m)^\s*#{2,6}\s+(\d{1,5})\.\s+([^\n]+?)\s*$")
INDEX_HEADING = re.compile(r"(?m)^\s*(\d{1,5})\.\s+[^\n]+$")
LOCALITY_SUFFIX = re.compile(r"\s+[–—-]\s+([^\n]+)$")

# Exact names are from the City of Munich's official Stadtbezirke list:
# https://stadt.muenchen.de/rathaus/daten-fakten/bezirke.html
CITY_AREAS = {
    "Altstadt-Lehel", "Ludwigsvorstadt-Isarvorstadt", "Maxvorstadt", "Schwabing-West",
    "Au-Haidhausen", "Sendling", "Sendling-Westpark", "Schwanthalerhöhe",
    "Neuhausen-Nymphenburg", "Moosach", "Milbertshofen-Am Hart", "Schwabing-Freimann",
    "Bogenhausen", "Berg am Laim", "Trudering-Riem", "Ramersdorf-Perlach",
    "Obergiesing-Fasangarten", "Untergiesing-Harlaching",
    "Thalkirchen-Obersendling-Forstenried-Fürstenried-Solln", "Hadern",
    "Pasing-Obermenzing", "Aubing-Lochhausen-Langwied", "Allach-Untermenzing",
    "Feldmoching-Hasenbergl", "Laim",
    # Stadtteile explicitly linked under the city districts in the same source.
    "Altstadt", "Lehel", "Ludwigsvorstadt", "Isarvorstadt", "Au", "Haidhausen",
    "Nymphenburg", "Neuhausen", "Milbertshofen", "Am Hart", "Schwabing",
    "Freimann", "Trudering", "Riem", "Ramersdorf", "Perlach", "Obergiesing",
    "Untergiesing", "Harlaching", "Thalkirchen", "Obersendling", "Forstenried",
    "Fürstenried", "Solln", "Pasing", "Obermenzing", "Aubing", "Lochhausen",
    "Langwied", "Allach", "Untermenzing", "Feldmoching", "Hasenbergl",
}

# Landkreis München's official municipality directory. This is only a negative
# exact-match aid; a locality absent from both sets remains unverified.
# https://familienleben.landkreis-muenchen.de/wissenswertes/kommunen-des-landkreises
COUNTY_MUNICIPALITIES = {
    "Aschheim", "Aying", "Baierbrunn", "Brunnthal", "Feldkirchen", "Garching",
    "Gräfelfing", "Grasbrunn", "Grünwald", "Haar", "Hohenbrunn",
    "Höhenkirchen-Siegertsbrunn", "Ismaning", "Kirchheim", "Neubiberg", "Neuried",
    "Oberhaching", "Oberschleißheim", "Ottobrunn", "Planegg", "Pullach",
    "Putzbrunn", "Sauerlach", "Schäftlarn", "Straßlach-Dingharting",
    "Taufkirchen", "Unterföhring", "Unterhaching", "Unterschleißheim",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    source_id TEXT PRIMARY KEY, source_url TEXT NOT NULL, title TEXT NOT NULL,
    publisher TEXT NOT NULL, published TEXT NOT NULL, source_text TEXT NOT NULL,
    source_sha256 TEXT NOT NULL, revision INTEGER NOT NULL, ingest_mode TEXT NOT NULL,
    checked TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
    item_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES articles(source_id),
    item_number INTEGER NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
    sha256 TEXT NOT NULL, locality TEXT NOT NULL, city_scope TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'pending',
    UNIQUE(source_id, item_number)
);
CREATE TABLE IF NOT EXISTS article_revisions (
    source_id TEXT NOT NULL, revision INTEGER NOT NULL, sha256 TEXT NOT NULL,
    observed TEXT NOT NULL, PRIMARY KEY(source_id, revision)
);
CREATE TABLE IF NOT EXISTS local_evidence (
    source_id TEXT PRIMARY KEY REFERENCES articles(source_id),
    path TEXT NOT NULL, sha256 TEXT NOT NULL, format TEXT NOT NULL,
    text_matches_file INTEGER NOT NULL
);
"""


def robots_status(client: httpx.Client) -> dict[str, object]:
    """Inspect permission only; do not request an archive or article page."""
    response = client.get(ROBOTS_URL, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    if response.status_code != 200 or str(response.url) != ROBOTS_URL or "user-agent:" not in response.text.lower():
        raise ValueError("Missing or unexpected robots.txt response")
    robots = RobotFileParser()
    robots.parse(response.text.splitlines())
    return {
        "robots_url": ROBOTS_URL,
        "archive_allowed": robots.can_fetch(USER_AGENT, ARCHIVE_URL),
        "article_allowed": robots.can_fetch(
            USER_AGENT, ORIGIN + "/aktuelles/pressemitteilungen/105609/index.html"
        ),
        "crawl_delay": robots.crawl_delay(USER_AGENT),
    }


def item_scope(title: str) -> tuple[str, str]:
    """Return a conservative city candidate, outside, or unverified label."""
    match = LOCALITY_SUFFIX.search(title)
    if not match:
        return "", "unverified"
    locality = " ".join(match[1].split()).rstrip(" .")
    if locality in CITY_AREAS or locality in {"München", "Landeshauptstadt München"}:
        return locality, "city_candidate"
    if locality in COUNTY_MUNICIPALITIES or locality.startswith("Landkreis München"):
        return locality, "outside"
    return locality, "unverified"


def split_daily_items(text: str) -> list[dict[str, object]]:
    """Split numbered *body sections*, never the duplicated table of contents."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    headings = list(ITEM_HEADING.finditer(text))
    if not headings:
        raise ValueError("No numbered daily-report body headings; parser/source changed")
    if "Inhalt:" in text[: headings[0].start()]:
        contents_start = text.index("Inhalt:") + len("Inhalt:")
        index = text[contents_start:headings[0].start()]
        listed = [int(m[1]) for m in INDEX_HEADING.finditer(index)]
        numbered = [int(m[1]) for m in headings]
        if not listed or listed != numbered:
            raise ValueError("Contents list does not match numbered body sections")
    items = []
    seen = set()
    for n, heading in enumerate(headings):
        number = int(heading[1])
        if number in seen:
            raise ValueError(f"Duplicate item number {number}")
        seen.add(number)
        title = " ".join(heading[2].split())
        end = headings[n + 1].start() if n + 1 < len(headings) else len(text)
        body = text[heading.end():end].strip()
        body = re.sub(r"(?s)(?:\n\s*\*\s*\*\s*\*\s*)+$", "", body).strip()
        if len(body) < 30:
            raise ValueError(f"Item {number} has no complete body")
        locality, scope = item_scope(title)
        items.append({"number": number, "title": title, "body": body,
                      "locality": locality, "city_scope": scope})
    return items


def parse_daily_document(document: dict[str, str]) -> tuple[str, list[dict[str, object]]]:
    """Validate an offline copy's claimed official provenance before staging it."""
    required = {"source_url", "publisher", "published", "title", "text"}
    if not required.issubset(document):
        raise ValueError("Missing daily-report source metadata")
    url = urlparse(document["source_url"])
    match = ARTICLE_PATH.fullmatch(url.path)
    if url.scheme != "https" or url.netloc != "www.polizei.bayern.de" or url.query or url.fragment or not match:
        raise ValueError("Unexpected Munich police article URL")
    if document["publisher"].strip() != "Polizeipräsidium München":
        raise ValueError("Not a Polizeipräsidium München publication")
    daily = DAILY_TITLE.fullmatch(document["title"].strip())
    if not daily:
        raise ValueError("Not a Munich numbered daily report")
    published = date.fromisoformat(document["published"])
    day, month, year = map(int, daily[1].split("."))
    if date(year, month, day) != published:
        raise ValueError("Daily report title and publication date differ")
    return match[1], split_daily_items(document["text"])


def connect(path: Path | str) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    return db


def stage_document(db: sqlite3.Connection, document: dict[str, str]) -> dict[str, object]:
    """Atomically checkpoint an offline document and every numbered item."""
    source_id, items = parse_daily_document(document)
    evidence = None
    if "source_file" in document or "source_file_sha256" in document:
        if not document.get("source_file") or not document.get("source_file_sha256"):
            raise ValueError("Local source file and SHA-256 must be supplied together")
        evidence = verify_local_document(
            document["source_file"], document["source_file_sha256"], document["text"]
        )
    canonical = json.dumps(
        {
            **{key: document[key] for key in ("source_url", "publisher", "published", "title", "text")},
            "source_file_sha256": evidence["sha256"] if evidence else None,
        },
        ensure_ascii=False, sort_keys=True,
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    previous = db.execute(
        "SELECT revision, source_sha256 FROM articles WHERE source_id=?", (source_id,)
    ).fetchone()
    if previous and previous["source_sha256"] == digest:
        if evidence:
            with db:
                db.execute(
                    """INSERT INTO local_evidence VALUES(?,?,?,?,?)
                    ON CONFLICT(source_id) DO UPDATE SET path=excluded.path,
                    sha256=excluded.sha256,format=excluded.format,
                    text_matches_file=excluded.text_matches_file""",
                    (source_id, evidence["path"], evidence["sha256"], evidence["format"],
                     int(evidence["text_matches_file"])),
                )
        return {"source_id": source_id, "items": len(items), "result": "unchanged"}
    revision = 1 if previous is None else previous["revision"] + 1
    observed = datetime.now(UTC).isoformat()
    with db:
        db.execute(
            """INSERT INTO articles VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_id) DO UPDATE SET
            source_url=excluded.source_url, title=excluded.title,
            publisher=excluded.publisher, published=excluded.published,
            source_text=excluded.source_text, source_sha256=excluded.source_sha256,
            revision=excluded.revision, ingest_mode=excluded.ingest_mode,
            checked=excluded.checked""",
            (source_id, document["source_url"], document["title"], document["publisher"],
             document["published"], document["text"], digest, revision,
             "offline_supplied_unverified", observed),
        )
        db.execute("DELETE FROM items WHERE source_id=?", (source_id,))
        db.executemany(
            """INSERT INTO items(item_id,source_id,item_number,title,body,sha256,locality,city_scope)
            VALUES(?,?,?,?,?,?,?,?)""",
            [(
                f"{source_id}:{item['number']}", source_id, item["number"], item["title"], item["body"],
                hashlib.sha256((item["title"] + "\n" + item["body"]).encode()).hexdigest(),
                item["locality"], item["city_scope"],
            ) for item in items],
        )
        db.execute("INSERT INTO article_revisions VALUES(?,?,?,?)",
                   (source_id, revision, digest, observed))
        db.execute("DELETE FROM local_evidence WHERE source_id=?", (source_id,))
        if evidence:
            db.execute(
                "INSERT INTO local_evidence VALUES(?,?,?,?,?)",
                (source_id, evidence["path"], evidence["sha256"], evidence["format"],
                 int(evidence["text_matches_file"])),
            )
    return {"source_id": source_id, "items": len(items),
            "result": "new" if previous is None else "revised"}


def review_rows(db_path: Path | str, *, limit: int = 100, offset: int = 0) -> list[dict[str, object]]:
    """Read-only, hash-checked numbered announcements for source-first review."""
    if not 1 <= limit <= 200:
        raise ValueError("Review limit must be 1–200")
    if offset < 0:
        raise ValueError("Review offset must be nonnegative")
    path = Path(db_path)
    if not path.is_file():
        raise ValueError("Munich source checkpoint is missing")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        has_evidence = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='local_evidence'"
        ).fetchone() is not None
        rows = []
        seen = 0
        for article in db.execute("SELECT * FROM articles ORDER BY published,source_id"):
            source_id, _ = parse_daily_document({
                "source_url": article["source_url"], "publisher": article["publisher"],
                "published": article["published"], "title": article["title"],
                "text": article["source_text"],
            })
            if source_id != article["source_id"]:
                raise ValueError("Munich source ID mismatch")
            evidence = db.execute(
                "SELECT * FROM local_evidence WHERE source_id=?", (article["source_id"],)
            ).fetchone() if has_evidence else None
            file_sha = None
            if evidence:
                checked = verify_local_document(
                    evidence["path"], evidence["sha256"], article["source_text"]
                )
                if checked["format"] != evidence["format"] or int(checked["text_matches_file"]) != evidence["text_matches_file"]:
                    raise ValueError("Munich local evidence metadata changed")
                file_sha = evidence["sha256"]
            payload = {key: article[key] for key in ("source_url", "publisher", "published", "title")}
            payload["text"] = article["source_text"]
            canonical = json.dumps(
                {**payload, "source_file_sha256": file_sha}, ensure_ascii=False, sort_keys=True,
            )
            legacy = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            valid_hashes = {hashlib.sha256(canonical.encode()).hexdigest()}
            if file_sha is None:
                valid_hashes.add(hashlib.sha256(legacy.encode()).hexdigest())
            if article["source_sha256"] not in valid_hashes:
                raise ValueError("Munich source hash mismatch")
            revision = db.execute(
                "SELECT sha256 FROM article_revisions WHERE source_id=? AND revision=?",
                (article["source_id"], article["revision"]),
            ).fetchone()
            if revision is None or revision["sha256"] != article["source_sha256"]:
                raise ValueError("Munich revision hash mismatch")
            expected = {item["number"]: item for item in split_daily_items(article["source_text"])}
            saved = db.execute(
                "SELECT * FROM items WHERE source_id=? ORDER BY item_number", (article["source_id"],)
            ).fetchall()
            if len(saved) != len(expected):
                raise ValueError("Munich numbered item set is incomplete")
            for item in saved:
                parsed = expected.get(item["item_number"])
                if parsed is None or any(item[key] != parsed[key] for key in ("title", "body", "city_scope", "locality")):
                    raise ValueError("Munich numbered item differs from source")
                digest = hashlib.sha256((item["title"] + "\n" + item["body"]).encode()).hexdigest()
                if digest != item["sha256"] or item["item_id"] != f"{article['source_id']}:{item['item_number']}":
                    raise ValueError("Munich numbered item hash mismatch")
                if seen < offset:
                    seen += 1
                    continue
                rows.append({
                    "city": "munich", "id": item["item_id"], "source_id": article["source_id"],
                    "source_url": article["source_url"], "published": article["published"],
                    "title": item["title"], "source_body": item["title"] + "\n" + item["body"],
                    "source_sha256": digest, "parent_source_sha256": article["source_sha256"],
                    "source_file_sha256": file_sha, "source_file_format": evidence["format"] if evidence else None,
                    "source_file_text_matches": bool(evidence["text_matches_file"]) if evidence else None,
                    "source_file_path": evidence["path"] if evidence else None,
                    "revision": article["revision"], "city_scope": item["city_scope"],
                    "review_status": item["review_status"], "source_verified": False,
                    "publication_ready": False,
                })
                if len(rows) >= limit:
                    return rows
        return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage offline Munich police daily reports")
    parser.add_argument("--check-robots", action="store_true")
    parser.add_argument("--import-json", type=Path, help="Local JSON document under .runtime/")
    parser.add_argument("--export-review", type=Path, help="Write local, hash-checked item NDJSON")
    parser.add_argument("--review-limit", type=int, default=100)
    parser.add_argument("--review-offset", type=int, default=0)
    parser.add_argument("--db", type=Path,
                        default=Path(".runtime/safety/cities/munich/police.sqlite"))
    args = parser.parse_args()
    if args.check_robots:
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            status = robots_status(client)
        print(json.dumps(status, indent=2))
        if not status["archive_allowed"] or not status["article_allowed"]:
            raise SystemExit(2)
        return
    if args.import_json is None and args.export_review is None:
        parser.error("Provide --check-robots, --import-json or --export-review")
    runtime = (Path.cwd() / ".runtime").resolve()
    paths = [args.db, args.import_json, args.export_review]
    if any(path and not path.resolve().is_relative_to(runtime) for path in paths):
        parser.error("Input, output and SQLite checkpoint must be under .runtime/")
    if args.import_json is not None:
        if args.import_json.stat().st_size > 20_000_000:
            parser.error("Local Munich import is too large")
        document = json.loads(args.import_json.read_text(encoding="utf-8"))
        if document.get("source_file") and not Path(document["source_file"]).is_absolute():
            document["source_file"] = str(args.import_json.parent / document["source_file"])
        if document.get("source_file") and not Path(document["source_file"]).resolve().is_relative_to(runtime):
            parser.error("Local source file must be under .runtime/")
        with connect(args.db) as db:
            result = stage_document(db, document)
        print(json.dumps(result, indent=2))
    if args.export_review is not None:
        if args.export_review.suffix != ".ndjson" or args.export_review.resolve() == args.db.resolve():
            parser.error("Review output must be a distinct .ndjson file")
        rows = review_rows(args.db, limit=args.review_limit, offset=args.review_offset)
        args.export_review.parent.mkdir(parents=True, exist_ok=True)
        args.export_review.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
        )
        print(json.dumps({"review_rows": len(rows), "output": str(args.export_review)}))


if __name__ == "__main__":
    main()
