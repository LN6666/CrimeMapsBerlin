"""Checkpoint the rolling Munich dataset published by POLIZEIKARTE.

POLIZEIKARTE is an independent project which structures public police reports
and links every row to its source report.  The owner selected its Munich map as
the source for this city.  This adapter therefore preserves the site's supplied
classification and location fields without trying to reinterpret the narrative.

The unfiltered 365-day page is capped at 500 rows.  Each of the site's ten
exclusive categories is below that cap, so a complete snapshot is built from
the category pages and their list pagination.  A snapshot is accepted only when
the declared category totals, map payload IDs, paginated list IDs, and overall
total all agree.  Raw HTML and report summaries remain in ignored local runtime
storage; this module never writes public map files.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sqlite3
import time
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

ORIGIN = "https://polizeikarte.de"
CITY_PATH = "/muenchen"
ROBOTS_URL = ORIGIN + "/robots.txt"
USER_AGENT = "CrimeMapsBerlin/0.1 (POLIZEIKARTE Munich source checkpoint)"
WINDOW_DAYS = 365
CATEGORIES = (
    "gewalt",
    "raub",
    "einbruch",
    "diebstahl",
    "sexualdelikte",
    "betrug",
    "drogen",
    "verkehr",
    "brand",
    "sonstige",
)
DETAIL_PATH = re.compile(r"/muenchen/meldung/(\d+)-[a-z0-9-]+")
GERMAN_MONTHS = {
    "Januar": 1,
    "Februar": 2,
    "März": 3,
    "April": 4,
    "Mai": 5,
    "Juni": 6,
    "Juli": 7,
    "August": 8,
    "September": 9,
    "Oktober": 10,
    "November": 11,
    "Dezember": 12,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS polizeikarte_entries (
    entry_id INTEGER PRIMARY KEY,
    detail_url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    category TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    place_label TEXT NOT NULL,
    district TEXT,
    public_precision TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    official_url TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    revision INTEGER NOT NULL,
    first_seen REAL NOT NULL,
    checked REAL NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    scan_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS polizeikarte_revisions (
    entry_id INTEGER NOT NULL,
    revision INTEGER NOT NULL,
    source_hash TEXT NOT NULL,
    observed REAL NOT NULL,
    PRIMARY KEY(entry_id, revision)
);
CREATE TABLE IF NOT EXISTS polizeikarte_scans (
    scan_id TEXT PRIMARY KEY,
    window_days INTEGER NOT NULL,
    started REAL NOT NULL,
    finished REAL,
    expected_total INTEGER,
    stored_total INTEGER,
    complete INTEGER NOT NULL DEFAULT 0,
    signature TEXT,
    summary_json TEXT
);
CREATE TABLE IF NOT EXISTS polizeikarte_pages (
    scan_id TEXT NOT NULL,
    category TEXT NOT NULL,
    page INTEGER NOT NULL,
    url TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    list_rows INTEGER NOT NULL,
    map_rows INTEGER NOT NULL,
    PRIMARY KEY(scan_id, category, page)
);
"""


def _clean(value: str) -> str:
    return " ".join(html.unescape(value).split())


def _detail_url(value: str) -> tuple[int, str]:
    parsed = urlparse(urljoin(ORIGIN, html.unescape(value)))
    match = DETAIL_PATH.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "polizeikarte.de"
        or parsed.query
        or parsed.fragment
        or not match
    ):
        raise ValueError("Unexpected POLIZEIKARTE Munich detail URL")
    return int(match[1]), parsed.geturl()


def _official_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("POLIZEIKARTE row has an invalid original-source URL")
    if parsed.fragment:
        raise ValueError("POLIZEIKARTE original-source URL unexpectedly contains a fragment")
    return parsed.geturl()


def _occurred_at(value: str) -> str:
    value = value.removeprefix("$D")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("POLIZEIKARTE occurrence timestamp lacks a timezone")
    return parsed.isoformat().replace("+00:00", "Z")


def _display_day(value: str) -> str:
    match = re.fullmatch(
        r"(?:Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag), "
        r"(\d{1,2})\. ([A-Za-zÄÖÜäöü]+) (\d{4})",
        value,
    )
    if not match or match[2] not in GERMAN_MONTHS:
        raise ValueError("POLIZEIKARTE list day format changed")
    return f"{int(match[3]):04d}-{GERMAN_MONTHS[match[2]]:02d}-{int(match[1]):02d}"


class _ListingParser(HTMLParser):
    """Read the static list rows without depending on Next.js internals."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.day = ""
        self.day_depth: int | None = None
        self.day_parts: list[str] = []
        self.row_depth: int | None = None
        self.field_depth: int | None = None
        self.field: str | None = None
        self.field_parts: list[str] = []
        self.in_title_link = False
        self.current: dict[str, object] | None = None
        self.rows: list[dict[str, object]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        classes = (attrs_dict.get("class") or "").split()
        if tag == "div":
            self.depth += 1
            if self.current is None and "list-day" in classes:
                self.day_depth = self.depth
                self.day_parts = []
            elif self.current is None and {"card", "event-row"}.issubset(classes):
                if not self.day:
                    raise ValueError("POLIZEIKARTE event row appeared before its day heading")
                self.row_depth = self.depth
                self.current = {
                    "display_day": self.day,
                    "display_time": "",
                    "detail_url": "",
                    "title": "",
                    "place_label": "",
                    "summary": "",
                }
            elif self.current is not None:
                for class_name, field in (
                    ("event-time", "display_time"),
                    ("place", "place_label"),
                    ("summary", "summary"),
                ):
                    if class_name in classes:
                        self.field = field
                        self.field_depth = self.depth
                        self.field_parts = []
                        break
        if tag == "a" and self.current is not None:
            href = attrs_dict.get("href") or ""
            if DETAIL_PATH.fullmatch(urlparse(urljoin(ORIGIN, href)).path):
                entry_id, url = _detail_url(href)
                self.current["entry_id"] = entry_id
                self.current["detail_url"] = url
                self.in_title_link = True

    def handle_data(self, data: str) -> None:
        if self.day_depth is not None:
            self.day_parts.append(data)
        if self.in_title_link and self.current is not None:
            self.current["title"] = str(self.current["title"]) + data
        elif self.field is not None:
            self.field_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self.in_title_link = False
        if tag != "div":
            return
        if self.day_depth == self.depth:
            self.day = _clean("".join(self.day_parts))
            _display_day(self.day)
            self.day_depth = None
            self.day_parts = []
        if self.field_depth == self.depth and self.current is not None and self.field:
            self.current[self.field] = _clean("".join(self.field_parts))
            self.field = None
            self.field_depth = None
            self.field_parts = []
        if self.row_depth == self.depth:
            row = self.current
            if row is None:
                raise ValueError("POLIZEIKARTE list parser lost its current row")
            row["title"] = _clean(str(row["title"]))
            if (
                not isinstance(row.get("entry_id"), int)
                or not row["detail_url"]
                or not row["title"]
                or not re.fullmatch(r"\d{2}:\d{2}", str(row["display_time"]))
            ):
                raise ValueError("POLIZEIKARTE list contains an incomplete event row")
            row["display_date"] = _display_day(str(row.pop("display_day")))
            self.rows.append(row)
            self.current = None
            self.row_depth = None
        self.depth -= 1


class _FlightScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_script = False
        self.parts: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and not dict(attrs).get("src"):
            self.in_script = True
            self.parts = []

    def handle_data(self, data: str) -> None:
        if self.in_script:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.in_script:
            self.scripts.append("".join(self.parts))
            self.in_script = False
            self.parts = []


def _map_events(page: str) -> list[dict[str, object]]:
    parser = _FlightScriptParser()
    parser.feed(page)
    arrays: list[list[object]] = []
    decoder = json.JSONDecoder()
    prefix = "self.__next_f.push("
    chunks: list[str] = []
    for script in parser.scripts:
        script = script.strip()
        if not script.startswith(prefix) or not script.endswith(")"):
            continue
        try:
            payload = json.loads(script[len(prefix):-1])
        except json.JSONDecodeError:
            continue
        if len(payload) < 2 or not isinstance(payload[1], str):
            continue
        if payload[0] == 1:
            chunks.append(payload[1])
    flight = "".join(chunks)
    cursor = 0
    while True:
        start = flight.find('"events":', cursor)
        if start < 0:
            break
        try:
            candidate, end = decoder.raw_decode(flight, start + len('"events":'))
        except json.JSONDecodeError:
            cursor = start + len('"events":')
            continue
        if isinstance(candidate, list):
            arrays.append(candidate)
        cursor = end
    candidates = [
        array
        for array in arrays
        if array and all(isinstance(item, dict) and {"id", "category", "source_url"} <= item.keys()
                         for item in array)
    ]
    if len(candidates) != 1:
        raise ValueError("POLIZEIKARTE map event payload is missing or ambiguous")
    return [dict(item) for item in candidates[0]]


def _declared_counts(page: str) -> tuple[int, int]:
    category = re.search(
        r'<p class="stats-line"><strong>([\d.]+).*?veröffentlicht(?:e Vorfälle|er Vorfall)</strong>', page,
        re.DOTALL,
    )
    total = re.search(r'>Alle\s*<span class="chip-count">([\d.]+)</span>', page)
    if not category or not total:
        raise ValueError("POLIZEIKARTE declared totals are missing")
    return int(category[1].replace(".", "")), int(total[1].replace(".", ""))


def _page_count(page: str) -> int:
    visible = re.sub(r"<script\b.*?</script>", " ", page, flags=re.DOTALL | re.IGNORECASE)
    visible = _clean(re.sub(r"<[^>]+>", " ", visible))
    matches = re.findall(r"Seite\s+(\d+)\s+von\s+(\d+)", visible)
    if not matches:
        return 1
    totals = {int(total) for _, total in matches}
    if len(totals) != 1 or min(int(current) for current, _ in matches) < 1:
        raise ValueError("POLIZEIKARTE list pagination is inconsistent")
    return totals.pop()


def parse_listing_page(page: str, category: str) -> dict[str, object]:
    """Parse one category/list page and the category-wide map payload."""
    if category not in CATEGORIES:
        raise ValueError("Unknown POLIZEIKARTE category")
    category_count, overall_count = _declared_counts(page)
    parser = _ListingParser()
    parser.feed(page)
    if parser.current is not None or not parser.rows:
        raise ValueError("POLIZEIKARTE list contains no complete rows")
    events = _map_events(page)
    normalized: dict[int, dict[str, object]] = {}
    for event in events:
        if event.get("category") != category:
            raise ValueError("POLIZEIKARTE category payload mixed categories")
        entry_id = event.get("id")
        if not isinstance(entry_id, int) or entry_id in normalized:
            raise ValueError("POLIZEIKARTE category payload has duplicate or invalid IDs")
        latitude, longitude = event.get("lat"), event.get("lng")
        if (latitude is None) != (longitude is None):
            raise ValueError("POLIZEIKARTE row contains a partial coordinate")
        if latitude is not None and (
            not isinstance(latitude, (float, int))
            or not isinstance(longitude, (float, int))
            or not -90 <= float(latitude) <= 90
            or not -180 <= float(longitude) <= 180
        ):
            raise ValueError("POLIZEIKARTE row contains an invalid coordinate")
        precision = event.get("public_precision")
        if precision not in {"CITY", "DISTRICT", "STREET", "ADDRESS", "PLACE", "POINT"}:
            raise ValueError("POLIZEIKARTE row contains an unknown location precision")
        normalized[entry_id] = {
            "entry_id": entry_id,
            "title": _clean(str(event.get("title") or "")),
            "category": category,
            "occurred_at": _occurred_at(str(event.get("occurred_at") or "")),
            "district": _clean(str(event["district"])) if event.get("district") else None,
            "public_precision": precision,
            "latitude": float(latitude) if latitude is not None else None,
            "longitude": float(longitude) if longitude is not None else None,
            "official_url": _official_url(str(event.get("source_url") or "")),
        }
    if len(normalized) != category_count:
        raise ValueError("POLIZEIKARTE map payload count differs from the declared category total")
    return {
        "rows": parser.rows,
        "events": normalized,
        "category_count": category_count,
        "overall_count": overall_count,
        "page_count": _page_count(page),
    }


def _listing_url(category: str, page: int = 1) -> str:
    if category not in CATEGORIES or page < 1:
        raise ValueError("Invalid POLIZEIKARTE listing request")
    query: dict[str, int | str] = {"zeitraum": WINDOW_DAYS, "kategorie": category}
    if page > 1:
        query["seite"] = page
    return ORIGIN + CITY_PATH + "?" + urlencode(query)


def _validate_listing_response(response: httpx.Response, requested_url: str) -> str:
    response.raise_for_status()
    if response.status_code != 200 or str(response.url) != requested_url:
        raise ValueError("POLIZEIKARTE listing redirected or returned an unexpected URL")
    if "text/html" not in response.headers.get("content-type", ""):
        raise ValueError("POLIZEIKARTE listing did not return HTML")
    if len(response.content) > 12_000_000:
        raise ValueError("POLIZEIKARTE listing exceeded the bounded response size")
    return response.text


def robots_status(client: httpx.Client) -> dict[str, object]:
    response = client.get(ROBOTS_URL, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    if response.status_code != 200 or str(response.url) != ROBOTS_URL:
        raise ValueError("Missing or unexpected POLIZEIKARTE robots.txt response")
    robots = RobotFileParser()
    robots.parse(response.text.splitlines())
    target = _listing_url(CATEGORIES[0])
    return {
        "robots_url": ROBOTS_URL,
        "listing_allowed": robots.can_fetch(USER_AGENT, target),
        "crawl_delay": robots.crawl_delay(USER_AGENT),
    }


def connect(path: Path | str) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def _canonical_hash(row: dict[str, object]) -> str:
    fields = {
        key: row[key]
        for key in (
            "entry_id",
            "detail_url",
            "title",
            "summary",
            "category",
            "occurred_at",
            "place_label",
            "district",
            "public_precision",
            "latitude",
            "longitude",
            "official_url",
        )
    }
    canonical = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _stage_snapshot(
    db: sqlite3.Connection,
    *,
    scan_id: str,
    rows: list[dict[str, object]],
    pages: list[dict[str, object]],
    started: float,
    expected_total: int,
    signature: str,
) -> dict[str, object]:
    now = time.time()
    stats = {"new": 0, "revised": 0, "unchanged": 0}
    with db:
        for row in rows:
            digest = _canonical_hash(row)
            previous = db.execute(
                "SELECT source_hash,revision,first_seen FROM polizeikarte_entries WHERE entry_id=?",
                (row["entry_id"],),
            ).fetchone()
            if previous is None:
                revision = 1
                first_seen = now
                stats["new"] += 1
            elif previous["source_hash"] == digest:
                revision = previous["revision"]
                first_seen = previous["first_seen"]
                stats["unchanged"] += 1
            else:
                revision = previous["revision"] + 1
                first_seen = previous["first_seen"]
                stats["revised"] += 1
            db.execute(
                """INSERT INTO polizeikarte_entries(
                   entry_id,detail_url,title,summary,category,occurred_at,place_label,district,
                   public_precision,latitude,longitude,official_url,source_hash,revision,
                   first_seen,checked,active,scan_id)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)
                   ON CONFLICT(entry_id) DO UPDATE SET
                   detail_url=excluded.detail_url,title=excluded.title,summary=excluded.summary,
                   category=excluded.category,occurred_at=excluded.occurred_at,
                   place_label=excluded.place_label,district=excluded.district,
                   public_precision=excluded.public_precision,latitude=excluded.latitude,
                   longitude=excluded.longitude,official_url=excluded.official_url,
                   source_hash=excluded.source_hash,revision=excluded.revision,
                   checked=excluded.checked,active=1,scan_id=excluded.scan_id""",
                (
                    row["entry_id"],
                    row["detail_url"],
                    row["title"],
                    row["summary"],
                    row["category"],
                    row["occurred_at"],
                    row["place_label"],
                    row["district"],
                    row["public_precision"],
                    row["latitude"],
                    row["longitude"],
                    row["official_url"],
                    digest,
                    revision,
                    first_seen,
                    now,
                    scan_id,
                ),
            )
            db.execute(
                "INSERT OR IGNORE INTO polizeikarte_revisions VALUES(?,?,?,?)",
                (row["entry_id"], revision, digest, now),
            )
        db.execute("UPDATE polizeikarte_entries SET active=0 WHERE scan_id<>?", (scan_id,))
        db.execute("DELETE FROM polizeikarte_pages WHERE scan_id=?", (scan_id,))
        db.executemany(
            "INSERT INTO polizeikarte_pages VALUES(?,?,?,?,?,?,?)",
            [
                (
                    scan_id,
                    page["category"],
                    page["page"],
                    page["url"],
                    page["sha256"],
                    page["list_rows"],
                    page["map_rows"],
                )
                for page in pages
            ],
        )
        summary = {
            **stats,
            "active": len(rows),
            "expected_total": expected_total,
            "categories": {category: sum(row["category"] == category for row in rows)
                           for category in CATEGORIES},
        }
        db.execute(
            """INSERT OR REPLACE INTO polizeikarte_scans(
               scan_id,window_days,started,finished,expected_total,stored_total,
               complete,signature,summary_json) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                scan_id,
                WINDOW_DAYS,
                started,
                now,
                expected_total,
                len(rows),
                1,
                signature,
                json.dumps(summary, ensure_ascii=False, sort_keys=True),
            ),
        )
    return {"scan_id": scan_id, "complete": True, **summary}


def collect(
    path: Path | str,
    *,
    delay: float = 1.0,
    client: httpx.Client | None = None,
) -> dict[str, object]:
    """Collect and atomically checkpoint one complete rolling 365-day snapshot."""
    if not 0 <= delay <= 60:
        raise ValueError("Delay must be between 0 and 60 seconds")
    owns_client = client is None
    if client is None:
        client = httpx.Client(
            timeout=30,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
        )
    started = time.time()
    scan_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    try:
        permission = robots_status(client)
        if not permission["listing_allowed"]:
            raise PermissionError("POLIZEIKARTE robots.txt does not allow the Munich listing")
        effective_delay = max(delay, float(permission["crawl_delay"] or 0))
        all_rows: list[dict[str, object]] = []
        page_records: list[dict[str, object]] = []
        category_signatures: list[str] = []
        declared_overall: set[int] = set()
        for category_index, category in enumerate(CATEGORIES):
            url = _listing_url(category)
            page = _validate_listing_response(client.get(url), url)
            parsed = parse_listing_page(page, category)
            category_rows = list(parsed["rows"])
            declared_overall.add(int(parsed["overall_count"]))
            page_records.append(
                {
                    "category": category,
                    "page": 1,
                    "url": url,
                    "sha256": hashlib.sha256(page.encode()).hexdigest(),
                    "list_rows": len(parsed["rows"]),
                    "map_rows": len(parsed["events"]),
                }
            )
            for page_number in range(2, int(parsed["page_count"]) + 1):
                time.sleep(effective_delay)
                page_url = _listing_url(category, page_number)
                body = _validate_listing_response(client.get(page_url), page_url)
                continuation = parse_listing_page(body, category)
                if (
                    continuation["category_count"] != parsed["category_count"]
                    or continuation["overall_count"] != parsed["overall_count"]
                    or continuation["page_count"] != parsed["page_count"]
                    or set(continuation["events"]) != set(parsed["events"])
                ):
                    raise ValueError("POLIZEIKARTE category changed during pagination")
                category_rows.extend(continuation["rows"])
                page_records.append(
                    {
                        "category": category,
                        "page": page_number,
                        "url": page_url,
                        "sha256": hashlib.sha256(body.encode()).hexdigest(),
                        "list_rows": len(continuation["rows"]),
                        "map_rows": len(continuation["events"]),
                    }
                )
            row_ids = [int(row["entry_id"]) for row in category_rows]
            events = parsed["events"]
            if len(row_ids) != len(set(row_ids)) or set(row_ids) != set(events):
                raise ValueError("POLIZEIKARTE paginated list and map payload IDs differ")
            for row in category_rows:
                supplied = events[int(row["entry_id"])]
                if row["title"] != supplied["title"]:
                    raise ValueError("POLIZEIKARTE list and map payload titles differ")
                all_rows.append({**supplied, **row})
            category_signatures.append(
                f"{category}:{parsed['category_count']}:" + ",".join(map(str, sorted(events)))
            )
            if category_index + 1 < len(CATEGORIES):
                time.sleep(effective_delay)
        if len(declared_overall) != 1:
            raise ValueError("POLIZEIKARTE categories disagree on the overall total")
        expected_total = declared_overall.pop()
        ids = [int(row["entry_id"]) for row in all_rows]
        if len(ids) != len(set(ids)):
            raise ValueError("POLIZEIKARTE categories overlap; category partition changed")
        if len(ids) != expected_total:
            raise ValueError("POLIZEIKARTE category totals do not equal the overall total")
        signature = hashlib.sha256("\n".join(category_signatures).encode()).hexdigest()
        with connect(path) as db:
            return _stage_snapshot(
                db,
                scan_id=scan_id,
                rows=all_rows,
                pages=page_records,
                started=started,
                expected_total=expected_total,
                signature=signature,
            )
    finally:
        if owns_client:
            client.close()


def status(path: Path | str) -> dict[str, object]:
    db_path = Path(path)
    if not db_path.is_file():
        return {"complete": False, "active": 0, "reason": "checkpoint missing"}
    with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        scan = db.execute(
            "SELECT * FROM polizeikarte_scans WHERE complete=1 ORDER BY finished DESC LIMIT 1"
        ).fetchone()
        if scan is None:
            return {"complete": False, "active": 0, "reason": "no complete snapshot"}
        active = db.execute("SELECT count(*) FROM polizeikarte_entries WHERE active=1").fetchone()[0]
        categories = dict(
            db.execute(
                "SELECT category,count(*) FROM polizeikarte_entries WHERE active=1 GROUP BY category"
            ).fetchall()
        )
        return {
            "complete": bool(scan["complete"]),
            "scan_id": scan["scan_id"],
            "window_days": scan["window_days"],
            "expected_total": scan["expected_total"],
            "active": active,
            "categories": categories,
            "signature": scan["signature"],
        }


def candidate_snapshot(path: Path | str) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Return hash-checked local candidates that retain upstream semantics.

    POLIZEIKARTE's street coordinates are retained as approximate display
    points.  City and district representatives remain provenance only, because
    treating a centroid as an incident point would create a false hotspot.
    """
    db_path = Path(path)
    if not db_path.is_file():
        raise ValueError("Munich POLIZEIKARTE checkpoint is missing")
    with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        scan = db.execute(
            "SELECT * FROM polizeikarte_scans WHERE complete=1 ORDER BY finished DESC LIMIT 1"
        ).fetchone()
        if scan is None:
            raise ValueError("Munich has no complete POLIZEIKARTE snapshot")
        saved = db.execute(
            """SELECT * FROM polizeikarte_entries
               WHERE active=1 AND scan_id=? ORDER BY occurred_at,entry_id""",
            (scan["scan_id"],),
        ).fetchall()
        if len(saved) != scan["expected_total"] or len(saved) != scan["stored_total"]:
            raise ValueError("Munich active entry count differs from the complete snapshot")
        events: list[dict[str, object]] = []
        source_coordinates = 0
        withheld_representatives = 0
        empty_summaries = 0
        for saved_row in saved:
            row = dict(saved_row)
            expected_hash = _canonical_hash(row)
            if expected_hash != row["source_hash"]:
                raise ValueError(f"Munich POLIZEIKARTE source hash mismatch: {row['entry_id']}")
            revision = db.execute(
                """SELECT source_hash FROM polizeikarte_revisions
                   WHERE entry_id=? AND revision=?""",
                (row["entry_id"], row["revision"]),
            ).fetchone()
            if revision is None or revision["source_hash"] != row["source_hash"]:
                raise ValueError(f"Munich POLIZEIKARTE revision mismatch: {row['entry_id']}")
            upstream_coordinates = (
                [row["longitude"], row["latitude"]]
                if row["longitude"] is not None and row["latitude"] is not None
                else None
            )
            if upstream_coordinates:
                source_coordinates += 1
            coordinates = upstream_coordinates if row["public_precision"] == "STREET" else None
            if upstream_coordinates and coordinates is None:
                withheld_representatives += 1
            if not row["summary"]:
                empty_summaries += 1
            events.append(
                {
                    "id": f"polizeikarte:{row['entry_id']}",
                    "title": row["title"],
                    "category": row["category"],
                    "published_at": None,
                    "event_date": row["occurred_at"][:10],
                    "month": row["occurred_at"][:7],
                    "time_basis": "polizeikarte_occurred_at",
                    "source_url": row["official_url"],
                    "feed_url": row["detail_url"],
                    "district": row["district"] or "",
                    "poi_mentions": [],
                    "mention_basis": "not_yet_analyzed",
                    "outcome": "unknown",
                    "source_status": "polizeikarte_complete_365_day_snapshot",
                    "source_sha256": row["source_hash"],
                    "source_revision": row["revision"],
                    "coordinates": coordinates,
                    "location_precision": row["public_precision"].lower(),
                    "location_label": row["place_label"],
                    "geocode_method": (
                        "polizeikarte_supplied_street_coordinate"
                        if coordinates
                        else "polizeikarte_supplied_nonpoint_location"
                    ),
                    "geocode_candidates": [],
                    "geocode_version": "polizeikarte-upstream-1",
                    "location_object_ids": [],
                    "geocode_evidence": [],
                    "source_summary": row["summary"],
                    "upstream_category": row["category"],
                    "upstream_public_precision": row["public_precision"],
                    "upstream_coordinates": upstream_coordinates,
                    "upstream_provider": "POLIZEIKARTE",
                    "semantic_basis": "owner_accepted_polizeikarte_upstream",
                }
            )
        audit = {
            "city": "munich",
            "source": "POLIZEIKARTE Munich rolling 365-day dataset",
            "scan_id": scan["scan_id"],
            "signature": scan["signature"],
            "archive_complete": True,
            "coverage": {
                "active": len(events),
                "expected_total": scan["expected_total"],
                "source_coordinates": source_coordinates,
                "street_coordinate_candidates": sum(bool(event["coordinates"]) for event in events),
                "city_or_district_representatives_withheld": withheld_representatives,
                "without_candidate_point": sum(not event["coordinates"] for event in events),
                "empty_summaries": empty_summaries,
                "official_source_urls": db.execute(
                    "SELECT count(DISTINCT official_url) FROM polizeikarte_entries WHERE active=1"
                ).fetchone()[0],
            },
            "upstream_semantics": "owner selected POLIZEIKARTE classifications and locations",
            "review_basis": "owner_accepted_polizeikarte_upstream",
            "source_first_llm_rereview_required": False,
            "publication_ready": False,
            "publication_block": "local candidate snapshot still needs POI integration and owner approval",
        }
        return events, audit


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Checkpoint POLIZEIKARTE's complete rolling Munich dataset"
    )
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--export-candidates", type=Path)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(".runtime/safety/cities/munich/police.sqlite"),
    )
    args = parser.parse_args()
    if sum((args.collect, args.status, args.export_candidates is not None)) != 1:
        parser.error("Choose exactly one of --collect, --status or --export-candidates")
    runtime = (Path.cwd() / ".runtime").resolve()
    if not args.db.resolve().is_relative_to(runtime) or (
        args.export_candidates and not args.export_candidates.resolve().is_relative_to(runtime)
    ):
        parser.error("SQLite checkpoint and candidate output must be under .runtime/")
    if args.collect:
        result = collect(args.db, delay=args.delay)
    elif args.status:
        result = status(args.db)
    else:
        events, audit = candidate_snapshot(args.db)
        args.export_candidates.parent.mkdir(parents=True, exist_ok=True)
        args.export_candidates.write_text(
            json.dumps({"city": "munich", "events": events}, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        result = {**audit, "output": str(args.export_candidates)}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
