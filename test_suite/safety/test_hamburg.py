import pytest

from crimemapsberlin.collector import accept, connect, discover
from crimemapsberlin.hamburg import (
    article_body, article_district, listing_rows, restore_cached_districts,
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
<p class="contact-headline">Rückfragen der Medien bitte an:</p>
<p class="contact-text">Polizei Hamburg, Dienststelle an der Falschestraße</p>
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
    assert "Wrongstraße" not in body
    assert "Falschestraße" not in body
    assert "Anderstraße" not in body
    assert article_district(body) == "Wandsbek"
    assert article_district("Tatort: Hamburg-Mitte, Straße. Tatort: Hamburg-Wandsbek, Platz.") == ""
    assert article_district("Tatort: Hamburg-St. Georg, Besenbinderhof") == "St. Georg"
    assert article_district("Unfallort: Hamburg-Moorfleet, Amandus-Stubbe-Straße") == "Moorfleet"
    with pytest.raises(ValueError, match="publisher"):
        article_body(ARTICLE.replace("<a>Polizei Hamburg</a>", "<a>Other publisher</a>"))


def test_cached_hamburg_article_restores_district_without_network(tmp_path):
    db = connect(tmp_path / "hamburg.sqlite")
    row = listing_rows(LISTING)[0]
    discover(db, [row], 1)
    body = article_body(ARTICLE)
    accept(db, row["id"], body, {}, 2)
    assert restore_cached_districts(db) == 1
    assert db.execute("SELECT district FROM reports").fetchone()[0] == "Wandsbek"
    assert restore_cached_districts(db) == 0
