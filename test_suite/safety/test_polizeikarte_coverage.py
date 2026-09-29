import hashlib
import json
import sqlite3

import httpx
import pytest

import crimemapsberlin.polizeikarte_coverage as coverage


def event(entry_id, category, source_url):
    return {
        "id": entry_id,
        "title": f"Meldung {entry_id}",
        "category": category,
        "occurred_at": "$D2026-09-27T21:00:00.000Z",
        "district": "Innenstadt",
        "public_precision": "STREET",
        "lat": 50.11,
        "lng": 8.68,
        "source_url": source_url,
    }


def page(category, events, total):
    flight = "5:" + json.dumps(
        {"events": events, "citySlug": "frankfurt"},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    payload = json.dumps([1, flight], ensure_ascii=False)
    return (
        '<html><p class="stats-line"><strong>'
        f'{len(events)} veröffentlichte Vorfälle</strong> in den vergangenen 12 Monaten '
        f'· Kategorie: {category}</p><a>Alle <span class="chip-count">{total}</span></a>'
        f"<script>self.__next_f.push({payload})</script></html>"
    )


def official_db(path):
    db = sqlite3.connect(path)
    db.execute(
        """CREATE TABLE reports(
        id TEXT PRIMARY KEY,url TEXT,title TEXT,published TEXT,body TEXT,sha256 TEXT,error TEXT)"""
    )
    rows = []
    for ident in ("1001", "1002"):
        body = f"Vollständiger amtlicher Text für Meldung {ident}."
        rows.append(
            (
                ident,
                f"https://www.presseportal.de/blaulicht/pm/4970/{ident}",
                f"Amtliche Meldung {ident}",
                "2026-09-27T12:00:00",
                body,
                hashlib.sha256(body.encode()).hexdigest(),
                None,
            )
        )
    db.executemany("INSERT INTO reports VALUES(?,?,?,?,?,?,?)", rows)
    db.commit()
    db.close()


def test_snapshot_and_official_overlap_are_fail_closed_and_hash_bound(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(coverage, "CATEGORIES", ("gewalt", "raub"))
    events = {
        "gewalt": [
            event(11, "gewalt", "https://www.presseportal.de/blaulicht/pm/4970/1001"),
            event(12, "gewalt", "https://presseportal.de/blaulicht/pm/4970/1001/"),
        ],
        "raub": [
            event(21, "raub", "https://polizei.example/amtliche-meldung/21")
        ],
    }
    responses = {coverage.ROBOTS_URL: ("text/plain", "User-agent: *\nAllow: /\n")}
    for category, rows in events.items():
        responses[coverage._listing_url("frankfurt", category)] = (
            "text/html",
            page(category, rows, 3),
        )

    def responder(request):
        content_type, body = responses[str(request.url)]
        return httpx.Response(200, text=body, headers={"content-type": content_type})

    with httpx.Client(transport=httpx.MockTransport(responder)) as client:
        snapshot = coverage.collect_snapshot("frankfurt", delay=0, client=client)
    path = tmp_path / "official.sqlite"
    official_db(path)
    audit = coverage.audit_against_official(snapshot, path)

    assert snapshot["expected_total"] == 3
    assert snapshot["upstream_semantics_accepted"] is False
    assert audit["coverage"] == {
        "official_reports_total": 2,
        "official_source_hashes_verified": 2,
        "upstream_entries_total": 3,
        "upstream_entries_directly_matched": 2,
        "upstream_entries_without_direct_match": 1,
        "official_reports_directly_matched": 1,
        "official_reports_without_direct_upstream_match": 1,
        "official_reports_with_multiple_upstream_entries": 1,
    }
    assert {match["match_method"] for match in audit["matches"]} == {
        "canonical_url",
        "presseportal_article_id",
    }
    assert audit["llm_review_bypassed"] is False
    assert audit["publication_ready"] is False


def test_snapshot_rejects_cross_category_duplicate_and_robots_denial(monkeypatch):
    monkeypatch.setattr(coverage, "CATEGORIES", ("gewalt", "raub"))
    duplicate = event(
        11, "gewalt", "https://www.presseportal.de/blaulicht/pm/4970/1001"
    )
    responses = {
        coverage.ROBOTS_URL: ("text/plain", "User-agent: *\nAllow: /\n"),
        coverage._listing_url("frankfurt", "gewalt"): (
            "text/html",
            page("gewalt", [duplicate], 2),
        ),
        coverage._listing_url("frankfurt", "raub"): (
            "text/html",
            page("raub", [{**duplicate, "category": "raub"}], 2),
        ),
    }

    def responder(request):
        content_type, body = responses[str(request.url)]
        return httpx.Response(200, text=body, headers={"content-type": content_type})

    with (
        httpx.Client(transport=httpx.MockTransport(responder)) as client,
        pytest.raises(ValueError, match="duplicate IDs"),
    ):
        coverage.collect_snapshot("frankfurt", delay=0, client=client)

    def denied(request):
        assert str(request.url) == coverage.ROBOTS_URL
        return httpx.Response(
            200,
            text="User-agent: *\nDisallow: /frankfurt\n",
            headers={"content-type": "text/plain"},
        )

    with (
        httpx.Client(transport=httpx.MockTransport(denied)) as client,
        pytest.raises(PermissionError, match="disallows"),
    ):
        coverage.collect_snapshot("frankfurt", delay=0, client=client)
