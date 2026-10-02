"""Release failures must preserve the last good city manifest and generation."""

import dataclasses
import fcntl
import hashlib
import json
import shutil
import sqlite3

import pytest
from shapely.geometry import shape
from test_reviewed_city_map import _write_poi_product
from test_reviewed_scenes import BODY, _decision_files, _source_db

from crimemapsberlin import reviewed_city_release as release
from crimemapsberlin.city_geometry_index import write_geometry_index
from crimemapsberlin.geometry_decisions import compile_geometry_decisions
from crimemapsberlin.map_decisions import compile_map_decisions
from crimemapsberlin.review_decisions import import_decisions
from crimemapsberlin.reviewed_city_map import build_candidate
from crimemapsberlin.reviewed_scenes import build_inventory
from crimemapsberlin.source_review_pack import read_checkpoint


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")


@pytest.fixture
def checked_city(tmp_path):
    """Use the real source, GIS, map and POI validators with synthetic data."""
    db = tmp_path / "source.sqlite"
    digest = _source_db(db)
    decisions = _decision_files(tmp_path, digest)
    import_decisions(
        db_path=db, city="cologne", review_path=decisions[0], scope_path=decisions[1], scene_path=decisions[2]
    )
    inventory = build_inventory(city="cologne", db_path=db)
    inventory_path = tmp_path / "inventory.json"
    write(inventory_path, inventory)
    pbf = tmp_path / "synthetic.pbf"
    pbf.write_bytes(b"synthetic geometry source bytes; no network download")
    pbf_hash = hashlib.sha256(pbf.read_bytes()).hexdigest()
    catalog = tmp_path / "catalog.json"
    write(
        catalog,
        {
            "poi_types": {"park": {"label": "Park", "color": "green"}},
            "sources": [],
            "coverage": [],
            "exhaustive": False,
        },
    )
    poi = tmp_path / "poi"
    poi.mkdir()
    _write_poi_product(poi, catalog)
    for name, key in [
        ("boundary.geojson", "source_pbf_sha256"),
        ("poi-contract.json", "source_pbf_sha256"),
        ("validation.json", "source_sha256"),
    ]:
        value = json.loads((poi / name).read_text())
        value[key] = pbf_hash
        write(poi / name, value)
    contract = json.loads((poi / "poi-contract.json").read_text())
    contract["city"] = "cologne"
    write(poi / "poi-contract.json", contract)
    boundary = json.loads((poi / "boundary.geojson").read_text())
    border = shape(boundary["geometry"])
    index_path = tmp_path / "index.json"
    index = write_geometry_index(
        city="cologne",
        objects=[],
        border=border,
        boundary_metadata=boundary,
        source_metadata={"sha256": pbf_hash, "pbf_timestamp": "2026-09-28T00:00:00Z"},
        output=index_path,
    )
    # These explicit unknowns are valid precision limits, not fabricated points.
    geometry_rows = [
        {
            "schema_version": 1,
            "city": "cologne",
            "source_id": row["source_id"],
            "source_sha256": row["source_sha256"],
            "decision_sha256": row["decision_sha256"],
            "location_id": row["location_id"],
            "geometry_request_sha256": row["geometry_request_sha256"],
            "verdict": "unresolved",
            "method": "none",
            "osm_object_groups": [],
            "review_note": "Synthetic source has no verified native scene geometry; retain unknown.",
            "reviewer": "synthetic-test",
            "reviewed_at": "2026-09-29T13:00:00+02:00",
        }
        for row in inventory["geometry_requests"]
    ]
    geometry = compile_geometry_decisions(
        inventory=inventory,
        geometry_index=index,
        border=border,
        decision_envelope={
            "schema_version": 1,
            "city": "cologne",
            "inventory_digest": inventory["inventory_digest"],
            "geometry_index_sha256": index["index_sha256"],
            "decisions": geometry_rows,
        },
        include_footprint_count_points=False,
    )
    geometry_path = tmp_path / "geometry.json"
    write(geometry_path, geometry)
    article = inventory["articles"][0]
    decision = {
        "schema_version": 1,
        "city": "cologne",
        "source_id": "source-1",
        "source_sha256": digest,
        "source_review_sha256": article["decision_sha256"],
        "article_category": "raub",
        "is_crime_report": True,
        "classification_evidence_quotes": ["Am Nordmarkt wurde ein Mann beraubt."],
        "incident_categories": [
            {
                "incident_id": incident["incident_id"],
                "category": category,
                "evidence_quotes": incident["evidence_quotes"],
            }
            for incident, category in zip(article["incidents"], ["raub", "sonstige"])
        ],
        "primary_count_incident_id": None,
        "primary_count_location_id": None,
        "review_note": "No trustworthy count point; both synthetic source scenes are retained.",
        "reviewer": "synthetic-test",
        "reviewed_at": "2026-09-29T13:00:00+02:00",
    }
    rows, _ = read_checkpoint(db)
    maps = compile_map_decisions(
        city="cologne",
        source_rows=rows,
        inventory=inventory,
        geometry_ledger=geometry,
        decision_envelope={
            "schema_version": 1,
            "city": "cologne",
            "inventory_digest": inventory["inventory_digest"],
            "geometry_ledger_sha256": geometry["ledger_sha256"],
            "decisions": [decision],
        },
    )
    maps_path = tmp_path / "maps.json"
    write(maps_path, maps)
    candidate = tmp_path / "candidate"
    build_candidate(
        city="cologne",
        source_db=db,
        inventory_path=inventory_path,
        geometry_ledger_path=geometry_path,
        map_ledger_path=maps_path,
        poi_root=poi,
        catalog_path=catalog,
        output=candidate,
    )
    acceptance_path = tmp_path / "acceptance.json"
    inputs = release.ReleaseInputs(
        city="cologne",
        source_db=db,
        source_pbf_path=pbf,
        inventory_path=inventory_path,
        geometry_index_path=index_path,
        geometry_ledger_path=geometry_path,
        map_ledger_path=maps_path,
        poi_root=poi,
        catalog_path=catalog,
    )
    audit = json.loads((candidate / "build-audit.json").read_text())
    evidence = tmp_path / "synthetic-acceptance-evidence.json"
    write(evidence, {"synthetic_test_only": True, "not_owner_approval": True})
    write(
        acceptance_path,
        {
            "schema_version": 1,
            "city": inputs.city,
            "generation": audit["generation"],
            "candidate_digest": audit["candidate_digest"],
            "candidate_file_hashes": release.file_hashes(candidate),
            "input_bindings": inputs.bindings(),
            "checks": dict.fromkeys(release.ACCEPTANCE_CHECKS, True),
            "evidence": {
                key: [{"path": str(evidence), "sha256": release._sha(evidence)}]
                for key in release.ACCEPTANCE_CHECKS
            },
        },
    )
    return dataclasses.replace(inputs, acceptance_path=acceptance_path), candidate


def approval_for(packet):
    return {
        "schema_version": 1,
        "city": packet["city"],
        "packet_digest": packet["packet_digest"],
        "candidate_digest": packet["candidate_digest"],
        "approved": True,
        "approved_by": "synthetic owner fixture",
        "inspection_note": "Synthetic test only.",
        "approved_at": "2026-10-02T09:00:00+09:00",
        "accepted_scope": packet["scope"],
    }


def previous_publication(root):
    root.mkdir()
    write(root / "manifest.json", {"city": "Köln", "generation": "previous-good"})
    old = root / "previous-good"
    old.mkdir()
    (old / "month.json").write_text("previous valid bytes")
    return release.file_hashes(root)


def assert_previous(root, previous):
    current = release.file_hashes(root)
    assert all(current[path] == digest for path, digest in previous.items())


def test_real_chain_packet_and_atomic_promotion_retain_previous(checked_city, tmp_path):
    inputs, candidate = checked_city
    original = release.file_hashes(candidate)
    packet = release.prepare_packet(inputs=inputs, candidate=candidate)
    assert packet["technical_acceptance_current"] is True
    assert packet["scope"]["primary_count_points"] == 0
    assert packet["scope"]["unlocated_display_locations"] == 3
    assert packet["owner_approved"] is False
    output = tmp_path / "public"
    previous = previous_publication(output)
    receipt = release.promote_candidate(
        inputs=inputs, candidate=candidate, approval=approval_for(packet), output=output
    )
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["owner_approved"] is True and manifest["publication_ready"] is True
    assert manifest["publication_blocks"] == []
    assert receipt["public_manifest_sha256"] == release._sha(output / "manifest.json")
    assert release.file_hashes(output / manifest["generation"]) == receipt["generation_file_hashes"]
    assert (output / "previous-good/month.json").read_text() == "previous valid bytes"
    assert release.file_hashes(candidate) == original
    assert previous["previous-good/month.json"] == release._sha(output / "previous-good/month.json")


@pytest.mark.parametrize(
    "field,value",
    [
        ("packet_digest", "0" * 64),
        ("candidate_digest", "0" * 64),
        ("city", "hamburg"),
        ("approved", False),
        ("approved_by", ""),
        ("inspection_note", ""),
        ("approved_at", "2026-10-02T09:00:00"),
        ("accepted_scope", {}),
    ],
)
def test_invalid_owner_signoff_cannot_replace_publication(checked_city, tmp_path, field, value):
    inputs, candidate = checked_city
    approval = approval_for(release.prepare_packet(inputs=inputs, candidate=candidate))
    approval[field] = value
    output = tmp_path / "public"
    previous = previous_publication(output)
    with pytest.raises(ValueError):
        release.promote_candidate(inputs=inputs, candidate=candidate, approval=approval, output=output)
    assert_previous(output, previous)


@pytest.mark.parametrize("changed", ["source", "pbf", "tile", "month", "index", "acceptance_evidence"])
def test_changed_source_geometry_payload_or_evidence_blocks_old_approval(checked_city, tmp_path, changed):
    inputs, candidate = checked_city
    packet = release.prepare_packet(inputs=inputs, candidate=candidate)
    approval = approval_for(packet)
    if changed == "source":
        body = BODY + " New source revision."
        with sqlite3.connect(inputs.source_db) as db:
            db.execute(
                "UPDATE reports SET body=?,sha256=?", (body, hashlib.sha256(body.encode()).hexdigest())
            )
    else:
        paths = {
            "pbf": inputs.source_pbf_path,
            "tile": next((candidate / packet["generation"] / "pois").rglob("*.json")),
            "month": next((candidate / packet["generation"] / "months").glob("*.json")),
            "index": inputs.geometry_index_path,
            "acceptance_evidence": tmp_path / "synthetic-acceptance-evidence.json",
        }
        with paths[changed].open("ab") as stream:
            stream.write(b"\n ")
    output = tmp_path / "public"
    previous = previous_publication(output)
    with pytest.raises(ValueError):
        release.promote_candidate(inputs=inputs, candidate=candidate, approval=approval, output=output)
    assert_previous(output, previous)


@pytest.mark.parametrize("missing", ["acceptance", "browser_behaviour", "gap_disclosure", "evidence"])
def test_missing_acceptance_is_disclosed_and_blocks_promotion(checked_city, tmp_path, missing):
    inputs, candidate = checked_city
    if missing == "acceptance":
        inputs = dataclasses.replace(inputs, acceptance_path=None)
    else:
        acceptance = json.loads(inputs.acceptance_path.read_text())
        if missing == "evidence":
            acceptance["evidence"] = {}
        else:
            acceptance["checks"][missing] = False
        write(inputs.acceptance_path, acceptance)
    packet = release.prepare_packet(inputs=inputs, candidate=candidate)
    assert packet["technical_acceptance_current"] is False
    assert "current_candidate_technical_acceptance_missing" in packet["publication_blocks"]
    with pytest.raises(ValueError, match="Unresolved technical"):
        release.promote_candidate(
            inputs=inputs, candidate=candidate, approval=approval_for(packet), output=tmp_path / "public"
        )


def test_nonowner_block_and_conflicting_generation_are_not_overwritten(checked_city, tmp_path):
    inputs, candidate = checked_city
    packet = release.prepare_packet(inputs=inputs, candidate=candidate)
    blocked = {**packet, "publication_blocks": [*packet["publication_blocks"], "native_source_pending"]}
    with pytest.raises(ValueError, match="Unresolved technical"):
        release.validate_owner_approval(blocked, approval_for(blocked))
    output = tmp_path / "public"
    previous = previous_publication(output)
    conflict = output / packet["generation"]
    conflict.mkdir()
    (conflict / "foreign.json").write_text("never overwrite")
    with pytest.raises(ValueError, match="immutable generation"):
        release.promote_candidate(
            inputs=inputs, candidate=candidate, approval=approval_for(packet), output=output
        )
    assert_previous(output, previous)
    assert (conflict / "foreign.json").read_text() == "never overwrite"


def test_copy_failure_retains_previous_map(checked_city, tmp_path, monkeypatch):
    inputs, candidate = checked_city
    packet = release.prepare_packet(inputs=inputs, candidate=candidate)
    output = tmp_path / "public"
    previous = previous_publication(output)
    copytree = shutil.copytree

    def fail_on_release(source, target, *args, **kwargs):
        if ".city-release-" in str(target):
            raise OSError("Synthetic disk/copy failure")
        return copytree(source, target, *args, **kwargs)

    monkeypatch.setattr(shutil, "copytree", fail_on_release)
    with pytest.raises(OSError, match="disk/copy failure"):
        release.promote_candidate(
            inputs=inputs, candidate=candidate, approval=approval_for(packet), output=output
        )
    assert_previous(output, previous)


@pytest.mark.parametrize("failure", ["changed_input_after_copy", "manifest_switch_failure"])
def test_commit_point_failure_keeps_the_last_good_manifest(checked_city, tmp_path, monkeypatch, failure):
    inputs, candidate = checked_city
    packet = release.prepare_packet(inputs=inputs, candidate=candidate)
    output = tmp_path / "public"
    previous = previous_publication(output)
    if failure == "changed_input_after_copy":
        copytree = shutil.copytree

        def change_after_copy(source, target, *args, **kwargs):
            result = copytree(source, target, *args, **kwargs)
            if str(target).endswith(packet["generation"]) and ".city-release-" in str(target):
                with inputs.source_pbf_path.open("ab") as stream:
                    stream.write(b"changed after validation")
            return result

        monkeypatch.setattr(shutil, "copytree", change_after_copy)
        error, message = ValueError, "Inputs changed before publication"
    else:
        replace = release.os.replace

        def fail_manifest_switch(source, target):
            if target == output / "manifest.json":
                raise OSError("Synthetic final manifest switch failure")
            return replace(source, target)

        monkeypatch.setattr(release.os, "replace", fail_manifest_switch)
        error, message = OSError, "manifest switch failure"
    with pytest.raises(error, match=message):
        release.promote_candidate(
            inputs=inputs, candidate=candidate, approval=approval_for(packet), output=output
        )
    assert_previous(output, previous)


def test_symlink_crosscity_and_parallel_release_fail_closed(checked_city, tmp_path):
    inputs, candidate = checked_city
    packet = release.prepare_packet(inputs=inputs, candidate=candidate)
    alias = tmp_path / "alias"
    alias.symlink_to(candidate, target_is_directory=True)
    with pytest.raises(ValueError, match="Symbolic link"):
        release.prepare_packet(inputs=inputs, candidate=alias)
    with pytest.raises(ValueError, match="separate"):
        release.promote_candidate(
            inputs=inputs, candidate=candidate, approval=approval_for(packet), output=candidate / "public"
        )
    output = tmp_path / "public"
    output.mkdir()
    write(output / "manifest.json", {"city": "Hamburg"})
    before = release._sha(output / "manifest.json")
    with pytest.raises(ValueError, match="another city's"):
        release.promote_candidate(
            inputs=inputs, candidate=candidate, approval=approval_for(packet), output=output
        )
    assert release._sha(output / "manifest.json") == before
    write(output / "manifest.json", {"city": "Köln", "generation": "previous"})
    with (output / ".release.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="in progress"):
            release.promote_candidate(
                inputs=inputs, candidate=candidate, approval=approval_for(packet), output=output
            )
