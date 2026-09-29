import copy

import pytest

from crimemapsberlin.berlin_semantic_review import validate_article

BODY = (
    "Am Montag gegen 10 Uhr wurde ein Mann in der U-Bahnlinie U8 angegriffen. "
    "Die Fahrt verlief zwischen Alexanderplatz und Hermannplatz. "
    "Später wurde die Jacke in der Beispielstraße gefunden."
)


def decision():
    return {
        "schema_version": 1,
        "city": "berlin",
        "source_id": "1",
        "source_url": "https://example.invalid/1",
        "source_sha256": "a" * 64,
        "reviewer": "Codex source-first review",
        "reviewed_at": "2026-09-29T20:00:00+09:00",
        "source_read_complete": True,
        "six_rule_checks": {
            "discovery_role_checked": True,
            "moving_transit_checked": True,
            "all_independent_events_checked": True,
            "original_event_times_checked": True,
            "all_location_roles_checked": True,
            "poi_context_only_checked": True,
        },
        "announcement_kind": "single incident with later discovery",
        "event_relationship": "one attack and a later evidence discovery",
        "minimum_independent_events": 1,
        "incidents_complete": True,
        "formal_locations_complete": True,
        "event_times_complete": True,
        "transit_review_complete": True,
        "poi_context_review_complete": True,
        "incidents": [
            {
                "incident_id": "1:incident:1",
                "evidence_quotes": [
                    "Am Montag gegen 10 Uhr wurde ein Mann in der U-Bahnlinie U8 angegriffen."
                ],
                "formal_location_ids": ["1:location:1"],
                "details": "Attack in the moving U8 train.",
                "event_time_review": {
                    "status": "sourced",
                    "display": "Montag gegen 10 Uhr",
                    "date": None,
                    "precision": "approximate",
                    "evidence_quotes": [
                        "Am Montag gegen 10 Uhr wurde ein Mann in der U-Bahnlinie U8 angegriffen."
                    ],
                    "review_note": "The source gives weekday and approximate time only.",
                },
            }
        ],
        "formal_locations": [
            {
                "location_id": "1:location:1",
                "label": "U8 between Alexanderplatz and Hermannplatz",
                "role": "incident",
                "precision": "route",
                "city_scope": "in_city",
                "evidence_quotes": ["Die Fahrt verlief zwischen Alexanderplatz und Hermannplatz."],
                "details": "Moving-train incident, not pinned to either station.",
                "event_time_review": {
                    "status": "sourced",
                    "display": "Montag gegen 10 Uhr",
                    "date": None,
                    "precision": "approximate",
                    "evidence_quotes": [
                        "Am Montag gegen 10 Uhr wurde ein Mann in der U-Bahnlinie U8 angegriffen."
                    ],
                    "review_note": "The source gives weekday and approximate time only.",
                },
                "transit_review": {
                    "status": "reviewed_route",
                    "mode": "subway",
                    "line": "U8",
                    "extent": "source_segment",
                    "evidence_quotes": ["Die Fahrt verlief zwischen Alexanderplatz und Hermannplatz."],
                    "review_note": "Both segment endpoints are explicit.",
                },
                "poi_contexts": [
                    {
                        "kind": "station",
                        "scope": "near_geometry",
                        "radius_m": 100,
                        "evidence_quotes": ["Die Fahrt verlief zwischen Alexanderplatz und Hermannplatz."],
                        "review_note": "Stations are context, not offence venues.",
                    }
                ],
            },
            {
                "location_id": "1:location:2",
                "label": "Beispielstraße",
                "role": "discovery",
                "precision": "street",
                "city_scope": "in_city",
                "evidence_quotes": ["Später wurde die Jacke in der Beispielstraße gefunden."],
                "details": "Later discovery only, not the attack location.",
                "event_time_review": {
                    "status": "reviewed_unknown",
                    "display": "",
                    "date": None,
                    "precision": "unknown",
                    "evidence_quotes": ["Später wurde die Jacke in der Beispielstraße gefunden."],
                    "review_note": "Only the relative word later is present.",
                },
                "transit_review": {
                    "status": "not_applicable",
                    "mode": None,
                    "line": "",
                    "extent": None,
                    "evidence_quotes": ["Später wurde die Jacke in der Beispielstraße gefunden."],
                    "review_note": "No moving public transport at this location.",
                },
                "poi_contexts": [],
            },
        ],
        "linked_source_ids": [],
        "uncertainty": ["Calendar date is not present in the excerpt."],
    }


SOURCE = {
    "source_id": "1",
    "source_url": "https://example.invalid/1",
    "source_sha256": "a" * 64,
    "source_body": BODY,
}
AUDIT = {"minimum_independent_events": 1}


def test_validates_explicit_six_rule_review():
    result = validate_article(decision(), SOURCE, AUDIT)
    assert result["formal_locations"][0]["transit_review"]["line"] == "U8"
    assert result["formal_locations"][0]["poi_contexts"][0]["association"] == ("source_reviewed_context_only")


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("event_times_complete",), False),
        (("incidents", 0, "event_time_review"), None),
        (("formal_locations", 0, "transit_review", "status"), "not_applicable"),
        (("formal_locations", 0, "event_time_review"), None),
        (("formal_locations", 0, "poi_contexts"), None),
        (("six_rule_checks", "discovery_role_checked"), False),
    ],
)
def test_rejects_shortcuts(path, value):
    payload = decision()
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises((TypeError, ValueError)):
        validate_article(payload, SOURCE, AUDIT)


def test_rejects_missing_independent_event():
    payload = decision()
    payload["incidents"] = []
    with pytest.raises(ValueError, match="omits independent events"):
        validate_article(payload, SOURCE, AUDIT)


def test_reviewed_unknown_time_is_explicit_and_noninvented():
    payload = decision()
    time = payload["incidents"][0]["event_time_review"]
    time.update(
        {
            "status": "reviewed_unknown",
            "display": "",
            "date": None,
            "precision": "unknown",
            "review_note": "The current source body contains no calendar date.",
        }
    )
    assert (
        validate_article(payload, SOURCE, AUDIT)["incidents"][0]["event_time_review"]["status"]
        == "reviewed_unknown"
    )


def test_stale_source_hash_is_rejected():
    payload = copy.deepcopy(decision())
    payload["source_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="stale or mismatched"):
        validate_article(payload, SOURCE, AUDIT)


def test_non_transit_route_is_explicitly_distinguished():
    payload = decision()
    location = payload["formal_locations"][0]
    location["transit_review"].update(
        {
            "status": "reviewed_non_transit_route",
            "mode": None,
            "line": "",
            "extent": None,
            "review_note": "This is a march route, not public transport.",
        }
    )
    assert (
        validate_article(payload, SOURCE, AUDIT)["formal_locations"][0]["transit_review"]["status"]
        == "reviewed_non_transit_route"
    )
