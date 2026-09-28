import hashlib
import json
import sqlite3
import zipfile

import pytest

from crimemapsberlin.source_review_pack import build_pack, read_base_pack, read_checkpoint


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


def add_stored_report(path, ident="source-3", body="Another complete source body."):
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO reports VALUES (?,?,?,?,?,?,?,NULL)",
            (
                ident,
                f"https://example.invalid/{ident}",
                "Another synthetic report",
                "2026-09-29T12:00:00+02:00",
                body,
                digest(body),
                1,
            ),
        )


def rewrite_zip(source, target, transform):
    with zipfile.ZipFile(source) as archive:
        files = {info.filename: archive.read(info) for info in archive.infolist()}
    transform(files)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)


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
    assert "Verified bodies in checkpoint: 1" in status_path.read_text()
    assert "Bodies included in this pack: 1" in status_path.read_text()
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


def test_delta_pack_revalidates_base_and_contains_only_new_source_ids(tmp_path):
    base_db = tmp_path / "base.sqlite"
    checkpoint(base_db)
    base_zip, _, _ = build_pack(
        city="test-city",
        db_path=base_db,
        channel="signed-official-distribution",
        output_dir=tmp_path / "base",
        batch_size=100,
    )
    current_db = tmp_path / "current.sqlite"
    checkpoint(current_db)
    add_stored_report(current_db)

    delta_zip, _, status_path = build_pack(
        city="test-city",
        db_path=current_db,
        channel="signed-official-distribution",
        output_dir=tmp_path / "delta",
        batch_size=100,
        base_pack_path=base_zip,
    )

    expected_base_sha = hashlib.sha256(base_zip.read_bytes()).hexdigest()
    assert f"Base pack SHA-256: `{expected_base_sha}`" in status_path.read_text()
    with zipfile.ZipFile(delta_zip) as archive:
        root = archive.namelist()[0].split("/", 1)[0]
        manifest = json.loads(archive.read(f"{root}/MANIFEST.json"))
        assert manifest["delta_only"] is True
        assert manifest["base_pack"] == {
            "filename": base_zip.name,
            "sha256": expected_base_sha,
            "source_bodies": 1,
        }
        assert manifest["base_source_bodies"] == 1
        assert manifest["delta_source_bodies"] == 1
        assert manifest["combined_source_bodies"] == 2
        rows = []
        for relative in manifest["batch_files"]:
            rows.extend(json.loads(line) for line in archive.read(f"{root}/{relative}").splitlines())
        assert {row["source_id"] for row in rows} == {"source-3"}
        assert "source-1" not in {row["source_id"] for row in rows}


def test_delta_pack_rejects_changed_base_source(tmp_path):
    base_db = tmp_path / "base.sqlite"
    checkpoint(base_db)
    base_zip, _, _ = build_pack(
        city="test-city",
        db_path=base_db,
        channel="synthetic",
        output_dir=tmp_path / "base",
        batch_size=100,
    )
    current_db = tmp_path / "current.sqlite"
    checkpoint(current_db, body="Changed but internally valid source body.")
    add_stored_report(current_db)

    with pytest.raises(ValueError, match="missing or changed"):
        build_pack(
            city="test-city",
            db_path=current_db,
            channel="synthetic",
            output_dir=tmp_path / "delta",
            batch_size=100,
            base_pack_path=base_zip,
        )


def test_delta_pack_rejects_bad_adjacent_base_sidecar(tmp_path):
    base_db = tmp_path / "base.sqlite"
    checkpoint(base_db)
    base_zip, sidecar, _ = build_pack(
        city="test-city",
        db_path=base_db,
        channel="synthetic",
        output_dir=tmp_path / "base",
        batch_size=100,
    )
    sidecar.write_text(f"{'0' * 64}  {base_zip.name}\n")

    with pytest.raises(ValueError, match="does not match its sidecar"):
        read_base_pack(base_zip, city="test-city", channel="synthetic")


def test_delta_pack_accepts_explicit_sidecar_outside_pack_directory(tmp_path):
    base_db = tmp_path / "base.sqlite"
    checkpoint(base_db)
    base_zip, sidecar, _ = build_pack(
        city="test-city",
        db_path=base_db,
        channel="synthetic",
        output_dir=tmp_path / "base",
        batch_size=100,
    )
    detached_dir = tmp_path / "detached"
    detached_dir.mkdir()
    detached_zip = detached_dir / base_zip.name
    detached_zip.write_bytes(base_zip.read_bytes())

    base = read_base_pack(
        detached_zip,
        city="test-city",
        channel="synthetic",
        sidecar_path=sidecar,
    )
    assert base["source_bodies"] == 1
    assert base["sha256"] == hashlib.sha256(detached_zip.read_bytes()).hexdigest()


def test_base_pack_rejects_internal_checksum_tampering(tmp_path):
    db_path = tmp_path / "base.sqlite"
    checkpoint(db_path)
    base_zip, _, _ = build_pack(
        city="test-city",
        db_path=db_path,
        channel="synthetic",
        output_dir=tmp_path / "base",
        batch_size=100,
    )
    tampered = tmp_path / "tampered.zip"

    def alter_readme(files):
        name = next(name for name in files if name.endswith("/README.md"))
        files[name] += b"tampered"

    rewrite_zip(base_zip, tampered, alter_readme)
    with pytest.raises(ValueError, match="checksum mismatch"):
        read_base_pack(tampered, city="test-city", channel="synthetic")


def test_base_pack_rejects_body_hash_tampering_even_with_updated_checksums(tmp_path):
    db_path = tmp_path / "base.sqlite"
    checkpoint(db_path)
    base_zip, _, _ = build_pack(
        city="test-city",
        db_path=db_path,
        channel="synthetic",
        output_dir=tmp_path / "base",
        batch_size=100,
    )
    tampered = tmp_path / "tampered-body.zip"

    def alter_body_and_checksums(files):
        batch_name = next(name for name in files if "/batches/" in name)
        row = json.loads(files[batch_name])
        row["source_body"] = "Tampered source body with a stale source hash."
        files[batch_name] = (json.dumps(row, separators=(",", ":")) + "\n").encode()
        checksum_name = next(name for name in files if name.endswith("/CHECKSUMS.sha256"))
        root = checksum_name.removesuffix("CHECKSUMS.sha256")
        files[checksum_name] = "".join(
            f"{hashlib.sha256(data).hexdigest()}  {name.removeprefix(root)}\n"
            for name, data in sorted(files.items())
            if name != checksum_name
        ).encode()

    rewrite_zip(base_zip, tampered, alter_body_and_checksums)
    with pytest.raises(ValueError, match="invalid or duplicate source record"):
        read_base_pack(tampered, city="test-city", channel="synthetic")


@pytest.mark.parametrize(
    ("city", "channel"),
    [("other-city", "synthetic"), ("test-city", "other-channel")],
)
def test_base_pack_rejects_incompatible_city_or_channel(tmp_path, city, channel):
    db_path = tmp_path / "base.sqlite"
    checkpoint(db_path)
    base_zip, _, _ = build_pack(
        city="test-city",
        db_path=db_path,
        channel="synthetic",
        output_dir=tmp_path / "base",
        batch_size=100,
    )
    with pytest.raises(ValueError, match="city or source channel"):
        read_base_pack(base_zip, city=city, channel=channel)


def test_base_pack_rejects_path_traversal_members(tmp_path):
    db_path = tmp_path / "base.sqlite"
    checkpoint(db_path)
    base_zip, _, _ = build_pack(
        city="test-city",
        db_path=db_path,
        channel="synthetic",
        output_dir=tmp_path / "base",
        batch_size=100,
    )
    unsafe = tmp_path / "unsafe.zip"

    def add_unsafe_member(files):
        root = next(iter(files)).split("/", 1)[0]
        files[f"{root}/../escape.txt"] = b"unsafe"

    rewrite_zip(base_zip, unsafe, add_unsafe_member)
    with pytest.raises(ValueError, match="unsafe path"):
        read_base_pack(unsafe, city="test-city", channel="synthetic")
