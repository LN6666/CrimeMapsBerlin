"""Checkpointed collector for the native Polizei Köln press archive.

The issuing authority covers Köln, Leverkusen and regional motorways.  The
``city_scope`` field is therefore only a conservative review lead, never a
geocode or a decision to publish an announcement on the Köln city map.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sqlite3
import time
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

ORIGIN = "https://koeln.polizei.nrw"
ARCHIVE = ORIGIN + "/presse/pressemitteilungen"
USER_AGENT = "CrimeMapsBerlin/0.1 (native Polizei Koeln press archive)"
ARTICLE_PATH = re.compile(r"/presse/[a-z0-9][a-z0-9-]*$")
NODE_ID = re.compile(r'"currentPath":"node\\?/+(\d+)"')
CANONICAL = re.compile(r'<link\s+rel="canonical"\s+href="([^"]+)"')
NEXT_PAGE = re.compile(r'href="\?[^\"]*?\bpage=(\d+)"[^>]*title="Zur nächsten Seite"')
SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
 source_url TEXT PRIMARY KEY,
 source_id TEXT UNIQUE,
 title TEXT NOT NULL,
 published TEXT NOT NULL,
 body TEXT,
 sha256 TEXT,
 etag TEXT,
 modified TEXT,
 checked REAL,
 retry_after REAL NOT NULL DEFAULT 0,
 failures INTEGER NOT NULL DEFAULT 0,
 error TEXT,
 first_seen REAL NOT NULL,
 revision INTEGER NOT NULL DEFAULT 0,
 city_scope TEXT NOT NULL DEFAULT 'needs_review',
 scope_evidence TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS revisions (
 source_id TEXT NOT NULL, revision INTEGER NOT NULL,
 sha256 TEXT NOT NULL, observed REAL NOT NULL,
 PRIMARY KEY(source_id, revision)
);
CREATE TABLE IF NOT EXISTS archive_scan (
 year INTEGER PRIMARY KEY, next_page INTEGER NOT NULL,
 complete INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
 started REAL PRIMARY KEY, finished REAL, summary TEXT
);
"""


def _text(value: str) -> str:
    return " ".join(html.unescape(value).split())


def _article_url(value: str) -> str:
    parsed = urlparse(urljoin(ORIGIN, html.unescape(value)))
    if (parsed.scheme, parsed.netloc) != ("https", "koeln.polizei.nrw"):
        raise ValueError("Article URL escaped the Polizei Köln origin")
    if not ARTICLE_PATH.fullmatch(parsed.path) or parsed.query or parsed.fragment:
        raise ValueError("Unexpected native press article path")
    return parsed.geturl()


class ListingParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.view_depth = None
        self.row_depth = None
        self.field = None
        self.rows_seen = 0
        self.rows = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if tag == "div":
            self.depth += 1
            if "view-list-view-press-releases-solr" in classes:
                self.view_depth = self.depth
            elif self.view_depth is not None and self.row_depth is None and "views-row" in classes:
                self.row_depth = self.depth
                self.rows_seen += 1
                self.current = {"url": "", "title": "", "published": "", "district": ""}
            elif self.current is not None and "combined-location" in classes:
                self.field = "authority"
                self.current["authority"] = ""
        if self.current is None:
            return
        if tag == "h2" and "field-title" in classes:
            self.field = "title"
        elif tag == "a" and self.field == "title":
            self.current["url"] = _article_url(attrs.get("href", ""))
        elif tag == "time":
            self.current["published"] = attrs.get("datetime", "")

    def handle_data(self, data):
        if self.current is not None and self.field:
            self.current[self.field] += data

    def handle_endtag(self, tag):
        if tag == "h2" and self.field == "title":
            self.field = None
        if tag != "div":
            return
        if self.current is not None and self.field == "authority":
            self.field = None
        if self.row_depth == self.depth:
            row = self.current
            if row is not None:
                row["title"] = _text(row["title"])
                row["authority"] = _text(row.get("authority", ""))
                if row["url"] and row["title"] and row["published"] and row["authority"].startswith("Polizei Köln"):
                    datetime.fromisoformat(row["published"])
                    row["id"] = urlparse(row["url"]).path.removeprefix("/presse/")
                    self.rows.append(row)
            self.current = None
            self.row_depth = None
        if self.view_depth == self.depth:
            self.view_depth = None
        self.depth -= 1


def listing_rows(page: str) -> list[dict]:
    parser = ListingParser()
    parser.feed(page)
    if not parser.rows_seen or parser.rows_seen != len(parser.rows):
        raise ValueError("Native Köln archive contains unparsed or foreign rows")
    dates = [row["published"] for row in parser.rows]
    if dates != sorted(dates, reverse=True):
        raise ValueError("Native Köln archive order changed")
    return parser.rows


def next_archive_page(page: str) -> int | None:
    match = NEXT_PAGE.search(page)
    return int(match[1]) if match else None


class NativeArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.body_depth = None
        self.author_depth = None
        self.author = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag != "div":
            return
        self.depth += 1
        classes = dict(attrs).get("class", "").split()
        if "field--name-body" in classes:
            self.body_depth = self.depth
        elif "field--name-field-press-release-author" in classes:
            self.author_depth = self.depth

    def handle_data(self, data):
        if self.body_depth is not None:
            self.parts.append(" " + data)
        if self.author_depth is not None:
            self.author.append(data)

    def handle_endtag(self, tag):
        if self.body_depth is not None and tag in {"p", "li", "br"}:
            self.parts.append("\n")
        if tag == "div":
            if self.depth == self.body_depth:
                self.body_depth = None
            if self.depth == self.author_depth:
                self.author_depth = None
            self.depth -= 1

    def handle_startendtag(self, tag, attrs):
        if self.body_depth is not None and tag == "br":
            self.parts.append("\n")


def article_record(page: str, requested_url: str) -> dict:
    # The native article exposes Drupal's stable node ID; the alias alone may change.
    match = NODE_ID.search(page)
    canonical = CANONICAL.search(page)
    if not match or not canonical:
        raise ValueError("Native Köln article ID or canonical URL missing")
    url = _article_url(canonical[1])
    if url != requested_url:
        # A changed alias is valid only when the HTTP layer redirected to it.
        raise ValueError("Native Köln canonical URL differs from fetched URL")
    if not re.search(r'<article\s+about="' + re.escape(urlparse(url).path) + r'"[^>]*node--type--press-release', page):
        raise ValueError("Not a native Polizei Köln press-release article")
    parser = NativeArticleParser()
    # Limit parsing to the actual press-release article; contacts/sidebar follow it.
    article = re.search(r'<article\s+about="' + re.escape(urlparse(url).path) + r'".*?</article>', page, re.S)
    if not article:
        raise ValueError("Native press-release article container missing")
    parser.feed(article[0])
    author = _text("".join(parser.author))
    body = "\n".join(_text(part) for part in "".join(parser.parts).splitlines() if _text(part))
    if author != "Polizei Köln" or len(body) < 30:
        raise ValueError("Native Köln publisher or body check failed")
    return {"source_id": match[1], "source_url": url, "body": body}


COLOGNE = re.compile(r"\b(?:in\s+Köln(?:-[\wÄÖÜäöüß]+)?|Köln-[\wÄÖÜäöüß]+|im\s+Kölner\s+Stadtteil|in\s+der\s+Kölner\s+Innenstadt)\b", re.I)
OUTSIDE = re.compile(
    r"\b(?:in|bei)\s+(?:Leverkusen|Erftstadt|Weisweiler|Düsseldorf|Bonn|Gevelsberg|Kleve|"
    r"Pulheim|Bergheim|Hürth|Frechen|Brühl|Wesseling|Dormagen|Bergisch\s+Gladbach)"
    r"(?:-[\wÄÖÜäöüß]+)?\b"
    r"|\b(?:Leverkusen|Erftstadt|Weisweiler|Düsseldorf|Gevelsberg|Pulheim|Bergheim|"
    r"Hürth|Frechen|Brühl|Wesseling|Dormagen)-[\wÄÖÜäöüß]+",
    re.I,
)
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


def city_scope(title: str, body: str) -> tuple[str, str]:
    """Return a municipal review lead, not an incident-scene finding."""
    # Ignore publisher/contact boilerplate before checking the narrative.
    narrative = re.sub(r"\b(?:Polizei|Polizeipräsidium|Staatsanwaltschaft)\s+Köln\b", "", title + "\n" + body)
    inside = _scene_scope_match(COLOGNE, narrative)
    outside = _scene_scope_match(OUTSIDE, narrative)
    if inside and outside:
        return "needs_review", f"mixed municipality mentions: {inside[0]}; {outside[0]}"
    if inside:
        return "cologne_candidate", inside[0]
    if outside:
        return "outside_candidate", outside[0]
    return "needs_review", "no unambiguous Köln municipality mention"


def connect(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    db.execute("PRAGMA journal_mode=WAL")
    return db


def discover(db: sqlite3.Connection, rows: list[dict], now: float) -> None:
    for row in rows:
        db.execute(
            """INSERT INTO reports(source_url,title,published,first_seen)
               VALUES(?,?,?,?) ON CONFLICT(source_url) DO UPDATE SET
               title=excluded.title,published=excluded.published""",
            (row["url"], row["title"], row["published"], now),
        )
    db.commit()


def accept(db: sqlite3.Connection, url: str, record: dict, headers: dict, now: float) -> str:
    canonical_url = record["source_url"]
    existing = db.execute("SELECT * FROM reports WHERE source_id=?", (record["source_id"],)).fetchone()
    if existing is not None and existing["source_url"] != canonical_url:
        # The canonical alias changed. Retain the old body/revisions and move its key.
        db.execute("DELETE FROM reports WHERE source_url=? AND source_id IS NULL", (canonical_url,))
        db.execute("UPDATE reports SET source_url=? WHERE source_id=?", (canonical_url, record["source_id"]))
    elif canonical_url != url:
        db.execute("UPDATE reports SET source_url=? WHERE source_url=?", (canonical_url, url))
    row = db.execute("SELECT * FROM reports WHERE source_url=?", (canonical_url,)).fetchone()
    if row is None:
        raise ValueError("Article not discovered in archive")
    body = record["body"]
    digest = hashlib.sha256(body.encode()).hexdigest()
    changed = row["sha256"] != digest
    revision = row["revision"] + int(changed)
    scope, evidence = city_scope(row["title"], body)
    db.execute(
        """UPDATE reports SET source_id=?,body=?,sha256=?,etag=?,modified=?,checked=?,
           error=NULL,retry_after=0,failures=0,revision=?,city_scope=?,scope_evidence=?
           WHERE source_url=?""",
        (record["source_id"], body, digest, headers.get("etag"), headers.get("last-modified"),
         now, revision, scope, evidence, canonical_url),
    )
    if changed:
        db.execute("INSERT INTO revisions VALUES(?,?,?,?)", (record["source_id"], revision, digest, now))
    db.commit()
    return "new" if row["sha256"] is None else "revised" if changed else "unchanged"


def fail(db: sqlite3.Connection, url: str, error: str, now: float) -> None:
    row = db.execute("SELECT failures FROM reports WHERE source_url=?", (url,)).fetchone()
    failures = row[0] + 1
    retry_after = now + min(86400, 300 * 2 ** min(failures - 1, 8))
    db.execute(
        "UPDATE reports SET failures=?,error=?,retry_after=? WHERE source_url=?",
        (failures, error[:200], retry_after, url),
    )
    db.commit()


def archive_url(year: int, page: int) -> str:
    query = {"created_1": f"01.01.{year}", "created_2": f"31.12.{year}"}
    if page:
        query["page"] = str(page)
    return ARCHIVE + "?" + urlencode(query)


def sync(path: str | Path, year: int, *, full: bool = False, max_pages: int = 2,
         limit: int = 20, delay: float = 1.0) -> dict:
    if not 2015 <= year <= datetime.now().year or not 1 <= max_pages <= 100 or not 1 <= limit <= 500 or delay < 1:
        raise ValueError("Use an available year, 1–100 pages, 1–500 articles and delay >= 1 second")
    db = connect(path)
    started = time.time()
    stats = dict(year=year, full_archive_scan=full, archive_pages=0, discovered=0,
                 new=0, revised=0, unchanged=0, failed=0)
    db.execute("INSERT INTO runs(started) VALUES(?)", (started,))
    db.commit()
    try:
        with httpx.Client(timeout=25, follow_redirects=False, headers={"User-Agent": USER_AGENT}) as client:
            robots_response = client.get(ORIGIN + "/robots.txt")
            robots_response.raise_for_status()
            if (
                robots_response.status_code != 200
                or str(robots_response.url) != ORIGIN + "/robots.txt"
                or "user-agent:" not in robots_response.text.lower()
            ):
                raise ValueError("Missing or unexpected native archive robots.txt")
            robots = RobotFileParser()
            robots.parse(robots_response.text.splitlines())
            delay = max(delay, float(robots.crawl_delay(USER_AGENT) or 0))
            last_request = time.monotonic()

            def get(url: str, headers: dict | None = None) -> httpx.Response:
                nonlocal last_request
                for _ in range(4):
                    parsed = urlparse(url)
                    if (parsed.scheme, parsed.netloc) != ("https", "koeln.polizei.nrw"):
                        raise ValueError("Unexpected native archive origin")
                    if not robots.can_fetch(USER_AGENT, url):
                        raise ValueError("robots.txt disallows " + url)
                    time.sleep(max(0, delay - (time.monotonic() - last_request)))
                    last_request = time.monotonic()
                    response = client.get(url, headers=headers)
                    if response.status_code in (301, 302, 303, 307, 308):
                        url = urljoin(str(response.url), response.headers["location"])
                        continue
                    if response.status_code != 304:
                        response.raise_for_status()
                    return response
                raise ValueError("Too many native archive redirects")

            state = db.execute("SELECT next_page,complete FROM archive_scan WHERE year=?", (year,)).fetchone()
            page_number = state["next_page"] if full and state and not state["complete"] else 0
            for _ in range(max_pages if full else min(max_pages, 2)):
                page = get(archive_url(year, page_number)).text
                rows = listing_rows(page)
                if any(not row["published"].startswith(str(year)) for row in rows):
                    raise ValueError("Native archive ignored year filter")
                discover(db, rows, time.time())
                stats["archive_pages"] += 1
                stats["discovered"] += len(rows)
                following = next_archive_page(page)
                if following is not None and following != page_number + 1:
                    raise ValueError("Native archive pagination gap or loop")
                complete = following is None
                if full:
                    db.execute(
                        """INSERT INTO archive_scan(year,next_page,complete,updated) VALUES(?,?,?,?)
                           ON CONFLICT(year) DO UPDATE SET next_page=excluded.next_page,
                           complete=excluded.complete,updated=excluded.updated""",
                        (year, 0 if complete else following, int(complete), time.time()),
                    )
                    db.commit()
                if complete:
                    break
                page_number = following

            pending = db.execute(
                """SELECT * FROM reports WHERE published LIKE ? AND retry_after<=? AND
                   (body IS NULL OR checked IS NULL OR checked<? OR published>=?)
                   ORDER BY body IS NOT NULL,COALESCE(checked,0),published DESC LIMIT ?""",
                (f"{year}-%", started, started - 7 * 86400,
                 datetime.fromtimestamp(started - 2 * 86400).isoformat()[:19], limit),
            ).fetchall()
            for row in pending:
                headers = {}
                if row["etag"]:
                    headers["If-None-Match"] = row["etag"]
                if row["modified"]:
                    headers["If-Modified-Since"] = row["modified"]
                try:
                    response = get(row["source_url"], headers)
                    if response.status_code == 304:
                        if row["body"] is None:
                            raise ValueError("304 without cached native article")
                        db.execute("UPDATE reports SET checked=?,error=NULL,failures=0,retry_after=0 WHERE source_url=?",
                                   (time.time(), row["source_url"]))
                        db.commit()
                        stats["unchanged"] += 1
                    else:
                        record = article_record(response.text, str(response.url))
                        stats[accept(db, row["source_url"], record, response.headers, time.time())] += 1
                except (httpx.HTTPError, ValueError) as exc:
                    fail(db, row["source_url"], f"{type(exc).__name__}: {exc}", time.time())
                    stats["failed"] += 1
            stats["stored"] = db.execute("SELECT count(*) FROM reports WHERE published LIKE ? AND body IS NOT NULL",
                                          (f"{year}-%",)).fetchone()[0]
            stats["pending"] = db.execute("SELECT count(*) FROM reports WHERE published LIKE ? AND body IS NULL",
                                           (f"{year}-%",)).fetchone()[0]
            stats["errors"] = db.execute("SELECT count(*) FROM reports WHERE published LIKE ? AND error IS NOT NULL",
                                          (f"{year}-%",)).fetchone()[0]
            stats["scope"] = {r["city_scope"]: r["count"] for r in db.execute(
                "SELECT city_scope,count(*) AS count FROM reports WHERE published LIKE ? AND body IS NOT NULL GROUP BY city_scope",
                (f"{year}-%",))}
            scan = db.execute("SELECT next_page,complete FROM archive_scan WHERE year=?", (year,)).fetchone()
            stats["archive_complete"] = bool(scan["complete"]) if scan else False
            stats["next_page"] = scan["next_page"] if scan else None
    finally:
        db.execute("UPDATE runs SET finished=?,summary=? WHERE started=?",
                   (time.time(), json.dumps(stats), started))
        db.commit()
        db.close()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=".runtime/safety/cities/cologne/police.sqlite")
    parser.add_argument("--year", type=int, default=datetime.now().year)
    parser.add_argument("--full", action="store_true", help="resume the bounded full-year native archive scan")
    parser.add_argument("--max-pages", type=int, default=2)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    import fcntl

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    with open(args.db + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = sync(args.db, args.year, full=args.full, max_pages=args.max_pages,
                      limit=args.limit, delay=args.delay)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["failed"] or result["errors"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
