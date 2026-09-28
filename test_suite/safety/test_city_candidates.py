import json

from crimemapsberlin.collector import accept, connect, discover
from crimemapsberlin.city_candidates import stage


def test_hamburg_candidates_stay_local_and_wait_for_review(tmp_path):
    raw = tmp_path / "data/raw/safety/cities/hamburg"
    raw.mkdir(parents=True)
    (raw / "hamburg-pois.json").write_text('{"elements":[]}')
    (raw / "streets.json").write_text(json.dumps([{
        "name": "Teststraße", "geometry": {"type": "LineString", "coordinates": [
            [10.0, 53.55], [10.001, 53.55],
        ]},
    }]))
    (raw / "localities.json").write_text("[]")
    (raw / "addresses.json").write_text("[]")
    runtime = tmp_path / ".runtime/safety/cities/hamburg"
    runtime.mkdir(parents=True)
    db = connect(runtime / "police.sqlite")
    discover(db, [dict(
        id="123", url="https://www.presseportal.de/blaulicht/pm/6337/123",
        title="Überfall in Hamburg", published="2026-09-01T12:00:00", district="",
    )], 1)
    body = "Hamburg (ots) Tatort: Hamburg-Mitte, Teststraße Ein Mann wurde dort beraubt."
    accept(db, "123", body, {}, 2)
    db.close()

    audit = stage("hamburg", root=tmp_path)
    candidates = json.loads((runtime / "review-candidates.json").read_text())
    assert audit["coverage"] == dict(
        discovered=1, fetched=1, pending=0, failed=0,
        selected=1, outside=0, deferred=0,
    )
    assert audit["located"] == 1
    assert audit["review_counts"]["pending"] == 1
    assert audit["publication_ready"] is False
    assert candidates["city"] == "hamburg"
    assert candidates["events"][0]["source_sha256"]
    assert "body" not in candidates["events"][0]
    assert not (tmp_path / "web/public").exists()
