import json
import sqlite3

import httpx
import pytest

import crimemapsberlin.polizeikarte_munich as source


def event(entry_id, category, *, latitude=48.13, longitude=11.57, precision=None):
    return {
        "id": entry_id,
        "title": f"Meldung {entry_id}",
        "category": category,
        "occurred_at": "$D2026-09-27T21:00:00.000Z",
        "district": "Altstadt-Lehel",
        "public_precision": precision or ("STREET" if latitude is not None else "DISTRICT"),
        "lat": latitude,
        "lng": longitude,
        "source_url": (
            f"https://polizei.bayern.de/aktuelles/pressemitteilungen/{entry_id}/index.html"
        ),
    }


def page(category, events, rows, *, total, current=1, pages=1):
    listing = []
    for row in rows:
        listing.append(
            '<div class="list-day">Sonntag, 27. September 2026</div>'
            '<div class="card event-row">'
            '<div class="event-time">21:00</div>'
            '<div class="event-main"><div class="cat">'
            f'<a href="/muenchen/meldung/{row["id"]}-meldung-{row["id"]}">'
            f'{row["title"]}</a></div>'
            f'<div class="place">{row.get("place", "München")}</div>'
            f'<div class="summary">Zusammenfassung der Meldung {row["id"]} mit genug Text.</div>'
            "</div></div>"
        )
    flight = "5:" + json.dumps(
        {"events": events, "citySlug": "muenchen"}, ensure_ascii=False, separators=(",", ":")
    )
    payload = json.dumps([1, flight], ensure_ascii=False)
    pagination = (
        '<nav class="seiten"><span>Seite <!-- -->'
        f"{current}<!-- --> von <!-- -->{pages}</span></nav>"
        if pages > 1
        else ""
    )
    return (
        '<html><p class="stats-line"><strong>'
        f'{len(events)} veröffentlichte Vorfälle</strong> in den vergangenen 12 Monaten '
        f'· Kategorie: {category}</p><a>Alle <span class="chip-count">{total}</span></a>'
        + "".join(listing)
        + pagination
        + f"<script>self.__next_f.push({payload})</script></html>"
    )


def test_listing_parser_joins_paginated_rows_to_category_wide_map_payload():
    events = [event(101, "gewalt"), event(102, "gewalt", latitude=None, longitude=None)]
    body = page("gewalt", events, [events[0]], total=2, current=1, pages=2)
    parsed = source.parse_listing_page(body, "gewalt")
    assert parsed["category_count"] == 2
    assert parsed["overall_count"] == 2
    assert parsed["page_count"] == 2
    assert parsed["rows"][0]["entry_id"] == 101
    assert parsed["events"][101]["occurred_at"] == "2026-09-27T21:00:00Z"
    assert parsed["events"][102]["latitude"] is None
    assert parsed["events"][102]["official_url"].startswith("https://polizei.bayern.de/")


def test_listing_parser_rejects_declared_count_or_category_mismatch():
    events = [event(101, "gewalt")]
    with pytest.raises(ValueError, match="count differs"):
        source.parse_listing_page(page("gewalt", events, [events[0]], total=2).replace(
            "1 veröffentlichte", "2 veröffentlichte"
        ), "gewalt")
    wrong = [event(101, "raub")]
    with pytest.raises(ValueError, match="mixed categories"):
        source.parse_listing_page(page("gewalt", wrong, [wrong[0]], total=1), "gewalt")


def test_complete_snapshot_is_atomic_hash_bound_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(source, "CATEGORIES", ("gewalt", "raub"))
    gewalt = [event(101, "gewalt"), event(102, "gewalt", precision="DISTRICT")]
    raub = [event(201, "raub")]
    responses = {
        source.ROBOTS_URL: ("text/plain", "User-agent: *\nAllow: /\n"),
        source._listing_url("gewalt"): (
            "text/html",
            page("gewalt", gewalt, [gewalt[0]], total=3, current=1, pages=2),
        ),
        source._listing_url("gewalt", 2): (
            "text/html",
            page("gewalt", gewalt, [gewalt[1]], total=3, current=2, pages=2),
        ),
        source._listing_url("raub"): (
            "text/html",
            page("raub", raub, raub, total=3),
        ),
    }

    def responder(request):
        content_type, body = responses[str(request.url)]
        return httpx.Response(200, text=body, headers={"content-type": content_type})

    db_path = tmp_path / "munich.sqlite"
    with httpx.Client(transport=httpx.MockTransport(responder)) as client:
        first = source.collect(db_path, delay=0, client=client)
        second = source.collect(db_path, delay=0, client=client)
    assert first["complete"] is True
    assert first["active"] == 3
    assert first["new"] == 3
    assert second["unchanged"] == 3
    assert source.status(db_path)["categories"] == {"gewalt": 2, "raub": 1}
    candidates, audit = source.candidate_snapshot(db_path)
    indexed = {row["id"]: row for row in candidates}
    assert indexed["polizeikarte:101"]["coordinates"] == [11.57, 48.13]
    assert indexed["polizeikarte:102"]["coordinates"] is None
    assert indexed["polizeikarte:102"]["upstream_coordinates"] == [11.57, 48.13]
    assert indexed["polizeikarte:102"]["semantic_basis"] == "owner_accepted_polizeikarte_upstream"
    assert audit["coverage"]["city_or_district_representatives_withheld"] == 1
    assert audit["review_basis"] == "owner_accepted_polizeikarte_upstream"
    assert audit["source_first_llm_rereview_required"] is False
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT count(*) FROM polizeikarte_revisions").fetchone()[0] == 3
        assert db.execute(
            """SELECT count(*) FROM polizeikarte_pages
               WHERE scan_id=(SELECT scan_id FROM polizeikarte_scans ORDER BY finished DESC LIMIT 1)"""
        ).fetchone()[0] == 3
        assert db.execute(
            "SELECT official_url FROM polizeikarte_entries WHERE entry_id=102"
        ).fetchone()[0].endswith("/102/index.html")
