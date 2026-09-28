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
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

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
    if url.scheme != "https" or url.netloc != "www.polizei.bayern.de" or url.query or not match:
        raise ValueError("Unexpected Munich police article URL")
    if document["publisher"].strip() != "Polizeipräsidium München":
        raise ValueError("Not a Polizeipräsidium München publication")
    daily = DAILY_TITLE.fullmatch(document["title"].strip())
    if not daily:
        raise ValueError("Not a Munich numbered daily report")
    published = date.fromisoformat(document["published"])
    if datetime.strptime(daily[1], "%d.%m.%Y").date() != published:
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
    canonical = json.dumps(
        {key: document[key] for key in ("source_url", "publisher", "published", "title", "text")},
        ensure_ascii=False, sort_keys=True,
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    previous = db.execute(
        "SELECT revision, source_sha256 FROM articles WHERE source_id=?", (source_id,)
    ).fetchone()
    if previous and previous["source_sha256"] == digest:
        return {"source_id": source_id, "items": len(items), "result": "unchanged"}
    revision = 1 if previous is None else previous["revision"] + 1
    observed = datetime.now(timezone.utc).isoformat()
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
    return {"source_id": source_id, "items": len(items),
            "result": "new" if previous is None else "revised"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage offline Munich police daily reports")
    parser.add_argument("--check-robots", action="store_true")
    parser.add_argument("--import-json", type=Path, help="Local JSON document under .runtime/")
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
    if args.import_json is None:
        parser.error("Provide --check-robots or --import-json")
    runtime = (Path.cwd() / ".runtime").resolve()
    if not args.import_json.resolve().is_relative_to(runtime) or not args.db.resolve().is_relative_to(runtime):
        parser.error("Input and SQLite checkpoint must both be under .runtime/")
    document = json.loads(args.import_json.read_text(encoding="utf-8"))
    with connect(args.db) as db:
        result = stage_document(db, document)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
