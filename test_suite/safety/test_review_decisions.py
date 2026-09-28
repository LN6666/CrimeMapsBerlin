import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from crimemapsberlin.review_decisions import (
    current_supported_decisions,
    import_decisions,
    review_summary,
)

IDENT = "synthetic-source"
BODY = (
    "Am Nordmarkt wurde ein Mann beraubt. "
    "An der Münsterstraße beschädigte eine zweite Person ein Fahrzeug. "
    "Die Festnahme erfolgte später im Stadtteil Innenstadt-West."
)
QUOTE_ONE = "Am Nordmarkt wurde ein Mann beraubt."
QUOTE_TWO = "An der Münsterstraße beschädigte eine zweite Person ein Fahrzeug."
QUOTE_THREE = "Die Festnahme erfolgte später im Stadtteil Innenstadt-West."


def source_db(path, *, native_columns=False, ident=IDENT, url=None, body=BODY):
    url = url or f"https://example.invalid/report/{ident}"
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    if native_columns:
        db.execute(
            """CREATE TABLE reports(
                   source_id TEXT PRIMARY KEY,source_url TEXT NOT NULL,title TEXT NOT NULL,
                   published TEXT NOT NULL,body TEXT,sha256 TEXT,revision INTEGER,error TEXT
               )"""
        )
        db.execute(
            "INSERT INTO reports VALUES(?,?,?,?,?,?,?,NULL)",
            (
                ident,
                url,
                "Synthetische Meldung",
                "2026-09-29T12:00:00+02:00",
                body,
                hashlib.sha256(body.encode()).hexdigest(),
                1,
            ),
        )
    else:
        db.execute(
            """CREATE TABLE reports(
                   id TEXT PRIMARY KEY,url TEXT NOT NULL,title TEXT NOT NULL,
                   published TEXT NOT NULL,body TEXT,sha256 TEXT,revision INTEGER,error TEXT
               )"""
        )
        db.execute(
            "INSERT INTO reports VALUES(?,?,?,?,?,?,?,NULL)",
            (
                ident,
                url,
                "Synthetische Meldung",
                "2026-09-29T12:00:00+02:00",
                body,
                hashlib.sha256(body.encode()).hexdigest(),
                1,
            ),
        )
    db.commit()
    return db, url


def decision_files(tmp_path, *, city="berlin", ident=IDENT, url=None, body=BODY):
    url = url or f"https://example.invalid/report/{ident}"
    digest = hashlib.sha256(body.encode()).hexdigest()
    identity = {
        "schema_version": 1,
        "city": city,
        "source_id": ident,
        "source_url": url,
        "source_sha256": digest,
    }
    review = {
        **identity,
        "verdict": "supported",
        "evidence_quotes": [QUOTE_ONE],
        "review_note": "The full source was read and all explicit incidents were inventoried.",
        "reviewer": "source-first-llm-v1",
        "reviewed_at": "2026-09-29T12:30:00+02:00",
    }
    scope = {
        **identity,
        "scope_verdict": "in_city",
        "evidence_quotes": [QUOTE_ONE],
    }
    scenes = {
        "schema_version": 1,
        "city": city,
        "articles": [
            {
                **identity,
                "incident_count": 2,
                "incidents_complete": True,
                "formal_locations_complete": True,
                "incidents": [
                    {
                        "incident_id": f"{ident}:incident:1",
                        "evidence_quotes": [QUOTE_ONE],
                        "formal_location_ids": [f"{ident}:location:1"],
                    },
                    {
                        "incident_id": f"{ident}:incident:2",
                        "evidence_quotes": [QUOTE_TWO],
                        "formal_location_ids": [
                            f"{ident}:location:2",
                            f"{ident}:location:3",
                        ],
                    },
                ],
                "formal_locations": [
                    {
                        "location_id": f"{ident}:location:1",
                        "label": "Nordmarkt",
                        "role": "incident",
                        "precision": "place",
                        "city_scope": "in_city",
                        "evidence_quotes": [QUOTE_ONE],
                        "coordinates": [7.466, 51.518],
                    },
                    {
                        "location_id": f"{ident}:location:2",
                        "label": "Münsterstraße",
                        "role": "incident",
                        "precision": "street",
                        "city_scope": "in_city",
                        "evidence_quotes": [QUOTE_TWO],
                        "coordinates": None,
                    },
                    {
                        "location_id": f"{ident}:location:3",
                        "label": "Innenstadt-West",
                        "role": "arrest",
                        "precision": "district",
                        "city_scope": "in_city",
                        "evidence_quotes": [QUOTE_THREE],
                        "coordinates": None,
                    },
                ],
            }
        ],
    }
    review_path = tmp_path / "review-decisions.delta.ndjson"
    scope_path = tmp_path / "scope-decisions.delta.ndjson"
    scene_path = tmp_path / "scene-decisions.delta.json"

    def write():
        review_path.write_text(json.dumps(review, ensure_ascii=False) + "\n", encoding="utf-8")
        scope_path.write_text(json.dumps(scope, ensure_ascii=False) + "\n", encoding="utf-8")
        scene_path.write_text(json.dumps(scenes, ensure_ascii=False), encoding="utf-8")

    write()
    return review, scope, scenes, write, review_path, scope_path, scene_path


def db_path(db):
    return Path(db.execute("PRAGMA database_list").fetchone()[2])


def run_import(db, files, *, city="berlin", imported_at=3):
    *_, review_path, scope_path, scene_path = files
    return import_decisions(
        db_path=db_path(db),
        city=city,
        review_path=review_path,
        scope_path=scope_path,
        scene_path=scene_path,
        imported_at=imported_at,
    )


@pytest.mark.parametrize(
    ("city", "native_columns"),
    [("berlin", False), ("hamburg", False), ("cologne", True), ("frankfurt", False)],
)
def test_imports_each_city_schema_with_multiple_incidents_and_locations(
    tmp_path, city, native_columns
):
    db, url = source_db(tmp_path / "sources.sqlite", native_columns=native_columns)
    files = decision_files(tmp_path, city=city, url=url)
    result = run_import(db, files, city=city)
    assert result["validated"] == 1
    assert (result["inserted"], result["changed"], result["unchanged"]) == (1, 0, 0)
    assert result["review_counts"] == {
        "supported": 1,
        "needs_correction": 0,
        "uncertain": 0,
        "pending": 0,
        "stale": 0,
    }
    assert result["all_current_reviews_supported"] is True
    assert result["owner_approval_required"] is True
    assert result["owner_approved"] is False and result["publication_ready"] is False
    accepted = current_supported_decisions(db_path=db_path(db), city=city)
    assert len(accepted) == 1
    assert accepted[0]["scene_inventory"]["incident_count"] == 2
    assert len(accepted[0]["scene_inventory"]["formal_locations"]) == 3
    repeated = run_import(db, files, city=city, imported_at=4)
    assert (repeated["inserted"], repeated["changed"], repeated["unchanged"]) == (0, 0, 1)
    assert db.execute("SELECT count(*) FROM source_llm_review_history").fetchone()[0] == 1
    db.close()


def test_explicit_zero_incident_and_empty_location_inventory_is_allowed(tmp_path):
    db, url = source_db(tmp_path / "sources.sqlite")
    files = decision_files(tmp_path, url=url)
    _, scope, scenes, write, *_ = files
    scope["scope_verdict"] = "out_of_city"
    article = scenes["articles"][0]
    article["incident_count"] = 0
    article["incidents"] = []
    article["formal_locations"] = []
    write()
    result = run_import(db, files)
    assert result["review_counts"]["supported"] == 1
    decision = current_supported_decisions(db_path=db_path(db), city="berlin")[0]
    assert decision["scene_inventory"]["incidents"] == []
    assert decision["scene_inventory"]["formal_locations_complete"] is True
    db.close()


@pytest.mark.parametrize("component", ["review", "scope", "incident", "location"])
def test_every_semantic_level_requires_a_verbatim_full_text_quote(tmp_path, component):
    db, url = source_db(tmp_path / "sources.sqlite")
    files = decision_files(tmp_path, url=url)
    review, scope, scenes, write, *_ = files
    bad_quote = "This invented quotation does not occur anywhere in the official source."
    if component == "review":
        review["evidence_quotes"] = [bad_quote]
    elif component == "scope":
        scope["evidence_quotes"] = [bad_quote]
    elif component == "incident":
        scenes["articles"][0]["incidents"][0]["evidence_quotes"] = [bad_quote]
    else:
        scenes["articles"][0]["formal_locations"][0]["evidence_quotes"] = [bad_quote]
    write()
    with pytest.raises(ValueError, match="absent from the current source body"):
        run_import(db, files)
    assert "source_llm_review_decisions" not in {
        row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    db.close()


@pytest.mark.parametrize("failure", ["count", "completeness", "reference", "district_point"])
def test_structurally_incomplete_scene_inventories_are_rejected(tmp_path, failure):
    db, url = source_db(tmp_path / "sources.sqlite")
    files = decision_files(tmp_path, url=url)
    _, _, scenes, write, *_ = files
    article = scenes["articles"][0]
    if failure == "count":
        article["incident_count"] = 1
    elif failure == "completeness":
        article["formal_locations_complete"] = False
    elif failure == "reference":
        article["incidents"][0]["formal_location_ids"] = [f"{IDENT}:location:missing"]
    else:
        article["formal_locations"][2]["coordinates"] = [7.4, 51.5]
    write()
    with pytest.raises(ValueError):
        run_import(db, files)
    db.close()


@pytest.mark.parametrize("failure", ["city", "url", "hash", "set"])
def test_cross_file_or_source_identity_mismatches_are_rejected(tmp_path, failure):
    db, url = source_db(tmp_path / "sources.sqlite")
    files = decision_files(tmp_path, url=url)
    review, scope, scenes, write, *_ = files
    if failure == "city":
        review["city"] = "hamburg"
    elif failure == "url":
        scope["source_url"] = "https://unrelated.example/wrong"
    elif failure == "hash":
        scenes["articles"][0]["source_sha256"] = "0" * 64
    else:
        scope["source_id"] = "another-source"
    write()
    with pytest.raises(ValueError):
        run_import(db, files)
    db.close()


def test_source_revision_expires_old_decision_and_rejects_old_bundle(tmp_path):
    db, url = source_db(tmp_path / "sources.sqlite")
    files = decision_files(tmp_path, url=url)
    imported = run_import(db, files)
    old_digest = imported["decision_set_digest"]
    revised = BODY + " Der Bericht wurde nachträglich ergänzt."
    db.execute(
        "UPDATE reports SET body=?,sha256=? WHERE id=?",
        (revised, hashlib.sha256(revised.encode()).hexdigest(), IDENT),
    )
    db.commit()
    summary = review_summary(db_path=db_path(db), city="berlin")
    assert summary["review_counts"]["stale"] == 1
    assert summary["all_current_reviews_supported"] is False
    assert summary["decision_set_digest"] != old_digest
    assert current_supported_decisions(db_path=db_path(db), city="berlin") == []
    with pytest.raises(ValueError, match="stale"):
        run_import(db, files)
    db.close()


def test_changed_decision_changes_digest_and_preserves_runtime_history(tmp_path):
    db, url = source_db(tmp_path / "sources.sqlite")
    files = decision_files(tmp_path, url=url)
    first = run_import(db, files)
    review, _, _, write, *_ = files
    review["review_note"] = "A second full-text review changed the documented rationale."
    write()
    second = run_import(db, files, imported_at=5)
    assert second["changed"] == 1 and second["inserted"] == 0
    assert second["decision_set_digest"] != first["decision_set_digest"]
    assert second["owner_approved"] is False and second["publication_ready"] is False
    assert db.execute("SELECT count(*) FROM source_llm_review_history").fetchone()[0] == 2
    db.close()


def test_current_reader_revalidates_stored_semantics_even_if_digest_is_rewritten(tmp_path):
    db, url = source_db(tmp_path / "sources.sqlite")
    files = decision_files(tmp_path, url=url)
    run_import(db, files)
    row = db.execute(
        "SELECT decision_json FROM source_llm_review_decisions"
    ).fetchone()
    decision = json.loads(row[0])
    decision["review"]["evidence_quotes"] = [
        "This invented passage does not occur in the current official source."
    ]
    payload = json.dumps(
        decision, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    db.execute(
        "UPDATE source_llm_review_decisions SET decision_json=?,decision_sha256=?",
        (payload, hashlib.sha256(payload.encode()).hexdigest()),
    )
    db.commit()
    with pytest.raises(ValueError, match="absent from the current source body"):
        review_summary(db_path=db_path(db), city="berlin")
    db.close()


def test_missing_source_body_remains_pending_in_complete_checkpoint_summary(tmp_path):
    db, url = source_db(tmp_path / "sources.sqlite")
    db.execute(
        "INSERT INTO reports VALUES(?,?,?,?,NULL,NULL,0,NULL)",
        (
            "pending-source",
            "https://example.invalid/report/pending-source",
            "Noch nicht gespeicherte Meldung",
            "2026-09-28T12:00:00+02:00",
        ),
    )
    db.commit()
    result = run_import(db, decision_files(tmp_path, url=url))
    assert result["source_records"] == 2
    assert result["review_counts"]["supported"] == 1
    assert result["review_counts"]["pending"] == 1
    assert result["all_current_reviews_supported"] is False
    db.close()


def test_unified_ledger_does_not_overwrite_existing_scope_or_scene_storage(tmp_path):
    db, url = source_db(tmp_path / "sources.sqlite", native_columns=True)
    db.execute(
        """CREATE TABLE city_scope_decisions(
               source_id TEXT PRIMARY KEY,source_sha256 TEXT,verdict TEXT,
               evidence TEXT,reviewed REAL
           )"""
    )
    db.execute(
        "INSERT INTO city_scope_decisions VALUES(?,?,?,?,?)",
        (IDENT, "legacy-hash", "uncertain", "legacy evidence stays intact", 1),
    )
    db.commit()
    files = decision_files(tmp_path, city="cologne", url=url)
    _, scope, _, write, *paths = files
    scope["scope_verdict"] = "mixed"
    write()
    scene_before = paths[-1].read_bytes()
    result = run_import(db, files, city="cologne")
    assert result["review_counts"]["supported"] == 1
    assert db.execute("SELECT * FROM city_scope_decisions").fetchone()[2] == "uncertain"
    assert db.execute(
        "SELECT scope_verdict FROM source_llm_review_decisions"
    ).fetchone()[0] == "mixed"
    assert paths[-1].read_bytes() == scene_before
    assert "reviews" not in {
        row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    db.close()


def test_munich_is_rejected_before_opening_a_checkpoint(tmp_path):
    files = decision_files(tmp_path, city="munich")
    missing = tmp_path / "must-not-be-created.sqlite"
    *_, review_path, scope_path, scene_path = files
    with pytest.raises(ValueError, match="owner accepted POLIZEIKARTE upstream semantics"):
        import_decisions(
            db_path=missing,
            city="munich",
            review_path=review_path,
            scope_path=scope_path,
            scene_path=scene_path,
        )
    assert not missing.exists()


def test_unknown_reports_schema_fails_closed(tmp_path):
    db = sqlite3.connect(tmp_path / "sources.sqlite")
    db.row_factory = sqlite3.Row
    db.execute(
        """CREATE TABLE reports(
               key TEXT PRIMARY KEY,title TEXT,published TEXT,body TEXT,sha256 TEXT,
               revision INTEGER,error TEXT
           )"""
    )
    db.commit()
    files = decision_files(tmp_path)
    with pytest.raises(ValueError, match="unsupported schema"):
        run_import(db, files)
    db.close()
