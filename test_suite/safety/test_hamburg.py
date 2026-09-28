import httpx
import pytest

from crimemapsberlin import hamburg
from crimemapsberlin.city_sources import read_city_source
from crimemapsberlin.collector import accept, connect, discover
from crimemapsberlin.hamburg import (
    article_body,
    article_district,
    listing_rows,
    restore_cached_districts,
)

LISTING = '''<article class="news" data-label="6358440">
<div class="date">24.09.2026 &ndash; 12:59</div>
<h3 class="news-headline-clamp"><a href="https://www.presseportal.de/blaulicht/pm/6337/6358440">
POL-HH: Überfall am Bahnhof</a></h3></article>'''

ARTICLE = '''<nav>Polizei Hamburg · Wrongstraße</nav>
<article class="col eight story mbs">
<p class="date">24.09.2026</p><p class="customer"><a>Polizei Hamburg</a></p>
<h1>POL-HH: Überfall</h1><div class="story-sharing"></div>
<p><i>Hamburg (ots)</i></p><p>Tatort: Hamburg-Wandsbek, Ostpreußenplatz</p>
<p>Am Ostpreußenplatz wurde ein Mann beraubt.</p>
<p>Täter 1:</p><pre>   - männlich
   - circa 30 Jahre alt
   - trug eine schwarze Kapuze</pre>
<ul><li>etwa 180 cm groß</li><li><strong>dunkle</strong> Jacke</li></ul>
<p class="contact-headline">Rückfragen der Medien bitte an:</p>
<p class="contact-text">Polizei Hamburg, Dienststelle an der Falschestraße</p>
<pre>Kontakttelefon 040/000000</pre>
</article><article class="news"><p>Another incident in Anderstraße</p></article>'''


def test_newsroom_parser_keeps_only_matching_police_article_ids():
    rows = listing_rows(LISTING)
    assert len(rows) == 1
    assert rows[0]["id"] == "6358440"
    assert rows[0]["published"] == "2026-09-24T12:59:00"
    assert rows[0]["url"].endswith("/6337/6358440")
    with pytest.raises(ValueError, match="unparsed"):
        listing_rows(LISTING.replace("/6337/6358440", "/9999/6358440"))


def test_article_ignores_navigation_contacts_and_related_reports():
    body = article_body(ARTICLE)
    assert "Ostpreußenplatz" in body
    assert "circa 30 Jahre alt" in body
    assert "schwarze Kapuze" in body
    assert "etwa 180 cm groß" in body
    assert "dunkle Jacke" in body
    assert "Wrongstraße" not in body
    assert "Falschestraße" not in body
    assert "Kontakttelefon" not in body
    assert "Anderstraße" not in body
    assert article_district(body) == "Wandsbek"
    assert article_district("Tatort: Hamburg-Mitte, Straße. Tatort: Hamburg-Wandsbek, Platz.") == ""
    assert article_district("Tatort: Hamburg-St. Georg, Besenbinderhof") == "St. Georg"
    assert article_district("Unfallort: Hamburg-Moorfleet, Amandus-Stubbe-Straße") == "Moorfleet"
    assert article_district("Feststellort: Hamburg-St. Georg, Steindamm") == "St. Georg"
    assert article_district(
        "Tatzeitraum: Mai bis August; Tatort: Hamburg-Wandsbek Die Polizei ermittelt."
    ) == "Wandsbek"
    assert article_district(
        "Tatort: Hamburg-Mitte Tatort: Hamburg-Wandsbek Die Polizei ermittelt."
    ) == ""
    assert article_district(
        "Tatorte: a) Hamburg-Blankenese, Teststraße b) Hamburg-Blankenese, Testweg "
        "Nachdem zwei Taten gemeldet worden waren, ermittelt die Polizei."
    ) == "Blankenese"
    assert article_district(
        "Tatorte: Hamburg-Wandsbek, Teststraße / Testweg Gestern wurden mehrere Taten gemeldet."
    ) == "Wandsbek"
    assert article_district(
        "Tatorte: Hamburg-Eidelstedt, -Eppendorf, -Niendorf und -Schnelsen "
        "Den Strafverfolgungsbehörden liegen mehrere Anzeigen vor."
    ) == ""
    assert article_district(
        "Tatorte: a) Hamburg-Mitte, Teststraße b) Hamburg-Wandsbek, Testweg "
        "Nachdem zwei Taten gemeldet worden waren, ermittelt die Polizei."
    ) == ""
    assert article_district(
        "Orte: a) Hamburg-Borgfelde, Teststraße b) Hamburg-St. Pauli und "
        "Hamburg-Altona-Altstadt a) Im Zuge einer Sperrung kommt es zu Behinderungen."
    ) == ""
    assert article_district(
        "Orte: a) Bundesautobahn 7 b) Hamburg-Borgfelde, Teststraße "
        "Am kommenden Wochenende werden beide Bereiche gesperrt."
    ) == ""
    assert article_district(
        "Tatorte: mehrere Stadtteile im Bezirk Hamburg-Harburg Am frühen Samstagmorgen "
        "wurde ein Tatverdächtiger festgenommen."
    ) == ""
    with pytest.raises(ValueError, match="publisher"):
        article_body(ARTICLE.replace("<a>Polizei Hamburg</a>", "<a>Other publisher</a>"))

    nested_contact = ARTICLE.replace(
        '<p class="contact-headline">Rückfragen der Medien bitte an:</p>',
        '<ul><li>discard this contact wrapper<p class="contact-headline">Rückfragen</p></li></ul>',
    )
    assert "discard this contact wrapper" not in article_body(nested_contact)


def test_parser_v2_cache_is_refetched_without_conditional_headers(tmp_path, monkeypatch):
    listing = LISTING.replace("24.09.2026", "01.01.2026")
    row = listing_rows(listing)[0]
    path = tmp_path / "hamburg.sqlite"
    db = connect(path)
    db.execute("ALTER TABLE reports ADD COLUMN parser_version INTEGER NOT NULL DEFAULT 1")
    discover(db, [row], 1)
    accept(
        db,
        row["id"],
        "Tatort: Hamburg-Wandsbek, Ostpreußenplatz. Alter Parsertext ohne Täterbeschreibung.",
        {"etag": '"parser-v2"', "last-modified": "Thu, 01 Jan 2026 12:00:00 GMT"},
        2,
    )
    db.execute("UPDATE reports SET parser_version=2,checked=?", (10**12,))
    db.commit()
    db.close()

    article_requests = []

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if request.url.path == "/blaulicht/nr/6337":
            return httpx.Response(200, text=listing)
        if request.url.path == "/blaulicht/pm/6337/6358440":
            article_requests.append(request)
            return httpx.Response(200, text=ARTICLE, headers={"etag": '"parser-v3"'})
        raise AssertionError(request.url)

    real_client = httpx.Client
    monkeypatch.setattr(
        hamburg.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = hamburg.sync(path, 2026, limit=1, delay=0)

    assert result["revised"] == 1
    assert result["parser_pending"] == 0
    assert len(article_requests) == 1
    assert "if-none-match" not in article_requests[0].headers
    assert "if-modified-since" not in article_requests[0].headers
    db = connect(path)
    saved = db.execute("SELECT body,parser_version FROM reports").fetchone()
    assert saved["parser_version"] == 3
    assert "schwarze Kapuze" in saved["body"]
    db.close()


def test_cached_hamburg_article_restores_district_without_network(tmp_path):
    db = connect(tmp_path / "hamburg.sqlite")
    row = listing_rows(LISTING)[0]
    discover(db, [row], 1)
    body = article_body(ARTICLE)
    accept(db, row["id"], body, {}, 2)
    assert restore_cached_districts(db) == 1
    assert db.execute("SELECT district FROM reports").fetchone()[0] == "Wandsbek"
    assert restore_cached_districts(db) == 0
    db.close()


def test_full_scan_records_stable_year_coverage(tmp_path, monkeypatch):
    current = LISTING.replace(
        "</article>",
        '</article><link rel="next" href="/blaulicht/nr/6337/2">',
    )
    older = LISTING.replace("6358440", "6000000").replace("24.09.2026", "31.12.2025")
    head_requests = 0

    def handler(request):
        nonlocal head_requests
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if request.url.path == "/blaulicht/nr/6337":
            head_requests += 1
            return httpx.Response(200, text=current)
        if request.url.path == "/blaulicht/nr/6337/2":
            return httpx.Response(200, text=older)
        if request.url.path == "/blaulicht/pm/6337/6358440":
            return httpx.Response(200, text=ARTICLE)
        raise AssertionError(request.url)

    real_client = httpx.Client
    monkeypatch.setattr(
        hamburg.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    path = tmp_path / "hamburg.sqlite"
    result = hamburg.sync(path, 2026, full=True, limit=1, delay=0)

    assert result["year_boundary_reached"] is True
    assert result["head_stable"] is True
    assert result["archive_complete"] is True
    assert result["archive_pages"] == 2
    assert head_requests == 2
    assert read_city_source("hamburg", path).archive_complete is True

    incremental = hamburg.sync(path, 2026, full=False, limit=1, delay=0)
    assert incremental["archive_complete"] is True
    assert head_requests == 3
