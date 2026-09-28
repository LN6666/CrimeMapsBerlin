import httpx
import pytest

from crimemapsberlin.munich import (
    ARCHIVE_URL, ROBOTS_URL, connect, item_scope, parse_daily_document, robots_status,
    stage_document,
)


REPORT = """10.07.2026, Polizeipräsidium München
Inhalt:
1011. Körperverletzung – Ludwigsvorstadt-Isarvorstadt
1012. Einbruch – Laim
1013. Betrug – Unterhaching
1014. Zeugenaufruf – unbekannter Ort

* * *

### 1011. Körperverletzung – Ludwigsvorstadt-Isarvorstadt
Am Donnerstag, 09.07.2026, kam es in der Lindwurmstraße zu einem Streit.
Die weitere Ermittlung wird durch die Münchner Polizei geführt.

* * *

### 1012. Einbruch – Laim
Ein Fenster an einem Keller wurde gewaltsam geöffnet. Die Personen flüchteten.
Die Ermittlungen dauern an; der exakte Tatort ist noch nicht ermittelt.

* * *

### 1013. Betrug – Unterhaching
Eine Person übergab Geld im Landkreis München. Die Polizei ermittelt.
Eine Adresse der Person in München wäre kein Hinweis auf den Tatort.

* * *

### 1014. Zeugenaufruf – unbekannter Ort
Die Polizei sucht weitere Hinweise zu dem beschriebenen Vorfall.
Die Mitteilung nennt keinen bestätigten Tatort innerhalb der Stadt.
"""


def document(text=REPORT):
    return {
        "source_url": "https://www.polizei.bayern.de/aktuelles/pressemitteilungen/105609/index.html",
        "publisher": "Polizeipräsidium München",
        "published": "2026-07-10",
        "title": "Medieninformation der Polizei München vom 10.07.2026",
        "text": text,
    }


def test_split_daily_report_uses_body_sections_and_excludes_outside_place():
    source_id, items = parse_daily_document(document())
    assert source_id == "105609"
    assert [item["number"] for item in items] == [1011, 1012, 1013, 1014]
    assert [item["city_scope"] for item in items] == [
        "city_candidate", "city_candidate", "outside", "unverified",
    ]
    assert items[2]["locality"] == "Unterhaching"
    assert "1012." not in items[0]["body"]
    assert all("lat" not in item and "lon" not in item for item in items)


def test_scope_only_uses_exact_heading_locality():
    assert item_scope("Einbruch – Lehel") == ("Lehel", "city_candidate")
    assert item_scope("Einbruch – Planegg") == ("Planegg", "outside")
    assert item_scope("Einbruch – Nordwest") == ("Nordwest", "unverified")
    assert item_scope("Einbruch in München") == ("", "unverified")


@pytest.mark.parametrize("changed,reason", [
    ({"publisher": "Polizeipräsidium Oberbayern Süd"}, "Not a Polizeipräsidium München"),
    ({"source_url": "https://example.org/aktuelles/pressemitteilungen/105609/index.html"},
     "Unexpected Munich police article URL"),
    ({"published": "2026-07-11"}, "publication date differ"),
    ({"title": "Sondermeldung der Polizei München"}, "Not a Munich numbered daily report"),
])
def test_document_provenance_must_match_official_daily_report(changed, reason):
    payload = document()
    payload.update(changed)
    with pytest.raises(ValueError, match=reason):
        parse_daily_document(payload)


def test_parser_fails_closed_on_changed_structure_or_incomplete_sections():
    with pytest.raises(ValueError, match="Contents list does not match"):
        parse_daily_document(document(REPORT.replace("1013. Betrug – Unterhaching\n", "1015. Betrug – Unterhaching\n", 1)))
    with pytest.raises(ValueError, match="No numbered daily-report body headings"):
        parse_daily_document(document(REPORT.replace("### ", "")))
    with pytest.raises(ValueError, match="Duplicate item number"):
        parse_daily_document(document(REPORT.replace("Inhalt:\n", "").replace("### 1014.", "### 1013.")))
    with pytest.raises(ValueError, match="no complete body"):
        parse_daily_document(document(REPORT.replace(
            "Die Polizei sucht weitere Hinweise zu dem beschriebenen Vorfall.\n"
            "Die Mitteilung nennt keinen bestätigten Tatort innerhalb der Stadt.", "x"
        )))


def test_local_checkpoint_is_idempotent_and_revisions_reset_review(tmp_path):
    db = connect(tmp_path / "munich.sqlite")
    first = stage_document(db, document())
    assert first == {"source_id": "105609", "items": 4, "result": "new"}
    db.execute("UPDATE items SET review_status='supported' WHERE item_id='105609:1011'")
    db.commit()
    assert stage_document(db, document())["result"] == "unchanged"
    assert db.execute("SELECT review_status FROM items WHERE item_id='105609:1011'").fetchone()[0] == "supported"
    corrected = document(REPORT.replace("kam es in der Lindwurmstraße", "kam es am Sendlinger Tor"))
    assert stage_document(db, corrected)["result"] == "revised"
    assert db.execute("SELECT revision FROM articles").fetchone()[0] == 2
    assert db.execute("SELECT review_status FROM items WHERE item_id='105609:1011'").fetchone()[0] == "pending"
    assert db.execute("SELECT count(*) FROM items").fetchone()[0] == 4
    assert db.execute("SELECT count(*) FROM article_revisions").fetchone()[0] == 2
    with pytest.raises(ValueError, match="Contents list"):
        stage_document(db, document(REPORT.replace("1013. Betrug – Unterhaching\n", "9999. Betrug – Unterhaching\n", 1)))
    assert db.execute("SELECT revision FROM articles").fetchone()[0] == 2
    db.close()


def test_robots_probe_only_fetches_robots_and_blocks_articles():
    requested = []

    def responder(request):
        requested.append(str(request.url))
        return httpx.Response(200, text="User-agent: *\nDisallow: /\n")

    with httpx.Client(transport=httpx.MockTransport(responder)) as client:
        status = robots_status(client)
    assert requested == [ROBOTS_URL]
    assert status["archive_allowed"] is False
    assert status["article_allowed"] is False
    assert ARCHIVE_URL not in requested


def test_robots_probe_fails_closed_when_file_is_missing():
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, text=""))) as client:
        with pytest.raises(ValueError, match="robots.txt"):
            robots_status(client)
