import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from crimemapsberlin.city_candidates import stage
from crimemapsberlin.city_contract import CITY_SPECS, paths_for
from crimemapsberlin.city_scope import record_city_scope
from crimemapsberlin.city_sources import frankfurt_scope, read_city_source
from crimemapsberlin.collector import accept as accept_standard
from crimemapsberlin.collector import connect as connect_standard
from crimemapsberlin.collector import discover as discover_standard
from crimemapsberlin.cologne import accept as accept_cologne
from crimemapsberlin.cologne import connect as connect_cologne
from crimemapsberlin.cologne import discover as discover_cologne


def osm_indexes(root, city):
    raw = paths_for(city, root).raw
    raw.mkdir(parents=True)
    (raw / f"{city}-pois.json").write_text('{"elements":[]}')
    (raw / "streets.json").write_text(json.dumps([{
        "name": "Teststraße", "geometry": {"type": "LineString", "coordinates": [
            [6.96, 50.94], [6.961, 50.94],
        ]},
    }]))
    (raw / "localities.json").write_text("[]")
    (raw / "addresses.json").write_text("[]")
    (raw / f"{city}-pois.source.json").write_text(json.dumps({
        "url": f"https://download.geofabrik.de/europe/germany/{city}-latest.osm.pbf",
        "sha256": "0" * 64,
        "license": "ODbL-1.0",
    }))


def test_first_group_paths_and_permissions_are_explicit(tmp_path):
    assert set(CITY_SPECS) == {"berlin", "hamburg", "cologne", "frankfurt", "munich"}
    assert CITY_SPECS["berlin"].epsg == 25833
    assert all(CITY_SPECS[city].epsg == 25832 for city in ("hamburg", "cologne", "frankfurt", "munich"))
    assert paths_for("berlin", tmp_path).raw == tmp_path / "data/raw/safety"
    assert paths_for("cologne", tmp_path).source_db == tmp_path / ".runtime/safety/cities/cologne/police.sqlite"
    assert paths_for("frankfurt", tmp_path).public == tmp_path / "web/public/safety/cities/frankfurt"
    assert CITY_SPECS["munich"].candidate_enabled
    assert not CITY_SPECS["cologne"].publication_enabled


@pytest.mark.parametrize(
    ("city", "publisher", "title", "body"),
    [
        (
            "hamburg",
            "6337",
            "POL-HH: Raub",
            "Tatort: Hamburg-Mitte, Teststraße. Ein Mann wurde beraubt.",
        ),
        (
            "frankfurt",
            "4970",
            "POL-F: Frankfurt - Gallus: Raub",
            "Tatort: Frankfurt-Gallus, Teststraße. Ein Mann wurde beraubt.",
        ),
    ],
)
def test_stale_pressportal_parser_version_blocks_city_candidates(
    tmp_path, city, publisher, title, body
):
    path = tmp_path / f"{city}.sqlite"
    db = connect_standard(path)
    db.execute("ALTER TABLE reports ADD COLUMN parser_version INTEGER NOT NULL DEFAULT 1")
    row = {
        "id": "123",
        "url": f"https://www.presseportal.de/blaulicht/pm/{publisher}/123",
        "title": title,
        "published": "2026-09-01T12:00:00",
        "district": "",
    }
    discover_standard(db, [row], 1)
    accept_standard(db, "123", body, {}, 2)
    db.close()

    stale = read_city_source(city, path)
    assert stale.coverage["fetched"] == 0
    assert stale.coverage["pending"] == 1
    assert not stale.reports

    db = connect_standard(path)
    db.execute("UPDATE reports SET parser_version=2")
    db.commit()
    db.close()
    still_stale = read_city_source(city, path)
    assert still_stale.coverage["fetched"] == 0
    assert still_stale.coverage["pending"] == 1
    assert not still_stale.reports

    db = connect_standard(path)
    db.execute("UPDATE reports SET parser_version=3")
    db.commit()
    db.close()
    current = read_city_source(city, path)
    assert current.coverage["fetched"] == 1
    if city == "frankfurt":
        assert current.coverage["selected"] == 0
        assert current.coverage["deferred"] == 1
        db = connect_standard(path)
        record_city_scope(db, "123", "in_city", body, 4)
        db.close()
        current = read_city_source(city, path)
    assert current.coverage["selected"] == 1


def test_cologne_native_schema_selects_only_city_leads(tmp_path, monkeypatch):
    osm_indexes(tmp_path, "cologne")
    path = paths_for("cologne", tmp_path).source_db
    db = connect_cologne(path)
    rows = [
        {"url": "https://koeln.polizei.nrw/presse/koeln-probe",
         "title": "Vorfall in Köln-Ehrenfeld", "published": "2026-09-01T12:00:00+02:00"},
        {"url": "https://koeln.polizei.nrw/presse/leverkusen-probe",
         "title": "Vorfall in Leverkusen", "published": "2026-09-02T12:00:00+02:00"},
    ]
    discover_cologne(db, rows, 1)
    accept_cologne(db, rows[0]["url"], {
        "source_id": "111", "source_url": rows[0]["url"],
        "body": "In Köln-Ehrenfeld auf der Teststraße wurde ein Fahrzeug gestohlen.",
    }, {}, 2)
    accept_cologne(db, rows[1]["url"], {
        "source_id": "222", "source_url": rows[1]["url"],
        "body": "In Leverkusen-Schlebusch wurde auf der Teststraße ein Fahrzeug gestohlen.",
    }, {}, 2)
    record_city_scope(
        db, "111", "in_city",
        "In Köln-Ehrenfeld auf der Teststraße wurde ein Fahrzeug gestohlen.", 3,
    )
    record_city_scope(
        db, "222", "out_of_city",
        "In Leverkusen-Schlebusch wurde auf der Teststraße ein Fahrzeug gestohlen.", 3,
    )
    db.close()

    selection = read_city_source("cologne", path)
    assert selection.coverage == {
        "discovered": 2, "fetched": 2, "pending": 0, "failed": 0,
        "selected": 1, "outside": 1, "deferred": 0,
    }
    assert [row["id"] for row in selection.reports] == ["111"]
    audit = stage("cologne", root=tmp_path)
    candidates = json.loads((paths_for("cologne", tmp_path).runtime / "review-candidates.json").read_text())
    assert audit["coverage"]["outside"] == 1
    assert [event["id"] for event in candidates["events"]] == ["111"]
    assert "body" not in candidates["events"][0]
    assert not paths_for("cologne", tmp_path).public.exists()
    spec = importlib.util.spec_from_file_location(
        "candidate_build", Path(__file__).resolve().parents[2] / "scripts/safety/build.py",
    )
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    monkeypatch.setattr(build, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["build.py", "--city", "cologne"])
    with pytest.raises(SystemExit, match="Publication blocked: cologne"):
        build.main()
    assert not paths_for("cologne", tmp_path).public.exists()
    monkeypatch.setitem(
        build.CITY_SPECS,
        "cologne",
        replace(build.CITY_SPECS["cologne"], publication_enabled=True),
    )
    with pytest.raises(SystemExit, match="Publication blocked: cologne"):
        build.main()
    assert not paths_for("cologne", tmp_path).public.exists()
    monkeypatch.setattr(sys, "argv", ["build.py", "--city", "cologne", "--db", "other.sqlite"])
    with pytest.raises(SystemExit, match="--db override"):
        build.main()


def test_frankfurt_newsroom_boilerplate_does_not_establish_city_scope(tmp_path):
    assert frankfurt_scope("POL-F: Bericht", "Frankfurt (ots) - Auf einer Autobahn kam es zum Unfall.") == "needs_review"
    assert frankfurt_scope("POL-F: Bericht", "Frankfurt (ots) - In Offenbach geschah ein Diebstahl.") == "needs_review"
    assert frankfurt_scope("POL-F: Bericht", "Frankfurt (ots) - In Frankfurt am Main geschah ein Diebstahl.") == "needs_review"
    assert frankfurt_scope(
        "POL-F: Festnahme",
        "Frankfurt (ots) - In Bad Vilbel geschah ein Raub. Der Täter wurde in Frankfurt festgenommen.",
    ) == "needs_review"
    assert frankfurt_scope(
        "POL-F: Festnahmen in Frankfurt am Main",
        "Frankfurt (ots) - Der Überfall ereignete sich in Kronberg.",
    ) == "needs_review"

    osm_indexes(tmp_path, "frankfurt")
    path = paths_for("frankfurt", tmp_path).source_db
    db = connect_standard(path)
    rows = [
        {"id": "333", "url": "https://www.presseportal.de/blaulicht/pm/4970/333",
         "title": "POL-F: Diebstahl", "published": "2026-09-01T12:00:00", "district": ""},
        {"id": "444", "url": "https://www.presseportal.de/blaulicht/pm/4970/444",
         "title": "POL-F: Unfall", "published": "2026-09-02T12:00:00", "district": ""},
    ]
    discover_standard(db, rows, 1)
    accept_standard(db, "333", "Frankfurt (ots) - In Frankfurt am Main auf der Teststraße wurde ein Fahrzeug gestohlen.", {}, 2)
    accept_standard(db, "444", "Frankfurt (ots) - In Offenbach geschah auf der Teststraße ein Verkehrsunfall.", {}, 2)
    record_city_scope(
        db, "333", "in_city",
        "Frankfurt (ots) - In Frankfurt am Main auf der Teststraße wurde ein Fahrzeug gestohlen.", 3,
    )
    record_city_scope(
        db, "444", "out_of_city",
        "Frankfurt (ots) - In Offenbach geschah auf der Teststraße ein Verkehrsunfall.", 3,
    )
    db.close()

    audit = stage("frankfurt", root=tmp_path)
    candidates = json.loads((paths_for("frankfurt", tmp_path).runtime / "review-candidates.json").read_text())
    assert audit["coverage"]["selected"] == 1
    assert audit["coverage"]["outside"] == 1
    assert audit["archive_complete"] is False
    assert [event["id"] for event in candidates["events"]] == ["333"]
    assert not paths_for("frankfurt", tmp_path).public.exists()


def test_first_group_llm_scope_decision_is_quote_and_hash_bound(tmp_path):
    path = tmp_path / "frankfurt.sqlite"
    db = connect_standard(path)
    row = {
        "id": "555", "url": "https://www.presseportal.de/blaulicht/pm/4970/555",
        "title": "POL-F: Probe", "published": "2026-09-03T12:00:00", "district": "",
    }
    body = "In Frankfurt am Main auf der Teststraße wurde ein Fahrzeug gestohlen."
    discover_standard(db, [row], 1)
    accept_standard(db, "555", body, {}, 2)
    with pytest.raises(ValueError, match="quote"):
        record_city_scope(
            db, "555", "in_city", "Diese erfundene Passage steht nicht im Bericht.", 3
        )
    record_city_scope(db, "555", "in_city", body, 3)
    db.close()
    assert read_city_source("frankfurt", path).coverage["selected"] == 1

    db = connect_standard(path)
    accept_standard(db, "555", body + " Neue Erkenntnisse.", {}, 4)
    db.close()
    stale = read_city_source("frankfurt", path)
    assert stale.coverage["selected"] == 0
    assert stale.coverage["deferred"] == 1


def test_munich_staging_requires_complete_direct_source_before_osm_access(tmp_path):
    with pytest.raises(ValueError, match="checkpoint is missing"):
        stage("munich", root=tmp_path)
    assert not (tmp_path / "web").exists()
