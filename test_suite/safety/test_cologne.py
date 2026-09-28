import httpx
import pytest

from crimemapsberlin import cologne

from crimemapsberlin.cologne import (
    accept, article_record, city_scope, connect, discover, listing_rows,
    next_archive_page,
    sync,
)


LISTING = '''<div class="view view-list-view-press-releases-solr"><div class="view-content">
<div class="views-row"><div class="field-content"><div class="press-list">
<H2 class="field-title"><a href="/presse/streit-in-koeln-ossendorf-eskaliert">Streit in Köln-Ossendorf eskaliert</a></H2>
<div class="date-time"><time datetime="2026-09-26T20:31:59+02:00">26. September 2026</time></div>
<div class="combined-location">Polizei Köln | PLZ: 51103</div>
</div></div></div>
<div class="views-row"><div class="field-content"><div class="press-list">
<H2 class="field-title"><a href="/presse/polizei-sucht-nach-mutmasslichem-brandstifter">Polizei sucht nach mutmaßlichem Brandstifter</a></H2>
<div class="date-time"><time datetime="2026-09-25T12:28:18+02:00">25. September 2026</time></div>
<div class="combined-location">Polizei Köln | PLZ: 51103</div>
</div></div></div></div></div>
<nav aria-label="Seitennummerierung"><a href="?created_1=01.01.2026&amp;created_2=31.12.2026&amp;page=1"
title="Zur nächsten Seite">mehr Ergebnisse anzeigen</a></nav>'''

ARTICLE = '''<link rel="canonical" href="https://koeln.polizei.nrw/presse/polizei-sucht-nach-mutmasslichem-brandstifter" />
<article about="/presse/polizei-sucht-nach-mutmasslichem-brandstifter" class="node node--type--press-release node--view-mode-full">
<div class="field field--name-field-press-release-author">Polizei Köln</div>
<div class="field field--name-body"><p>In Leverkusen-Schlebusch versuchte ein Unbekannter,
den Eingangsbereich eines Hauses anzuzünden.</p><p>Die Polizei sucht Zeugen.</p></div></article>
<aside>In Köln befindet sich die Pressestelle, nicht der Tatort.</aside>
<script>var settings={"path":{"currentPath":"node\\/217132"}}</script>'''


def test_native_archive_keeps_only_own_rows_and_pagination():
    rows = listing_rows(LISTING)
    assert [row["id"] for row in rows] == [
        "streit-in-koeln-ossendorf-eskaliert", "polizei-sucht-nach-mutmasslichem-brandstifter",
    ]
    assert rows[0]["published"] == "2026-09-26T20:31:59+02:00"
    assert next_archive_page(LISTING) == 1
    with pytest.raises(ValueError, match="origin"):
        listing_rows(LISTING.replace("/presse/streit-in-koeln-ossendorf-eskaliert",
                                     "https://foreign.example/story"))


def test_native_article_uses_stable_id_and_excludes_sidebar():
    url = "https://koeln.polizei.nrw/presse/polizei-sucht-nach-mutmasslichem-brandstifter"
    record = article_record(ARTICLE, url)
    assert record["source_id"] == "217132"
    assert "Leverkusen-Schlebusch" in record["body"]
    assert "Pressestelle" not in record["body"]
    with pytest.raises(ValueError, match="publisher"):
        article_record(ARTICLE.replace(">Polizei Köln</div>", ">Andere Behörde</div>"), url)


def test_city_scope_never_infers_scene_from_issuing_authority_or_zip():
    assert city_scope("Polizei Köln", "Polizei Köln | PLZ: 51103")[0] == "needs_review"
    assert city_scope("Brandstiftung", "In Leverkusen-Schlebusch brannte ein Haus.")[0] == "outside_candidate"
    assert city_scope("Explosion", "In Köln-Ehrenfeld explodierte ein Kasten.")[0] == "cologne_candidate"
    assert city_scope("Ermittlungen", "Tat in Erftstadt; Festnahme in Köln.")[0] == "needs_review"
    assert city_scope("Unfall auf der BAB 3", "Auf der Autobahn 3 kam es zum Unfall.")[0] == "needs_review"
    assert city_scope("In der Kölner Straße", "In Leverkusen trafen sich Zeugen.")[0] == "outside_candidate"


def test_checkpoint_revisions_and_source_id_are_local(tmp_path):
    db = connect(tmp_path / "cologne.sqlite")
    row = listing_rows(LISTING)[1]
    discover(db, [row], 1)
    record = article_record(ARTICLE, row["url"])
    assert accept(db, row["url"], record, {}, 2) == "new"
    assert accept(db, row["url"], record, {}, 3) == "unchanged"
    changed = {**record, "body": record["body"] + " Neue Erkenntnisse."}
    assert accept(db, row["url"], changed, {}, 4) == "revised"
    stored = db.execute("SELECT source_id,revision,city_scope,scope_evidence FROM reports").fetchone()
    assert tuple(stored) == ("217132", 2, "outside_candidate", "In Leverkusen-Schlebusch")
    assert db.execute("SELECT count(*) FROM revisions").fetchone()[0] == 2
    db.close()


def test_native_archive_requires_valid_robots_rules(tmp_path, monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, text="<html>unavailable</html>")

    real_client = httpx.Client
    monkeypatch.setattr(
        cologne.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    with pytest.raises(ValueError, match="robots.txt"):
        sync(tmp_path / "cologne.sqlite", 2026, max_pages=1, limit=1)
    assert seen == ["/robots.txt"]
