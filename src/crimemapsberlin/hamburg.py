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
    plural_narrative_start = (
        r"Nachdem|Gestern|Heute|Den\s+Strafverfolgungsbehörden|Die\s+Polizei|"
        r"Einsatzkräfte|Mehrere|Zwei|Drei|Unbekannte|Aufgrund|Vergangenen|Im\s+Zuge|"
        r"Am\s+(?:Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag|"
        r"vergangenen|heutigen|frühen)|In\s+der\s+Nacht"
    )
    plural_headings = list(
        re.finditer(r"\b(?:Tatorte|Unfallorte|Feststellorte|Orte):\s*", body)
    )
    headings = re.findall(r"\b(?:Tatort|Unfallort|Feststellort|Ort):\s*Hamburg-", body)
    if plural_headings:
        if len(plural_headings) != 1 or headings:
            return ""
        tail = body[plural_headings[0].end():]
        boundary = re.search(
            rf"\s+(?=(?:[a-z]\)\s+)?(?:{plural_narrative_start})\b)", tail
        )
        header = tail[:boundary.start()] if boundary else tail[:400]
        district_pattern = re.compile(
            r"\bHamburg-([^,;\n]{2,55}?)(?=\s*[,;]|\s+(?:und|sowie)\s+Hamburg-|"
            r"\s+[a-z]\)|$)"
        )
        districts = [value.strip() for value in district_pattern.findall(header)]
        abbreviated_districts = re.search(
            r"(?:,\s*|\bund\s+|\bsowie\s+)-[A-ZÄÖÜ]", header
        )
        if (
            not districts
            or abbreviated_districts
            or re.search(r"\bmehrere\s+stadtteile\b|\bbezirk\s+hamburg-", header, re.I)
        ):
            return ""
        scene_markers = re.findall(r"(?:^|\s)[a-z]\)\s*", header)
        if len(scene_markers) > 1:
            scenes = [
                part for part in re.split(r"(?:^|\s)[a-z]\)\s*", header)
                if part.strip()
            ]
            if any(not district_pattern.findall(scene) for scene in scenes):
                return ""
        return districts[0] if len({value.casefold() for value in districts}) == 1 else ""
    if len(headings) != 1:
        # Two singular headings are still two scenes. Do not let the lazy
        # district capture consume the second heading as part of one name.
        return ""
    narrative_start = (
        r"Die|Der|Den|Dem|Das|Ein|Eine|Einen|Am|An|Im|In|Heute|Gestern|Seit|Nach|Vor|"
        r"Einsatzkräfte|Polizei|Mehrere|Zwei|Drei|Unbekannte|Aufgrund"
    )
    matches = re.findall(
        rf"\b(?:Tatort|Unfallort|Feststellort|Ort):\s*Hamburg-([^,;\n]{{2,55}}?)"
        rf"(?=\s*[,;]|\s+(?:{narrative_start})\b)",
        body,
    )
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
    if "parser_version" not in {row[1] for row in db.execute("PRAGMA table_info(reports)")}:
        db.execute("ALTER TABLE reports ADD COLUMN parser_version INTEGER NOT NULL DEFAULT 1")
    db.execute(
        """CREATE TABLE IF NOT EXISTS archive_coverage (
           year INTEGER PRIMARY KEY, complete INTEGER NOT NULL, checked REAL NOT NULL,
           pages INTEGER NOT NULL, discovered INTEGER NOT NULL, boundary TEXT NOT NULL,
           head_stable INTEGER NOT NULL)"""
    )
    db.commit()
    restored_districts = restore_cached_districts(db)
    started = time.time()
    stats = dict(year=year, full_archive_scan=full, archive_pages=0, discovered=0,
                 new=0, revised=0, unchanged=0, failed=0,
                 restored_districts=restored_districts, year_boundary_reached=False,
                 head_stable=False, archive_complete=False)
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
        first_page_signature = None
        boundary = ""
        for _ in range(100 if full else 1):
            page = get(url).text
            listed = listing_rows(page)
            if not listed:
                raise ValueError("No Hamburg newsroom records; source/parser changed")
            stats["archive_pages"] += 1
            if first_page_signature is None:
                first_page_signature = [(row["id"], row["published"]) for row in listed]
            rows = [r for r in listed if r["published"].startswith(str(year))]
            if rows:
                discover(db, rows, time.time())
            stats["discovered"] += len(rows)
            listed_years = [int(row["published"][:4]) for row in listed]
            if any(listed_year < year for listed_year in listed_years):
                boundary = "older_year"
                stats["year_boundary_reached"] = True
                break
            next_page = NEXT_PAGE.search(page)
            if not next_page:
                boundary = "source_end"
                stats["year_boundary_reached"] = True
                break
            next_url = urljoin(ORIGIN, next_page[1])
            if next_url == url:
                raise ValueError("Newsroom pagination loop")
            url = next_url
        if full and stats["year_boundary_reached"]:
            repeated = listing_rows(get(NEWSROOM).text)
            stats["head_stable"] = first_page_signature == [
                (row["id"], row["published"]) for row in repeated
            ]
        pending = db.execute(
            """SELECT * FROM reports WHERE retry_after<=? AND
               (body IS NULL OR parser_version<? OR checked IS NULL OR checked<? OR published>=?)
               ORDER BY body IS NOT NULL, COALESCE(checked,0), published DESC LIMIT ?""",
            (started, PARSER_VERSION, started - 7 * 86400,
             datetime.fromtimestamp(started - 2 * 86400, timezone.utc).isoformat()[:19], limit),
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
                    body = article_body(response.text)
                    result = accept(db, row["id"], body, response.headers, time.time())
                    db.execute(
                        "UPDATE reports SET district=?,parser_version=? WHERE id=?",
                        (article_district(body), PARSER_VERSION, row["id"]),
                    )
                    db.commit()
                stats[result] += 1
            except (httpx.HTTPError, ValueError) as exc:
                fail(db, row["id"], f"{type(exc).__name__}: {exc}", time.time(),
                     exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None)
                stats["failed"] += 1
        stats["stored"] = db.execute("SELECT count(*) FROM reports WHERE body IS NOT NULL").fetchone()[0]
        stats["pending"] = db.execute("SELECT count(*) FROM reports WHERE body IS NULL").fetchone()[0]
        stats["parser_pending"] = db.execute(
            "SELECT count(*) FROM reports WHERE body IS NOT NULL AND parser_version<?",
            (PARSER_VERSION,),
        ).fetchone()[0]
        stats["errors"] = db.execute("SELECT count(*) FROM reports WHERE error IS NOT NULL").fetchone()[0]
        if full:
            stats["archive_complete"] = bool(
                stats["year_boundary_reached"]
                and stats["head_stable"]
                and stats["discovered"]
                and not stats["pending"]
                and not stats["parser_pending"]
                and not stats["errors"]
            )
        else:
            coverage = db.execute(
                "SELECT complete,checked FROM archive_coverage WHERE year=?", (year,)
            ).fetchone()
            unseen_head = coverage and db.execute(
                "SELECT 1 FROM reports WHERE published LIKE ? AND first_seen>? LIMIT 1",
                (f"{year}-%", coverage["checked"]),
            ).fetchone()
            stats["archive_complete"] = bool(
                coverage
                and coverage["complete"]
                and unseen_head is None
                and not stats["pending"]
                and not stats["parser_pending"]
                and not stats["errors"]
            )
        if full:
            db.execute(
                """INSERT INTO archive_coverage
                   (year,complete,checked,pages,discovered,boundary,head_stable)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(year) DO UPDATE SET
                   complete=excluded.complete,checked=excluded.checked,pages=excluded.pages,
                   discovered=excluded.discovered,boundary=excluded.boundary,
                   head_stable=excluded.head_stable""",
                (
                    year, int(stats["archive_complete"]), time.time(), stats["archive_pages"],
                    stats["discovered"], boundary or "page_limit", int(stats["head_stable"]),
                ),
            )
            db.commit()
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
    if result["failed"] or result["pending"] or result["parser_pending"] or result["errors"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
