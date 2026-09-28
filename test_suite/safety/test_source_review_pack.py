import hashlib
import json
import sqlite3
import zipfile

import pytest

from crimemapsberlin.source_review_pack import build_pack, read_checkpoint


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def checkpoint(path, *, body="Synthetic complete source body.", stored_hash=None):
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE reports (
                id TEXT, url TEXT, title TEXT, published TEXT, body TEXT,
                sha256 TEXT, revision INTEGER, error TEXT
            );
            CREATE TABLE archive_cursor (
                year INTEGER, next_url TEXT, pages_scanned INTEGER,
                complete INTEGER, updated REAL
            );
            """
        )
        db.execute(
            "INSERT INTO reports VALUES (?,?,?,?,?,?,?,NULL)",
            (
                "source-1",
                "https://example.invalid/source-1",
                "Synthetic report",
                "2026-09-28T12:00:00+02:00",
                body,
                stored_hash if stored_hash is not None else digest(body),
                1,
            ),
        )
        db.execute(
            "INSERT INTO reports VALUES (?,?,?,?,NULL,NULL,?,NULL)",
            (
                "source-2",
                "https://example.invalid/source-2",
                "Pending synthetic report",
                "2026-09-27T12:00:00+02:00",
                0,
            ),
        )
        db.execute("INSERT INTO archive_cursor VALUES (2026,NULL,2,1,0)")


def test_pack_is_hash_bound_batched_and_local_only(tmp_path):
    db_path = tmp_path / "checkpoint.sqlite"
    checkpoint(db_path)

    zip_path, external_path, status_path = build_pack(
        city="test-city",
        db_path=db_path,
        channel="signed-official-distribution",
        output_dir=tmp_path / "out",
        batch_size=1,
    )

    assert zip_path.parent == tmp_path / "out"
    assert external_path.read_text().split()[0] == hashlib.sha256(zip_path.read_bytes()).hexdigest()
    assert "Verified bodies included: 1" in status_path.read_text()
    assert "Missing bodies: 1" in status_path.read_text()
    assert "Channel scan complete: True" in status_path.read_text()

    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        assert all(not name.startswith("/") and ".." not in name.split("/") for name in names)
        roots = {name.split("/", 1)[0] for name in names}
        assert len(roots) == 1
        root = roots.pop()
        manifest = json.loads(archive.read(f"{root}/MANIFEST.json"))
        assert manifest["city"] == "test-city"
        assert manifest["source_bodies"] == 1
        assert manifest["coverage"] == {
            "discovered": 2,
            "bodies_in_pack": 1,
            "missing_bodies": 1,
            "source_errors": 0,
            "channel_scan_complete": True,
        }
        assert manifest["publication_ready"] is False
        assert manifest["commit_to_git"] is False

        batch_name = f"{root}/batches/source-batch-0001.ndjson"
        decision = json.loads(archive.read(batch_name))
        assert decision["source_id"] == "source-1"
        assert decision["source_body"] == "Synthetic complete source body."
        assert decision["source_sha256"] == digest(decision["source_body"])
        assert decision["review_status"] == "pending"

        checksums = archive.read(f"{root}/CHECKSUMS.sha256").decode().splitlines()
        for line in checksums:
            expected, relative = line.split("  ", 1)
            assert hashlib.sha256(archive.read(f"{root}/{relative}")).hexdigest() == expected


@pytest.mark.parametrize(
    ("body", "stored_hash", "message"),
    [
        ("Synthetic complete source body.", "0" * 64, "hash mismatch"),
        ("   ", None, "body is empty"),
    ],
)
def test_checkpoint_tampering_or_empty_bodies_fail_closed(tmp_path, body, stored_hash, message):
    db_path = tmp_path / "checkpoint.sqlite"
    checkpoint(db_path, body=body, stored_hash=stored_hash)

    with pytest.raises(ValueError, match=message):
        read_checkpoint(db_path)


@pytest.mark.parametrize("city", ["Bremen", "../bremen", "b", "bremen_2026"])
def test_city_slug_cannot_escape_or_destabilize_pack_paths(tmp_path, city):
    db_path = tmp_path / "checkpoint.sqlite"
    checkpoint(db_path)

    with pytest.raises(ValueError, match="stable lowercase slug"):
        build_pack(
            city=city,
            db_path=db_path,
            channel="synthetic",
            output_dir=tmp_path / "out",
            batch_size=100,
        )
