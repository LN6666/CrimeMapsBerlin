import hashlib
import json
import sqlite3

from crimemapsberlin.review_decisions import import_decisions
from crimemapsberlin.reviewed_scenes import build_inventory

BODY = (
    "Am Nordmarkt wurde ein Mann beraubt. "
    "An der Münsterstraße beschädigte eine zweite Person ein Fahrzeug. "
    "Die Festnahme erfolgte später im Stadtteil Innenstadt-West."
)


def _source_db(path):
    digest = hashlib.sha256(BODY.encode()).hexdigest()
    with sqlite3.connect(path) as db:
        db.executescript(
            """CREATE TABLE reports(
                   source_id TEXT PRIMARY KEY,source_url TEXT NOT NULL,title TEXT NOT NULL,
                   published TEXT NOT NULL,body TEXT,sha256 TEXT,revision INTEGER,error TEXT);
               CREATE TABLE archive_scan(year INTEGER,complete INTEGER);"""
        )
        db.execute(
            "INSERT INTO reports VALUES(?,?,?,?,?,?,?,NULL)",
            (
                "source-1", "https://example.invalid/source-1", "Synthetic",
                "2026-09-29T12:00:00+02:00", BODY, digest, 1,
            ),
        )
        db.execute("INSERT INTO archive_scan VALUES(2026,1)")
    return digest


def _decision_files(root, digest):
    identity = {
        "schema_version": 1,
        "city": "cologne",
        "source_id": "source-1",
        "source_url": "https://example.invalid/source-1",
        "source_sha256": digest,
    }
    review = {
        **identity,
        "verdict": "supported",
        "evidence_quotes": ["Am Nordmarkt wurde ein Mann beraubt."],
        "review_note": "The complete source was read and every scene was inventoried.",
        "reviewer": "test-reviewer",
        "reviewed_at": "2026-09-29T12:30:00+02:00",
    }
    scope = {
        **identity,
        "scope_verdict": "in_city",
        "evidence_quotes": ["Am Nordmarkt wurde ein Mann beraubt."],
    }
    scenes = {
        "schema_version": 1,
        "city": "cologne",
        "articles": [{
            **identity,
            "incident_count": 2,
            "incidents_complete": True,
            "formal_locations_complete": True,
            "incidents": [
                {
                    "incident_id": "source-1:incident:1",
                    "evidence_quotes": ["Am Nordmarkt wurde ein Mann beraubt."],
                    "formal_location_ids": ["source-1:location:1"],
                },
                {
                    "incident_id": "source-1:incident:2",
                    "evidence_quotes": [
                        "An der Münsterstraße beschädigte eine zweite Person ein Fahrzeug."
                    ],
                    "formal_location_ids": [
                        "source-1:location:2", "source-1:location:3"
                    ],
                },
            ],
            "formal_locations": [
                {
                    "location_id": "source-1:location:1",
                    "label": "Nordmarkt",
                    "role": "incident",
                    "precision": "place",
                    "city_scope": "in_city",
                    "evidence_quotes": ["Am Nordmarkt wurde ein Mann beraubt."],
                    "coordinates": [6.78, 51.23],
                },
                {
                    "location_id": "source-1:location:2",
                    "label": "Münsterstraße",
                    "role": "incident",
                    "precision": "street",
                    "city_scope": "in_city",
                    "evidence_quotes": [
                        "An der Münsterstraße beschädigte eine zweite Person ein Fahrzeug."
                    ],
                    "coordinates": None,
                },
                {
                    "location_id": "source-1:location:3",
                    "label": "Innenstadt-West",
                    "role": "arrest",
                    "precision": "district",
                    "city_scope": "in_city",
                    "evidence_quotes": [
                        "Die Festnahme erfolgte später im Stadtteil Innenstadt-West."
                    ],
                    "coordinates": None,
                },
            ],
        }],
    }
    review_path = root / "review.ndjson"
    scope_path = root / "scope.ndjson"
    scene_path = root / "scenes.json"
    review_path.write_text(json.dumps(review, ensure_ascii=False) + "\n", encoding="utf-8")
    scope_path.write_text(json.dumps(scope, ensure_ascii=False) + "\n", encoding="utf-8")
    scene_path.write_text(json.dumps(scenes, ensure_ascii=False), encoding="utf-8")
    return review_path, scope_path, scene_path


def test_supported_decisions_become_explicit_geometry_work_without_publication(tmp_path):
    db_path = tmp_path / "sources.sqlite"
    digest = _source_db(db_path)
    review, scope, scenes = _decision_files(tmp_path, digest)
    import_decisions(
        db_path=db_path,
        city="cologne",
        review_path=review,
        scope_path=scope,
        scene_path=scenes,
        imported_at=1,
    )
    result = build_inventory(city="cologne", db_path=db_path)
    assert result["review_counts"]["supported"] == 1
    assert result["reviewed_incidents"] == 2
    assert result["reviewed_formal_locations"] == 3
    assert result["geometry_task_counts"] == {
        "checked_district_geometry_required": 1,
        "checked_road_geometry_required": 1,
        "review_point_requires_boundary_check": 1,
    }
    assert result["geometry_requests"][1]["incident_ids"] == ["source-1:incident:2"]
    assert result["geometry_requests"][1]["source_url"] == "https://example.invalid/source-1"
    assert result["geometry_requests"][1]["city_scope"] == "in_city"
    assert result["geometry_requests"][1]["evidence_quotes"] == [
        "An der Münsterstraße beschädigte eine zweite Person ein Fahrzeug."
    ]
    assert len(result["geometry_requests"][1]["geometry_request_sha256"]) == 64
    assert result["geometry_complete"] is False
    assert result["owner_approved"] is False
    assert result["publication_ready"] is False


def test_missing_or_stale_reviews_fail_closed_in_scene_inventory(tmp_path):
    db_path = tmp_path / "sources.sqlite"
    digest = _source_db(db_path)
    empty = build_inventory(city="cologne", db_path=db_path)
    assert empty["review_counts"]["pending"] == 1
    assert empty["articles"] == []
    assert empty["geometry_complete"] is False
    review, scope, scenes = _decision_files(tmp_path, digest)
    import_decisions(
        db_path=db_path,
        city="cologne",
        review_path=review,
        scope_path=scope,
        scene_path=scenes,
    )
    revised = BODY + " Ergänzung."
    with sqlite3.connect(db_path) as db:
        db.execute(
            "UPDATE reports SET body=?,sha256=? WHERE source_id='source-1'",
            (revised, hashlib.sha256(revised.encode()).hexdigest()),
        )
    stale = build_inventory(city="cologne", db_path=db_path)
    assert stale["review_counts"]["stale"] == 1
    assert stale["articles"] == []
    assert stale["publication_blocks"][0] == "source_review_incomplete"
