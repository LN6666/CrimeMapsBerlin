import copy
import hashlib

import pytest

from crimemapsberlin.source_relation_draft import _digest, compile_relation_draft

CITY = "nuremberg"
QUOTE = "Die Polizei berichtet über den Vorfall am Marktplatz."
STAMP = "2026-09-30T19:00:00+00:00"


def inputs(count=3):
    sources, reviews, maps = [], [], []
    for sid in ["first", "second", "third"][:count]:
        body = f"Quellbericht {sid}. {QUOTE}"
        sha = hashlib.sha256(body.encode()).hexdigest()
        source = {
            "source_id": sid,
            "source_url": f"https://example.invalid/{sid}",
            "source_body": body,
            "source_sha256": sha,
        }
        identity = {
            "schema_version": 1,
            "city": CITY,
            "source_id": sid,
            "source_url": source["source_url"],
            "source_sha256": sha,
        }
        iid, lid = f"{sid}:incident:1", f"{sid}:location:1"
        decision = {
            **identity,
            "review": {
                "verdict": "supported",
                "evidence_quotes": [QUOTE],
                "review_note": "Synthetic full-body source review.",
                "reviewer": "LLM fixture",
                "reviewed_at": STAMP,
            },
            "scope": {"scope_verdict": "in_city", "evidence_quotes": [QUOTE]},
            "scene_inventory": {
                "incident_count": 1,
                "incidents_complete": True,
                "formal_locations_complete": True,
                "incidents": [{"incident_id": iid, "evidence_quotes": [QUOTE], "formal_location_ids": [lid]}],
                "formal_locations": [
                    {
                        "location_id": lid,
                        "label": "Marktplatz",
                        "role": "incident",
                        "precision": "place",
                        "city_scope": "in_city",
                        "coordinates": None,
                        "evidence_quotes": [QUOTE],
                    }
                ],
            },
        }
        review_sha = _digest(decision)
        sources.append(source)
        reviews.append({"source_id": sid, "decision": decision, "source_review_sha256": review_sha})
        maps.append(
            {
                "source_id": sid,
                "source_sha256": sha,
                "source_review_sha256": review_sha,
                "primary_count_incident_id": iid,
                "primary_count_location_id": lid,
            }
        )
    return {
        "city": CITY,
        "source_rows": sources,
        "source_reviews": reviews,
        "proposals": [],
        "map_decisions": maps,
    }


def add_relation(args, current, prior, treatment):
    sources = {x["source_id"]: x for x in args["source_rows"]}
    iid, old_iid = f"{current}:incident:1", f"{prior}:incident:1"
    proposal = {
        "schema_version": 1,
        "city": CITY,
        "relation_id": iid + "::" + old_iid,
        "source_id": current,
        "source_sha256": sources[current]["source_sha256"],
        "incident_id": iid,
        "prior_source_id": prior,
        "prior_source_sha256": sources[prior]["source_sha256"],
        "prior_incident_id": old_iid,
        "relation_type": "same_event",
        "evidence_quote": QUOTE,
        "compiled_into_final_map": False,
    }
    args["proposals"].append(proposal)
    return {
        "relation_id": proposal["relation_id"],
        "treatment": treatment,
        "preferred_source_id": None,
        "supersedes_fields": [],
        "review_note": "Explicit LLM fixture choice, unrelated to the old relation label.",
        "reviewer": "LLM fixture",
        "reviewed_at": STAMP,
    }


def envelope(args, decisions):
    source_set = [
        {
            "source_id": x["source_id"],
            "source_sha256": x["decision"]["source_sha256"],
            "decision_sha256": x["source_review_sha256"],
        }
        for x in sorted(args["source_reviews"], key=lambda x: x["source_id"])
    ]
    args["decision_envelope"] = {
        "schema_version": 1,
        "city": CITY,
        "source_decision_set_digest": _digest(source_set),
        "relation_set_sha256": _digest(args["proposals"]),
        "map_draft_sha256": _digest(args["map_decisions"]),
        "decisions": decisions,
    }
    return args


def test_transitive_same_occurrence_rejects_duplicate_selected_references():
    args = inputs()
    decisions = [
        add_relation(args, "second", "first", "same_occurrence"),
        add_relation(args, "third", "second", "same_occurrence"),
    ]
    args["map_decisions"][1].update(primary_count_incident_id=None, primary_count_location_id=None)
    with pytest.raises(ValueError, match="Duplicate selected occurrence"):
        compile_relation_draft(**envelope(args, decisions))


@pytest.mark.parametrize(
    "treatment",
    [
        "aggregate_context",
        "case_update",
        "distinct_phase",
        "tentative_connection",
        "cumulative_status",
        "planned_actual",
    ],
)
def test_context_labels_do_not_merge_distinct_events(treatment):
    args = inputs(2)
    choice = add_relation(args, "second", "first", treatment)
    result = compile_relation_draft(**envelope(args, [choice]))
    assert result["primary_reference_count"] == 2
    assert result["confirmed_occurrence_groups"] == []
    assert not result["publication_ready"] and not result["formal_map_compiled"]


def test_aggregate_does_not_join_two_old_occurrences_through_one_summary():
    args = inputs()
    choices = [
        add_relation(args, "third", "first", "aggregate_context"),
        add_relation(args, "third", "second", "aggregate_context"),
    ]
    args["map_decisions"][2].update(primary_count_incident_id=None, primary_count_location_id=None)
    result = compile_relation_draft(**envelope(args, choices))
    assert result["primary_reference_count"] == 2 and result["confirmed_occurrence_groups"] == []


@pytest.mark.parametrize(
    "failure", ["body", "review_digest", "proposal_quote", "proposal_scene", "map_binding", "missing_choice"]
)
def test_stale_or_unbound_inputs_block_the_draft(failure):
    args = inputs(2)
    choices = [add_relation(args, "second", "first", "case_update")]
    if failure == "body":
        args["source_rows"][0]["source_body"] += " New official revision."
    elif failure == "review_digest":
        args["source_reviews"][0]["source_review_sha256"] = "0" * 64
    elif failure == "proposal_quote":
        args["proposals"][0]["evidence_quote"] = "Diese Behauptung steht nicht im Originalbericht."
    elif failure == "proposal_scene":
        args["proposals"][0]["incident_id"] = "second:incident:99"
    elif failure == "map_binding":
        args["map_decisions"][0]["source_review_sha256"] = "0" * 64
    else:
        choices = []
    with pytest.raises(ValueError):
        compile_relation_draft(**envelope(args, choices))


def test_supersession_retains_both_original_sources_and_requires_explicit_preference():
    args = inputs(2)
    choice = add_relation(args, "second", "first", "same_occurrence")
    choice.update(preferred_source_id="second", supersedes_fields=["location"])
    args["map_decisions"][1].update(primary_count_incident_id=None, primary_count_location_id=None)
    before = copy.deepcopy(args)
    result = compile_relation_draft(**envelope(args, [choice]))
    assert args["source_reviews"] == before["source_reviews"]
    assert result["primary_reference_count"] == 1
    choice["preferred_source_id"] = None
    with pytest.raises(ValueError, match="Supersession"):
        compile_relation_draft(**envelope(args, [choice]))


def test_uncertain_source_stays_visible_in_draft_and_cannot_supply_a_count():
    args = inputs(2)
    row = args["source_reviews"][1]
    row["decision"]["review"]["verdict"] = "uncertain"
    row["source_review_sha256"] = _digest(row["decision"])
    args["map_decisions"][1]["source_review_sha256"] = row["source_review_sha256"]
    choice = add_relation(args, "second", "first", "tentative_connection")
    with pytest.raises(ValueError, match="unsupported"):
        compile_relation_draft(**envelope(args, [choice]))
    args["map_decisions"][1].update(primary_count_incident_id=None, primary_count_location_id=None)
    result = compile_relation_draft(**envelope(args, [choice]))
    assert not result["all_source_reviews_supported"]
    assert not result["owner_approved"] and not result["publication_ready"]
