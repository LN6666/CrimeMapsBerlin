"""Incremental official archive collector. No LLM; SQLite is the durable checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from .feed import article_text

BASE = "https://www.berlin.de"
SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
 id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL, published TEXT NOT NULL,
 district TEXT NOT NULL, body TEXT, sha256 TEXT, etag TEXT, modified TEXT,
 checked REAL, retry_after REAL DEFAULT 0, failures INTEGER DEFAULT 0, error TEXT,
 first_seen REAL NOT NULL, revision INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS revisions (
 id TEXT, revision INTEGER, sha256 TEXT, observed REAL, PRIMARY KEY(id,revision));
CREATE TABLE IF NOT EXISTS runs (started REAL PRIMARY KEY, finished REAL, summary TEXT);
"""


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    db.execute("PRAGMA journal_mode=WAL")
    if "http_status" not in {r[1] for r in db.execute("PRAGMA table_info(reports)")}:
        db.execute("ALTER TABLE reports ADD COLUMN http_status INTEGER")
        db.commit()
    return db


def clean(value):
    return " ".join(html.unescape(re.sub("<[^>]+>", " ", value)).split())


def listings(page):
    records = {}
    for item in re.findall(r"<li>.*?</li>", page, re.S):
        link = re.search(r'<a\s+href="([^"]*pressemitteilung\.(\d+)\.php)"[^>]*>(.*?)</a>', item, re.S)
        date = re.search(r"(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})", item)
        if not link or not date:
            continue
        url = urljoin(BASE, html.unescape(link[1]))
        if urlparse(url).hostname != "www.berlin.de":
            continue
        district = re.search(r"Ereignisort:\s*</strong>(.*?)</span>", item, re.S)
        records[link[2]] = dict(
            id=link[2],
            url=url,
            title=clean(link[3]),
            published=datetime.strptime(date[1] + " " + date[2], "%d.%m.%Y %H:%M").isoformat(),
            district=clean(district[1]) if district else "",
        )
    return list(records.values())


def pages(page):
    return max([1] + [int(n) for n in re.findall(r"page_at_1_0=(\d+)", page)])


def discover(db, records, now):
    for r in records:
        db.execute(
            """INSERT INTO reports(id,url,title,published,district,first_seen)
            VALUES(:id,:url,:title,:published,:district,:now)
            ON CONFLICT(id) DO UPDATE SET url=excluded.url,title=excluded.title,
            published=excluded.published,district=excluded.district""",
            {**r, "now": now},
        )
    db.commit()


def accept(db, ident, body, headers, now):
    body = " ".join(body.split())
    if len(body) < 30:
        raise ValueError("Article body extraction failed; keeping previous version")
    digest = hashlib.sha256(body.encode()).hexdigest()
    old = db.execute("SELECT sha256, revision FROM reports WHERE id=?", (ident,)).fetchone()
    changed = old["sha256"] != digest
    revision = old["revision"] + int(changed)
    db.execute(
        """UPDATE reports SET body=?,sha256=?,etag=?,modified=?,checked=?,
        error=NULL,http_status=200,failures=0,retry_after=0,revision=? WHERE id=?""",
        (body, digest, headers.get("etag"), headers.get("last-modified"), now, revision, ident),
    )
    if changed:
        db.execute("INSERT INTO revisions VALUES(?,?,?,?)", (ident, revision, digest, now))
    db.commit()
    return "new" if old["sha256"] is None else "revised" if changed else "unchanged"


def fail(db, ident, error, now, status=None):
    n = db.execute("SELECT failures FROM reports WHERE id=?", (ident,)).fetchone()[0] + 1
    delay = min(86400, 300 * 2 ** min(n - 1, 8))
    db.execute(
        "UPDATE reports SET error=?,failures=?,retry_after=?,http_status=? WHERE id=?",
        (error[:200], n, now + delay, status, ident),
    )
    db.commit()


def sync(path, year, full=False, limit=1500, delay=1.0):
    db = connect(path)
    started = time.time()
    stats = dict(
        new=0,
        revised=0,
        unchanged=0,
        failed=0,
        discovered=0,
        archive_pages=0,
        full_archive_scan=full,
        year=year,
    )
    db.execute("INSERT INTO runs(started) VALUES(?)", (started,))
    db.commit()
    with httpx.Client(
        timeout=25,
        follow_redirects=False,
        headers={"User-Agent": "CrimeMapsBerlin/0.1 (public police archive index)"},
    ) as client:
        # Stop rather than interpreting a failed robots fetch as permission.
        r = client.get(BASE + "/robots.txt")
        r.raise_for_status()
        robots = RobotFileParser()
        robots.parse(r.text.splitlines())
        delay = max(delay, float(robots.crawl_delay("CrimeMapsBerlin") or 0))
        last_request = time.monotonic()

        def get(url, headers=None):
            nonlocal last_request
            if not robots.can_fetch("CrimeMapsBerlin", url):
                raise ValueError("robots.txt disallows " + url)
            time.sleep(max(0, delay - (time.monotonic() - last_request)))
            last_request = time.monotonic()
            result = client.get(url, headers=headers)
            # Follow only same-origin redirects, bounded, never credentials to another host.
            for _ in range(3):
                if result.status_code not in (301, 302, 303, 307, 308):
                    break
                target = urljoin(str(result.url), result.headers["location"])
                if urlparse(target).netloc != "www.berlin.de" or urlparse(target).scheme != "https":
                    raise ValueError("Unexpected redirect")
                if not robots.can_fetch("CrimeMapsBerlin", target):
                    raise ValueError("Disallowed redirect")
                time.sleep(delay)
                last_request = time.monotonic()
                result = client.get(target, headers=headers)
            result.raise_for_status() if result.status_code != 304 else None
            return result

        archive = f"{BASE}/polizei/polizeimeldungen/archiv/{year}/"
        first = get(archive).text
        total = pages(first)
        wanted = total if full else min(total, 2)
        for n in range(1, wanted + 1):
            page = first if n == 1 else get(archive + f"?page_at_1_0={n}").text
            rows = listings(page)
            if not rows:
                raise ValueError(f"No archive records on page {n}; parser/source changed")
            discover(db, rows, time.time())
            stats["discovered"] += len(rows)
            stats["archive_pages"] += 1
        # A rotating seven-day revisit detects corrections to older discovered reports too.
        pending = db.execute(
            """SELECT * FROM reports WHERE retry_after<=? AND
          (body IS NULL OR checked IS NULL OR checked<? OR published>=?)
          ORDER BY body IS NOT NULL, COALESCE(checked,0), published DESC LIMIT ?""",
            (
                started,
                started - 7 * 86400,
                datetime.fromtimestamp(started - 2 * 86400, timezone.utc).isoformat()[:19],
                limit,
            ),
        ).fetchall()
        for i, row in enumerate(pending):
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
                    db.execute(
                        "UPDATE reports SET checked=?,error=NULL,failures=0,retry_after=0 WHERE id=?",
                        (time.time(), row["id"]),
                    )
                    db.commit()
                    result = "unchanged"
                else:
                    result = accept(db, row["id"], article_text(response.text), response.headers, time.time())
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
            if (i + 1) % 25 == 0:
                print(json.dumps({**stats, "processed": i + 1, "queued": len(pending)}), flush=True)
        stats["stored"] = db.execute("SELECT count(*) FROM reports WHERE body IS NOT NULL").fetchone()[0]
        stats["pending"] = db.execute("SELECT count(*) FROM reports WHERE body IS NULL").fetchone()[0]
        stats["errors"] = db.execute("SELECT count(*) FROM reports WHERE error IS NOT NULL").fetchone()[0]
    db.execute(
        "UPDATE runs SET finished=?,summary=? WHERE started=?", (time.time(), json.dumps(stats), started)
    )
    db.commit()
    db.close()
    return stats


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=".runtime/safety/police.sqlite")
    p.add_argument("--year", type=int, default=datetime.now().year)
    p.add_argument("--full", action="store_true")
    p.add_argument("--limit", type=int, default=1500)
    p.add_argument("--delay", type=float, default=1.0)
    args = p.parse_args()
    if not 2015 <= args.year <= datetime.now().year or args.limit < 1 or args.delay < 1:
        p.error("Use available year, positive limit and delay >= 1 second")
    # Advisory process lock prevents scheduled/manual writers overlapping.
    import fcntl

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    with open(args.db + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = sync(args.db, args.year, args.full, args.limit, args.delay)
    print(json.dumps(result, indent=2))
    if result["failed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
