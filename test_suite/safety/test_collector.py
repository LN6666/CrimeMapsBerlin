from crimemapsberlin.collector import accept, connect, discover, fail, listings, pages
from crimemapsberlin.feed import article_text

PAGE = """<li><div>20.09.2026 12:04 Uhr</div><a href="/polizei/polizeimeldungen/2026/pressemitteilung.123.php">A &amp; B</a><span><strong>Ereignisort: </strong>Mitte</span></li><a href="?page_at_1_0=22">22</a>"""


def test_archive_dedup_is_id_not_url():
    rows = listings(PAGE + PAGE.replace("/2026/", "/"))
    assert len(rows) == 1 and rows[0]["id"] == "123"
    assert rows[0]["title"] == "A & B"
    assert rows[0]["published"] == "2026-09-20T12:04:00"
    assert pages(PAGE) == 22


def test_revisions_and_failed_fetch_preserve_last_good(tmp_path):
    db = connect(tmp_path / "state.sqlite")
    discover(db, listings(PAGE), 1)
    body = "Nr. 42 Ein ausreichend langer Originaltext für den Test."
    assert accept(db, "123", body, {"etag": "one"}, 2) == "new"
    assert accept(db, "123", body, {}, 3) == "unchanged"
    assert accept(db, "123", body + " Korrektur.", {}, 4) == "revised"
    fail(db, "123", "503", 5)
    row = db.execute("SELECT * FROM reports").fetchone()
    assert row["body"] == body + " Korrektur." and row["revision"] == 2
    assert row["retry_after"] == 305 and row["failures"] == 1
    assert db.execute("SELECT count(*) FROM revisions").fetchone()[0] == 2
    db.close()
    reopened = connect(tmp_path / "state.sqlite")
    assert reopened.execute("SELECT revision FROM reports").fetchone()[0] == 2


def test_empty_listing_district_does_not_erase_cached_article_heading(tmp_path):
    db = connect(tmp_path / "state.sqlite")
    row = {**listings(PAGE)[0], "district": ""}
    discover(db, [row], 1)
    db.execute("UPDATE reports SET district='Wandsbek' WHERE id='123'")
    db.commit()
    discover(db, [row], 2)
    assert db.execute("SELECT district FROM reports WHERE id='123'").fetchone()[0] == "Wandsbek"


def test_markup_outside_article_never_geocoded():
    body = article_text(
        "<nav>Invalidstraße</nav>Nr. 42<br>Text am Bahnhof<!-- /Flex Text --><footer>Platz der Luftbrücke</footer>"
    )
    assert "Bahnhof" in body and "Invalidstraße" not in body and "Luftbrücke" not in body


def test_official_article_number_without_period():
    assert "Text" in article_text("<strong>Nr 1130</strong><br>Text am Bahnhof<!-- /Flex Text -->")


def test_official_non_numbered_body_is_anchored_to_article():
    page = '<nav>Wrong place</nav><p class="polizeimeldung">Date</p><!-- Flex Text --><p>Public event notice without a number.</p><!-- /Flex Text --><footer>Wrong HQ</footer>'
    body = article_text(page)
    assert "Public event" in body and "Wrong" not in body
