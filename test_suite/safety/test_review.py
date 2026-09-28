import hashlib

import pytest

from crimemapsberlin.review import (
    connect,
    fingerprint,
    owner_approved,
    record_owner_approval,
    record_reviews,
    review_packet,
    review_status,
    review_summary,
    reviewed_tags,
)


BODY = "Die Polizei meldet einen Überfall am Ostpreußenplatz in Hamburg-Wandsbek."


def event(**updates):
    return {
        "id": "6358440",
        "source_sha256": hashlib.sha256(BODY.encode()).hexdigest(),
        "source_url": "https://www.presseportal.de/blaulicht/pm/6337/6358440",
        "category": "Raub",
        "location_label": "Ostpreußenplatz",
        **updates,
    }


def decision(candidate, **updates):
    return {
        "id": candidate["id"],
        "source_sha256": candidate["source_sha256"],
        "extraction_sha256": fingerprint(candidate),
        "verdict": "supported",
        "evidence_quote": "einen Überfall am Ostpreußenplatz",
        "note": "The quoted incident scene and offence agree with the extracted fields.",
        "reviewer": "codex-review-v1",
        **updates,
    }


def test_review_tracks_both_source_and_extraction_versions(tmp_path):
    db = connect(tmp_path / "review.sqlite")
    first = event()
    assert review_summary(db, "hamburg", [first])["pending"] == 1
    assert record_reviews(db, "hamburg", [first], {first["id"]: BODY}, [decision(first)]) == 1
    assert review_status(db, "hamburg", first) == "supported"
    assert review_status(db, "berlin", first) == "pending"
    assert review_status(db, "hamburg", event(location_label="Wrongstraße")) == "pending"
    assert review_status(db, "hamburg", event(source_sha256="0" * 64)) == "pending"


def test_review_hashes_exact_stored_body_but_normalizes_quote_whitespace(tmp_path):
    db = connect(tmp_path / "review.sqlite")
    body = "Die Polizei meldet einen Überfall\nam Ostpreußenplatz in Hamburg-Wandsbek."
    candidate = event(source_sha256=hashlib.sha256(body.encode()).hexdigest())
    assert record_reviews(
        db,
        "cologne",
        [candidate],
        {candidate["id"]: body},
        [decision(candidate, evidence_quote="einen Überfall am Ostpreußenplatz")],
    ) == 1
    assert review_status(db, "cologne", candidate) == "supported"


def test_review_rejects_stale_or_unsupported_decisions_atomically(tmp_path):
    db = connect(tmp_path / "review.sqlite")
    first = event()
    with pytest.raises(ValueError, match="Stale"):
        record_reviews(
            db, "hamburg", [first], {first["id"]: BODY},
            [decision(first, extraction_sha256="0" * 64)],
        )
    with pytest.raises(ValueError, match="verbatim"):
        record_reviews(
            db, "hamburg", [first], {first["id"]: BODY},
            [decision(first, evidence_quote="invented location quote")],
        )
    with pytest.raises(ValueError, match="Source changed"):
        record_reviews(db, "hamburg", [first], {first["id"]: BODY + " Correction"}, [decision(first)])
    assert review_status(db, "hamburg", first) == "pending"


def test_possible_hate_crime_tag_requires_source_quote_and_motive_basis(tmp_path):
    db = connect(tmp_path / "review.sqlite")
    body = BODY + " Die Polizei ermittelt wegen eines möglichen homophoben Hintergrunds."
    candidate = event(source_sha256=hashlib.sha256(body.encode()).hexdigest())
    tag = {
        "tag": "possible_hate_crime",
        "basis": "police_motive_suspected",
        "evidence_quote": "eines möglichen homophoben Hintergrunds",
    }
    with pytest.raises(ValueError, match="basis"):
        record_reviews(
            db, "hamburg", [candidate], {candidate["id"]: body},
            [decision(candidate, tags=[{**tag, "basis": "victim_identity"}])],
        )
    record_reviews(
        db, "hamburg", [candidate], {candidate["id"]: body},
        [decision(candidate, tags=[tag])],
    )
    assert reviewed_tags(db, "hamburg", candidate) == [tag]


def test_owner_approval_requires_inspected_current_decisions(tmp_path):
    db = connect(tmp_path / "review.sqlite")
    first = event()
    with pytest.raises(ValueError, match="Every current announcement"):
        review_packet(db, "hamburg", [first])
    record_reviews(db, "hamburg", [first], {first["id"]: BODY}, [decision(first)])
    packet = review_packet(db, "hamburg", [first])
    assert packet["count"] == 1
    assert packet["items"][0]["source_url"] == first["source_url"]
    assert not owner_approved(db, "hamburg", [first])
    approval = dict(city="hamburg", decision_digest=packet["decision_digest"],
                    approved_by="owner", note="Reviewed source evidence and questioned the mapping")
    with pytest.raises(ValueError, match="stale"):
        record_owner_approval(db, "hamburg", [first],
                              {**approval, "decision_digest": "0" * 64})
    record_owner_approval(db, "hamburg", [first], approval)
    assert owner_approved(db, "hamburg", [first])
    assert not owner_approved(db, "hamburg", [event(location_label="Wrongstraße")])
    move = [{"id": first["id"], "reason": "location_moved", "distance_m": 200}]
    moved_packet = review_packet(db, "hamburg", [first], move)
    assert moved_packet["changed_locations"] == move
    assert moved_packet["decision_digest"] == packet["decision_digest"]
    assert owner_approved(db, "hamburg", [first], move)
    record_reviews(db, "hamburg", [first], {first["id"]: BODY},
                   [decision(first, note="Further challenge changed the review")])
    assert not owner_approved(db, "hamburg", [first])
