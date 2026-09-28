import httpx
import pytest

from crimemapsberlin import frankfurt
from crimemapsberlin.collector import accept, connect, discover
from crimemapsberlin.frankfurt import article_body, listing_rows, next_url, sync

LISTING = """<link rel="next" href="/blaulicht/nr/4970/30">
<article class="news" data-label="6359830">
<div class="date">27.09.2026 &ndash; 12:14</div>
<h3 class="news-headline-clamp"><a href="https://www.presseportal.de/blaulicht/pm/4970/6359830">
POL-F: Frankfurt - Gallus: Festnahme</a></h3></article>"""

ARTICLE = """<nav>Another Polizeipräsidium · Wrongstraße</nav>
<article class="col eight story mbs">
<p class="date">27.09.2026</p>
<p class="customer"><a href="/blaulicht/nr/4970">Polizeipräsidium Frankfurt am Main</a></p>
<h1>POL-F: Frankfurt - Gallus: Festnahme</h1>
<p><i>Frankfurt (ots)</i></p>
<p>In der Kleyerstraße wurden zwei Jugendliche festgenommen.</p>
<p>Das Fahrzeug hatte keine gültige Zulassung.</p>
<p>Täter 1:</p><pre>   - männlich
   - circa 30 Jahre alt
   - trug eine schwarze Kapuze</pre>
<ul><li>etwa 180 cm groß</li><li><strong>dunkle</strong> Jacke</li></ul>
<p class="contact-headline">Rückfragen bitte an:</p>
<p class="contact-text">Pressestelle an der Falschestraße</p>
<pre>Kontakttelefon 069/000000</pre>
<p class="originator">Original-Content von: Polizeipräsidium Frankfurt am Main</p>
</article><article class="news"><p>Another incident in Anderstraße</p></article>"""


def test_frankfurt_listing_accepts_only_matching_publisher_ids():
    rows = listing_rows(LISTING)
    assert len(rows) == 1
    assert rows[0] == {
        "id": "6359830",
        "url": "https://www.presseportal.de/blaulicht/pm/4970/6359830",
        "title": "POL-F: Frankfurt - Gallus: Festnahme",
        "published": "2026-09-27T12:14:00",
        "district": "",
    }
    with pytest.raises(ValueError, match="unparsed"):
        listing_rows(LISTING.replace("/pm/4970/6359830", "/pm/6337/6359830"))
    with pytest.raises(ValueError, match="unparsed"):
        listing_rows("<article class='news' data-label='123'></article>")


def test_frankfurt_article_excludes_navigation_contacts_and_related_stories():
    body = article_body(ARTICLE)
    assert "Kleyerstraße" in body
    assert "Zulassung" in body
    assert "circa 30 Jahre alt" in body
    assert "schwarze Kapuze" in body
    assert "etwa 180 cm groß" in body
    assert "dunkle Jacke" in body
    assert "Wrongstraße" not in body
    assert "Falschestraße" not in body
    assert "Kontakttelefon" not in body
    assert "Anderstraße" not in body
    with pytest.raises(ValueError, match="publisher"):
        article_body(ARTICLE.replace("Polizeipräsidium Frankfurt am Main</a>", "Other publisher</a>"))

    nested_contact = ARTICLE.replace(
        '<p class="contact-headline">Rückfragen bitte an:</p>',
        '<ul><li>discard this contact wrapper<h2 class="contact-headline">Rückfragen</h2></li></ul>',
    )
    assert "discard this contact wrapper" not in article_body(nested_contact)


def test_frankfurt_parser_v2_cache_is_refetched_without_conditional_headers(tmp_path, monkeypatch):
    listing = LISTING.replace("27.09.2026", "01.01.2026")
    row = listing_rows(listing)[0]
    path = tmp_path / "frankfurt.sqlite"
    db = connect(path)
    db.execute("ALTER TABLE reports ADD COLUMN parser_version INTEGER NOT NULL DEFAULT 1")
    discover(db, [row], 1)
    accept(
        db,
        row["id"],
        "In der Kleyerstraße erfolgte eine Festnahme. Alter Parsertext ohne Täterbeschreibung.",
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
        if request.url.path == "/blaulicht/nr/4970":
            return httpx.Response(200, text=listing)
        if request.url.path == "/blaulicht/pm/4970/6359830":
            article_requests.append(request)
            return httpx.Response(200, text=ARTICLE, headers={"etag": '"parser-v3"'})
        raise AssertionError(request.url)

    real_client = httpx.Client
    monkeypatch.setattr(
        frankfurt.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = sync(path, 2026, pages=1, limit=1, delay=0)

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


def test_frankfurt_pagination_does_not_leave_publisher_newsroom():
    assert next_url(LISTING) == "https://www.presseportal.de/blaulicht/nr/4970/30"
    assert next_url("<html></html>") is None
    with pytest.raises(ValueError, match="pagination"):
        next_url(LISTING.replace("/nr/4970/30", "/nr/6337/30"))


def test_frankfurt_stores_only_local_checkpoint_with_revision_hash(tmp_path):
    db = connect(tmp_path / "frankfurt.sqlite")
    row = listing_rows(LISTING)[0]
    discover(db, [row], 1)
    assert accept(db, row["id"], article_body(ARTICLE), {}, 2) == "new"
    saved = db.execute("SELECT url,sha256,revision,body FROM reports").fetchone()
    assert saved["url"] == row["url"]
    assert len(saved["sha256"]) == 64
    assert saved["revision"] == 1
    assert "Kleyerstraße" in saved["body"]
    assert accept(db, row["id"], article_body(ARTICLE), {}, 3) == "unchanged"
    assert db.execute("SELECT count(*) FROM revisions").fetchone()[0] == 1
    db.close()


def test_frankfurt_resumes_archive_cursor_and_refreshes_head(tmp_path, monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if request.url.path == "/blaulicht/nr/4970":
            return httpx.Response(200, text=LISTING)
        if request.url.path == "/blaulicht/nr/4970/30":
            older = LISTING.replace("27.09.2026", "27.09.2025").replace('href="/blaulicht/nr/4970/30"', "")
            return httpx.Response(200, text=older)
        if request.url.path == "/blaulicht/pm/4970/6359830":
            return httpx.Response(200, text=ARTICLE)
        raise AssertionError(request.url)

    real_client = httpx.Client
    monkeypatch.setattr(
        frankfurt.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    path = tmp_path / "frankfurt.sqlite"
    first = sync(path, 2026, pages=1, limit=1, delay=0)
    assert first["stored"] == 1
    assert first["archive_complete"] is False
    second = sync(path, 2026, pages=1, limit=1, delay=0)
    assert second["head_refreshed"] is True
    assert second["archive_complete"] is True
    assert second["year_covered"] is True
    assert seen.count("/blaulicht/nr/4970/30") == 1
    db = connect(path)
    assert db.execute("SELECT pages_scanned,complete FROM frankfurt_archive_cursor").fetchone()[:] == (2, 1)
    assert db.execute("SELECT parser_version FROM reports").fetchone()[0] == 3
    db.close()


def test_frankfurt_rejects_redirect_to_a_different_record_path(tmp_path, monkeypatch):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(302, headers={"location": "/blaulicht/nr/6337"})

    real_client = httpx.Client
    monkeypatch.setattr(
        frankfurt.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    path = tmp_path / "frankfurt.sqlite"
    with pytest.raises(ValueError, match="changed record path"):
        sync(path, 2026, pages=1, limit=1, delay=0)
    db = connect(path)
    assert "changed record path" in db.execute("SELECT summary FROM runs").fetchone()[0]
    assert db.execute("SELECT count(*) FROM reports").fetchone()[0] == 0
    db.close()


def test_frankfurt_fails_closed_if_robots_file_is_not_rules(tmp_path, monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, text="<html>temporary placeholder</html>")

    real_client = httpx.Client
    monkeypatch.setattr(
        frankfurt.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    with pytest.raises(ValueError, match="robots.txt"):
        sync(tmp_path / "frankfurt.sqlite", 2026, pages=1, limit=1, delay=0)
    assert seen == ["/robots.txt"]
