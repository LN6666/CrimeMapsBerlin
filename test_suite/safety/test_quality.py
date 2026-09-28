from crimemapsberlin.quality import location_changes, publication_problems


def snapshot(fetched=3, pending=0, failed=0, months=None, generation="old"):
    return dict(
        generation=generation,
        coverage=dict(discovered=fetched + pending, fetched=fetched, pending=pending, failed=failed),
        months=months or {"2026-09": dict(count=fetched)},
    )


def audit(mapped=2, unlocated=1, generation="old"):
    return dict(mapped=mapped, unlocated=unlocated, generation=generation)


def test_new_publication_blocks_incomplete_source_and_bad_partition():
    assert publication_problems(snapshot(pending=1), audit(), None, None)
    assert publication_problems(snapshot(failed=1), audit(), None, None)
    assert publication_problems(snapshot(), audit(mapped=1), None, None)
    assert publication_problems(
        snapshot(months={"2026-09": dict(count=2)}), audit(), None, None
    )


def test_previous_good_map_survives_source_or_geocoder_regression():
    old, old_audit = snapshot(), audit()
    assert publication_problems(snapshot(fetched=2), audit(mapped=1), old, old_audit)
    assert publication_problems(
        snapshot(fetched=4, months={"2026-09": dict(count=2), "2026-10": dict(count=2)}),
        audit(mapped=3, unlocated=1),
        old,
        old_audit,
    )
    assert publication_problems(snapshot(), audit(mapped=1, unlocated=2), old, old_audit)


def test_additional_unlocated_report_is_visible_without_failing():
    old, old_audit = snapshot(), audit()
    new = snapshot(fetched=4, generation="new")
    assert publication_problems(new, audit(mapped=2, unlocated=2, generation="new"), old, old_audit) == []


def test_existing_report_location_changes_block_publish_without_affecting_new_reports():
    old = [dict(id="1", coordinates=[13.4, 52.5]), dict(id="2", coordinates=None)]
    new = [
        dict(id="1", coordinates=[13.42, 52.5]),
        dict(id="2", coordinates=[13.401, 52.5]),
        dict(id="3", coordinates=[13.41, 52.51]),
    ]
    changes = location_changes(old, new)
    assert {row["id"] for row in changes} == {"1", "2"}
    assert "location_moved" in {row["reason"] for row in changes}
    assert publication_problems(snapshot(), audit(), snapshot(), audit(), changes)
    assert publication_problems(snapshot(), audit(), snapshot(), audit(), changes,
                                owner_approved=True) == []
    assert location_changes(old, new[1:])[0]["reason"] == "missing_report"


def test_unreviewed_or_uncertain_reports_block_publication():
    counts = {"supported": 2, "pending": 1, "uncertain": 0, "needs_correction": 0}
    assert publication_problems(snapshot(), audit(), None, None, review_counts=counts)
    counts = {"supported": 3, "pending": 0, "uncertain": 0, "needs_correction": 0}
    assert publication_problems(snapshot(), audit(), None, None, review_counts=counts) == []
    assert publication_problems(snapshot(), audit(), None, None,
                                review_counts=counts, owner_approved=False)
    assert publication_problems(snapshot(), audit(), None, None,
                                review_counts=counts, owner_approved=True) == []
