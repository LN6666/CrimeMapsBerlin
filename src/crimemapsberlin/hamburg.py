"""Hamburg police newsroom adapter; local checkpoint only, no public full-text mirror."""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from .collector import accept, connect, discover, fail

ORIGIN = "https://www.presseportal.de"
NEWSROOM = ORIGIN + "/blaulicht/nr/6337"
ARTICLE_PATH = re.compile(r"/blaulicht/pm/6337/(\d+)$")
NEXT_PAGE = re.compile(r'<link\s+rel="next"\s+href="(/blaulicht/nr/6337/\d+)"')


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
                self.current = dict(id=attrs["data-label"], url="", title="", published="", district="")
        if self.current is None:
            return
        if tag == "div" and "date" in classes:
            self.field = "published"
        elif tag == "h3" and "news-headline-clamp" in classes:
            self.field = "title"
        elif tag == "a" and self.field == "title":
            url = urljoin(ORIGIN, attrs.get("href", ""))
            match = ARTICLE_PATH.fullmatch(urlparse(url).path)
            if urlparse(url).netloc == "www.presseportal.de" and match and match[1] == self.current["id"]:
                self.current["url"] = url

    def handle_data(self, data):
        if self.current is not None and self.field:
            self.current[self.field] += data

    def handle_endtag(self, tag):
        if self.current is None:
            return
        if tag in {"div", "h3"}:
            self.field = None
        if tag == "article":
            row = self.current
            if row["url"] and row["title"] and row["published"]:
                published = " ".join(row["published"].replace("–", " ").split())
                row["published"] = datetime.strptime(published, "%d.%m.%Y %H:%M").isoformat()
                row["title"] = " ".join(row["title"].split())
                self.rows.append(row)
            self.current = None
            self.field = None


class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_story = False
        self.after_heading = False
        self.in_paragraph = False
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
        elif self.in_story and self.after_heading and tag == "p":
            if "contact-headline" in classes or "originator" in classes:
                self.stopped = True
            elif not self.stopped:
                self.in_paragraph = True
                self.current = []

    def handle_data(self, data):
        if self.in_customer:
            self.customer += data
        if self.in_paragraph:
            self.current.append(data)

    def handle_endtag(self, tag):
        if not self.in_story:
            return
        if tag == "h1":
            self.after_heading = True
        elif tag == "p":
            self.in_customer = False
            if self.in_paragraph:
                paragraph = " ".join(" ".join(self.current).split())
                if paragraph and not paragraph.startswith("Schneller informiert:"):
                    self.parts.append(paragraph)
                self.in_paragraph = False
        elif tag == "article":
            self.in_story = False


def listing_rows(page):
    parser = NewsroomParser()
    parser.feed(page)
    if parser.articles_seen != len(parser.rows):
        raise ValueError("Hamburg newsroom list contains unparsed articles")
    return parser.rows


def article_body(page):
    parser = ArticleParser()
    parser.feed(page)
    body = " ".join(parser.parts)
    if parser.customer.strip() != "Polizei Hamburg" or len(body) < 30:
        raise ValueError("Hamburg article parser or publisher check failed")
    return body


def article_district(body):
    matches = re.findall(r"\b(?:Tatort|Unfallort|Ort):\s*Hamburg-([^,;\n]{2,55})\s*[,;]", body)
    # Multiple scene headings need an incident-by-incident location review.
    return matches[0].strip() if len(matches) == 1 else ""


def restore_cached_districts(db):
    """Repair district headings erased by earlier newsroom-list rescans."""
    repaired = 0
    for row in db.execute("SELECT id,body FROM reports WHERE district='' AND body IS NOT NULL"):
        district = article_district(row["body"])
        if district:
            db.execute("UPDATE reports SET district=? WHERE id=?", (district, row["id"]))
            repaired += 1
    db.commit()
    return repaired


def sync(path, year, *, full=False, limit=30, delay=1.0):
    db = connect(path)
    restored_districts = restore_cached_districts(db)
    started = time.time()
    stats = dict(year=year, full_archive_scan=full, archive_pages=0, discovered=0,
                 new=0, revised=0, unchanged=0, failed=0,
                 restored_districts=restored_districts)
    db.execute("INSERT INTO runs(started) VALUES(?)", (started,))
    db.commit()
    with httpx.Client(
        timeout=25,
        follow_redirects=False,
        headers={"User-Agent": "CrimeMapsBerlin/0.1 (Hamburg police newsroom index)"},
    ) as client:
        robots_response = client.get(ORIGIN + "/robots.txt")
        robots_response.raise_for_status()
        robots = RobotFileParser()
        robots.parse(robots_response.text.splitlines())
        delay = max(delay, float(robots.crawl_delay("CrimeMapsBerlin") or 0))
        last_request = time.monotonic()

        def get(url, headers=None):
            nonlocal last_request
            for _ in range(4):
                parsed = urlparse(url)
                if parsed.scheme != "https" or parsed.netloc != "www.presseportal.de":
                    raise ValueError("Unexpected newsroom origin")
                if not robots.can_fetch("CrimeMapsBerlin", url):
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
            raise ValueError("Too many newsroom redirects")

        url = NEWSROOM
        for _ in range(100 if full else 1):
            page = get(url).text
            rows = listing_rows(page)
            if not rows:
                raise ValueError("No Hamburg newsroom records; source/parser changed")
            rows = [r for r in rows if r["published"].startswith(str(year))]
            if not rows:
                break
            discover(db, rows, time.time())
            stats["archive_pages"] += 1
            stats["discovered"] += len(rows)
            next_page = NEXT_PAGE.search(page)
            if not next_page:
                break
            next_url = urljoin(ORIGIN, next_page[1])
            if next_url == url:
                raise ValueError("Newsroom pagination loop")
            url = next_url
        pending = db.execute(
            """SELECT * FROM reports WHERE retry_after<=? AND
               (body IS NULL OR checked IS NULL OR checked<? OR published>=?)
               ORDER BY body IS NOT NULL, COALESCE(checked,0), published DESC LIMIT ?""",
            (started, started - 7 * 86400,
             datetime.fromtimestamp(started - 2 * 86400, timezone.utc).isoformat()[:19], limit),
        ).fetchall()
        for row in pending:
            headers = {}
            if row["etag"]:
                headers["If-None-Match"] = row["etag"]
            if row["modified"]:
                headers["If-Modified-Since"] = row["modified"]
            try:
                response = get(row["url"], headers)
                if response.status_code == 304:
                    if row["body"] is None:
                        raise ValueError("304 without cached body")
                    db.execute("UPDATE reports SET checked=?,error=NULL,failures=0,retry_after=0 WHERE id=?",
                               (time.time(), row["id"]))
                    db.commit()
                    result = "unchanged"
                else:
                    body = article_body(response.text)
                    result = accept(db, row["id"], body, response.headers, time.time())
                    db.execute(
                        "UPDATE reports SET district=? WHERE id=?", (article_district(body), row["id"])
                    )
                    db.commit()
                stats[result] += 1
            except (httpx.HTTPError, ValueError) as exc:
                fail(db, row["id"], f"{type(exc).__name__}: {exc}", time.time(),
                     exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None)
                stats["failed"] += 1
        stats["stored"] = db.execute("SELECT count(*) FROM reports WHERE body IS NOT NULL").fetchone()[0]
        stats["pending"] = db.execute("SELECT count(*) FROM reports WHERE body IS NULL").fetchone()[0]
        stats["errors"] = db.execute("SELECT count(*) FROM reports WHERE error IS NOT NULL").fetchone()[0]
    db.execute(
        "UPDATE runs SET finished=?,summary=? WHERE started=?",
        (time.time(), json.dumps(stats), started),
    )
    db.commit()
    db.close()
    return stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=".runtime/safety/cities/hamburg/police.sqlite")
    parser.add_argument("--year", type=int, default=datetime.now().year)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    if args.year < 2015 or args.year > datetime.now().year or args.limit < 1 or args.delay < 1:
        parser.error("Use available year, positive limit and delay >= 1 second")
    import fcntl

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    with open(args.db + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = sync(args.db, args.year, full=args.full, limit=args.limit, delay=args.delay)
    print(json.dumps(result, indent=2))
    if result["failed"] or result["pending"] or result["errors"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
