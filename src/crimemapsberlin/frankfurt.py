"""Frankfurt police press-office newsroom intake, stored only in local SQLite.

The Hessian police press office links to this publisher newsroom. Publisher
identity does not establish that every reported incident is inside Frankfurt.
No geometry or public map is produced here.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from .collector import accept, connect, discover, fail

ORIGIN = "https://www.presseportal.de"
NEWSROOM = ORIGIN + "/blaulicht/nr/4970"
PUBLISHER = "Polizeipräsidium Frankfurt am Main"
ARTICLE_PATH = re.compile(r"/blaulicht/pm/4970/(\d+)$")
PAGE_PATH = re.compile(r"/blaulicht/nr/4970(?:/\d+)?$")
NEXT_PAGE = re.compile(r'<link\s+rel="next"\s+href="([^"]+)"')
PARSER_VERSION = 3


class NewsroomParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.articles_seen = 0
        self.current = None
        self.field = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if tag == "article" and "news" in classes:
            self.articles_seen += 1
            if attrs.get("data-label", "").isdigit():
                self.current = {
                    "id": attrs["data-label"],
                    "url": "",
                    "title": "",
                    "published": "",
                    "district": "",
                }
        if self.current is None:
            return
        if tag == "div" and "date" in classes:
            self.field = "published"
        elif tag == "h3" and "news-headline-clamp" in classes:
            self.field = "title"
        elif tag == "a" and self.field == "title":
            url = urljoin(ORIGIN, attrs.get("href", ""))
            parsed = urlparse(url)
            match = ARTICLE_PATH.fullmatch(parsed.path)
            if (
                parsed.scheme == "https"
                and parsed.netloc == "www.presseportal.de"
                and match
                and match[1] == self.current["id"]
            ):
                self.current["url"] = url

    def handle_data(self, data):
        if self.current is not None and self.field:
            self.current[self.field] += data

    def handle_endtag(self, tag):
        if self.current is None:
            return
        if tag in {"div", "h3"}:
            self.field = None
        elif tag == "article":
            row = self.current
            if row["url"] and row["title"] and row["published"]:
                # Preserve the site's wall-clock timestamp in the existing report schema.
                row["published"] = datetime.strptime(  # noqa: DTZ007
                    " ".join(row["published"].replace("–", " ").split()),
                    "%d.%m.%Y %H:%M",
                ).isoformat()
                row["title"] = " ".join(row["title"].split())
                self.rows.append(row)
            self.current = None
            self.field = None


class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_story = False
        self.after_heading = False
        self.block_tag = None
        self.stopped = False
        self.parts = []
        self.current = []
        self.in_customer = False
        self.customer = ""

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class", "").split()
        if tag == "article" and "story" in classes:
            self.in_story = True
        elif self.in_story and tag == "p" and "customer" in classes:
            self.in_customer = True
        elif self.in_story and self.after_heading and (
            "contact-headline" in classes or "originator" in classes
        ):
            self.stopped = True
            self.block_tag = None
            self.current = []
        elif self.in_story and self.after_heading and not self.stopped and tag in {"p", "li", "pre"}:
            self.block_tag = tag
            self.current = []

    def handle_data(self, data):
        if self.in_customer:
            self.customer += data
        if self.block_tag is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if not self.in_story:
            return
        if tag == "h1":
            self.after_heading = True
        elif tag == "p":
            self.in_customer = False
        if tag == self.block_tag:
            block = " ".join(" ".join(self.current).split())
            if block and not block.startswith("Schneller informiert:"):
                self.parts.append(block)
            self.block_tag = None
        if tag == "article":
            self.in_story = False


def listing_rows(page):
    parser = NewsroomParser()
    parser.feed(page)
    if parser.articles_seen == 0 or parser.articles_seen != len(parser.rows):
        raise ValueError("Frankfurt newsroom list contains no or unparsed articles")
    return parser.rows


def article_body(page):
    parser = ArticleParser()
    parser.feed(page)
    body = " ".join(parser.parts)
    if parser.customer.strip() != PUBLISHER or len(body) < 30:
        raise ValueError("Frankfurt article parser or publisher check failed")
    return body


def next_url(page):
    match = NEXT_PAGE.search(page)
    if not match:
        return None
    url = urljoin(ORIGIN, match[1])
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "www.presseportal.de"
        or not PAGE_PATH.fullmatch(parsed.path)
    ):
        raise ValueError("Unexpected Frankfurt newsroom pagination link")
    return url


def sync(path, year, *, pages=1, limit=5, delay=1.0):
    """Scan at most ``pages`` archive pages and revisit at most ``limit`` articles.

    A bounded run is a checkpoint, not a complete-year coverage claim.
    """
    db = connect(path)
    if "parser_version" not in {row[1] for row in db.execute("PRAGMA table_info(reports)")}:
        db.execute("ALTER TABLE reports ADD COLUMN parser_version INTEGER NOT NULL DEFAULT 1")
        db.commit()
    db.execute(
        """CREATE TABLE IF NOT EXISTS frankfurt_archive_cursor (
           year INTEGER PRIMARY KEY, next_url TEXT, pages_scanned INTEGER NOT NULL,
           complete INTEGER NOT NULL, updated REAL NOT NULL)"""
    )
    db.commit()
    started = time.time()
    stats = {
        "year": year,
        "requested_pages": pages,
        "archive_pages": 0,
        "head_refreshed": False,
        "discovered": 0,
        "new": 0,
        "revised": 0,
        "unchanged": 0,
        "failed": 0,
        "archive_exhausted": False,
        "year_covered": False,
    }
    db.execute("INSERT INTO runs(started) VALUES(?)", (started,))
    db.commit()
    try:
        with httpx.Client(
            timeout=25,
            follow_redirects=False,
            headers={"User-Agent": "CrimeMapsBerlin/0.1 (Frankfurt police newsroom index)"},
        ) as client:
            for attempt in range(3):
                try:
                    robots_response = client.get(ORIGIN + "/robots.txt")
                    robots_response.raise_for_status()
                    break
                except (httpx.TransportError, httpx.HTTPStatusError):
                    if attempt == 2:
                        raise
                    time.sleep(2**attempt)
            robots_response.raise_for_status()
            if (
                robots_response.status_code != 200
                or str(robots_response.url) != ORIGIN + "/robots.txt"
                or "user-agent:" not in robots_response.text.lower()
            ):
                raise ValueError("Missing or unexpected Frankfurt newsroom robots.txt")
            robots = RobotFileParser()
            robots.parse(robots_response.text.splitlines())
            delay = max(delay, float(robots.crawl_delay("CrimeMapsBerlin") or 0))
            last_request = time.monotonic()

            def get(url, headers=None):
                nonlocal last_request
                expected_path = urlparse(url).path
                for _ in range(4):
                    parsed = urlparse(url)
                    if parsed.scheme != "https" or parsed.netloc != "www.presseportal.de":
                        raise ValueError("Unexpected Frankfurt newsroom origin")
                    if not robots.can_fetch("CrimeMapsBerlin", url):
                        raise ValueError("robots.txt disallows " + url)
                    for attempt in range(3):
                        time.sleep(max(0, delay - (time.monotonic() - last_request)))
                        last_request = time.monotonic()
                        try:
                            response = client.get(url, headers=headers)
                        except httpx.TransportError:
                            if attempt == 2:
                                raise
                            time.sleep(2**attempt)
                            continue
                        if response.status_code in {429, 500, 502, 503, 504}:
                            if attempt == 2:
                                response.raise_for_status()
                            retry_after = response.headers.get("retry-after", "")
                            wait = int(retry_after) if retry_after.isdigit() else 2**attempt
                            time.sleep(min(30, max(delay, wait)))
                            continue
                        break
                    if response.status_code in (301, 302, 303, 307, 308):
                        target = urljoin(str(response.url), response.headers["location"])
                        if urlparse(target).path != expected_path:
                            raise ValueError("Frankfurt newsroom redirect changed record path")
                        url = target
                        continue
                    if response.status_code != 304:
                        response.raise_for_status()
                    return response
                raise ValueError("Too many Frankfurt newsroom redirects")

            seen_ids = set()

            def scan(url):
                page = get(url).text
                rows = listing_rows(page)
                selected = [r for r in rows if r["published"].startswith(str(year))]
                discover(db, selected, time.time())
                seen_ids.update(r["id"] for r in selected)
                stats["discovered"] = len(seen_ids)
                stats["archive_pages"] += 1
                return rows, next_url(page)

            state = db.execute(
                "SELECT next_url,pages_scanned,complete FROM frankfurt_archive_cursor WHERE year=?", (year,)
            ).fetchone()
            cursor = state["next_url"] if state and not state["complete"] else NEWSROOM
            scanned = state["pages_scanned"] if state and not state["complete"] else 0
            if cursor != NEWSROOM or (state and state["complete"]):
                scan(NEWSROOM)
                stats["head_refreshed"] = True
            url = cursor
            seen_pages = set()
            for _ in range(0 if state and state["complete"] else pages):
                if url in seen_pages:
                    raise ValueError("Frankfurt newsroom pagination loop")
                seen_pages.add(url)
                rows, url = scan(url)
                scanned += 1
                if url is None:
                    stats["archive_exhausted"] = True
                if all(r["published"][:4] < str(year) for r in rows):
                    stats["year_covered"] = True
                complete = stats["archive_exhausted"] or stats["year_covered"]
                db.execute(
                    """INSERT INTO frankfurt_archive_cursor(year,next_url,pages_scanned,complete,updated)
                       VALUES(?,?,?,?,?) ON CONFLICT(year) DO UPDATE SET
                       next_url=excluded.next_url,pages_scanned=excluded.pages_scanned,
                       complete=excluded.complete,updated=excluded.updated""",
                    (year, url, scanned, int(complete), time.time()),
                )
                db.commit()
                if complete:
                    break
            stats["archive_complete"] = bool(
                db.execute("SELECT complete FROM frankfurt_archive_cursor WHERE year=?", (year,)).fetchone()[
                    0
                ]
            )
            stats["cursor_pages_scanned"] = scanned
            pending = db.execute(
                """SELECT * FROM reports WHERE retry_after<=? AND
                   (body IS NULL OR parser_version<? OR checked IS NULL OR checked<? OR published>=?)
                   ORDER BY body IS NOT NULL, COALESCE(checked,0), published DESC LIMIT ?""",
                (
                    started,
                    PARSER_VERSION,
                    started - 7 * 86400,
                    datetime.fromtimestamp(started - 2 * 86400, UTC).isoformat()[:19],
                    limit,
                ),
            ).fetchall()
            for row in pending:
                headers = {}
                if row["parser_version"] >= PARSER_VERSION and row["etag"]:
                    headers["If-None-Match"] = row["etag"]
                if row["parser_version"] >= PARSER_VERSION and row["modified"]:
                    headers["If-Modified-Since"] = row["modified"]
                try:
                    response = get(row["url"], headers)
                    if response.status_code == 304:
                        if row["body"] is None:
                            raise ValueError("304 without cached body")
                        db.execute(
                            """UPDATE reports SET checked=?,error=NULL,failures=0,retry_after=0,
                               parser_version=? WHERE id=?""",
                            (time.time(), PARSER_VERSION, row["id"]),
                        )
                        db.commit()
                        result = "unchanged"
                    else:
                        result = accept(
                            db, row["id"], article_body(response.text), response.headers, time.time()
                        )
                        db.execute(
                            "UPDATE reports SET parser_version=? WHERE id=?",
                            (PARSER_VERSION, row["id"]),
                        )
                        db.commit()
                    stats[result] += 1
                except (httpx.HTTPError, ValueError) as exc:
                    fail(
                        db,
                        row["id"],
                        f"{type(exc).__name__}: {exc}",
                        time.time(),
                        exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None,
                    )
                    stats["failed"] += 1
            stats["stored"] = db.execute("SELECT count(*) FROM reports WHERE body IS NOT NULL").fetchone()[0]
            stats["pending"] = db.execute("SELECT count(*) FROM reports WHERE body IS NULL").fetchone()[0]
            stats["parser_pending"] = db.execute(
                "SELECT count(*) FROM reports WHERE body IS NOT NULL AND parser_version<?",
                (PARSER_VERSION,),
            ).fetchone()[0]
            stats["errors"] = db.execute("SELECT count(*) FROM reports WHERE error IS NOT NULL").fetchone()[0]
    except Exception as exc:
        stats["fatal_error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        db.execute(
            "UPDATE runs SET finished=?,summary=? WHERE started=?", (time.time(), json.dumps(stats), started)
        )
        db.commit()
        db.close()
    return stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=".runtime/safety/cities/frankfurt/police.sqlite")
    parser.add_argument("--year", type=int, default=datetime.now(UTC).year)
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    if (
        args.year < 2015
        or args.year > datetime.now(UTC).year
        or args.pages < 1
        or args.limit < 1
        or args.delay < 1
    ):
        parser.error("Use available year, positive page/record limits and delay >= 1 second")
    import fcntl

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    with open(args.db + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = sync(args.db, args.year, pages=args.pages, limit=args.limit, delay=args.delay)
    print(json.dumps(result, indent=2))
    if (
        result["failed"]
        or result["pending"]
        or result["parser_pending"]
        or result["errors"]
        or not result["archive_complete"]
    ):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
