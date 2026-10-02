"""Synthetic exact native type/line tests; no city data or police narratives."""

from copy import deepcopy

import pytest
from shapely.geometry import LineString, Point, box, shape

from crimemapsberlin.poi_cities import clip_features, geometry_covered_by
from crimemapsberlin.poi_context import context_kind_matches
from crimemapsberlin.poi_native_contexts import NATIVE_CONTEXT_RULES, native_context_kinds
from crimemapsberlin.spatial import associate, classify_poi, pois_from_osm

RULE_EXAMPLES = [
    (kind, {k: min(values) for k, values in conditions.items()})
    for kind, alternatives in NATIVE_CONTEXT_RULES.items()
    for conditions in alternatives
]


@pytest.mark.parametrize("kind,tags", RULE_EXAMPLES)
def test_each_native_rule_requires_its_literal_tag_evidence(kind, tags):
    assert kind in native_context_kinds(tags)
    assert context_kind_matches(kind, {"kind": "context", "osm_type_tags": tags})
    without_type = {"name": kind, "brand": kind, "operator": kind}
    assert kind not in native_context_kinds(without_type)
    assert not context_kind_matches(kind, {"kind": "context", "osm_type_tags": without_type})


@pytest.mark.parametrize(
    "kind,tags",
    [
        ("mosque", {"amenity": "place_of_worship"}),
        ("refugee_accommodation", {"amenity": "social_facility", "social_facility": "group_home"}),
        (
            "refugee_accommodation",
            {"amenity": "social_facility", "social_facility": "outreach", "social_facility:for": "refugee"},
        ),
        (
            "senior_residence",
            {"amenity": "social_facility", "social_facility": "day_care", "social_facility:for": "senior"},
        ),
        ("senior_residence", {"amenity": "social_facility", "social_facility": "nursing_home"}),
        ("secondary_school", {"amenity": "school"}),
        ("cigarette_vending_machine", {"amenity": "vending_machine"}),
        (
            "clothing_container",
            {"amenity": "recycling", "recycling_type": "centre", "recycling:clothes": "yes"},
        ),
        ("emergency_department", {"amenity": "hospital", "emergency": "yes"}),
        ("car_dealer_workshop", {"shop": "car_repair"}),
        ("car_dealer_workshop", {"shop": "car"}),
    ],
)
def test_client_group_or_specialised_function_is_never_inferred(kind, tags):
    assert kind not in native_context_kinds(dict(tags, name=kind))


def native_way(ident=1, tags=None):
    return {
        "type": "way",
        "id": ident,
        "tags": tags or {"railway": "platform", "public_transport": "platform", "train": "yes"},
        "geometry": [{"lon": 13.4, "lat": 52.5}, {"lon": 13.401, "lat": 52.5006}],
    }


def named_event(kind, feature):
    return {
        "id": "source-reviewed",
        "source_url": "https://example.org/official",
        "coordinates": None,
        "scene_locations": [
            {
                "scene_id": "source-reviewed:location:1",
                "role": "background",
                "primary_for_count": False,
                "geometry": feature["location_geometry"],
                "location_object_ids": [feature["properties"]["id"]],
                "poi_contexts": [
                    {
                        "kind": kind,
                        "scope": "named_object",
                        "radius_m": 0,
                        "evidence_quote": "Explicit source-reviewed stationary platform context.",
                    }
                ],
            }
        ],
    }


def test_opt_in_platform_line_is_exact_native_geometry_and_named_context_only():
    payload = {"elements": [native_way()]}
    legacy, _ = pois_from_osm(payload)
    assert legacy["features"] == []
    pois, rejected = pois_from_osm(payload, include_reviewed_contexts=True)
    assert rejected == {}
    platform = pois["features"][0]
    assert platform["properties"]["kind"] == "station"
    assert platform["properties"]["geometry_mode"] == "native_line_reference"
    assert platform["geometry"] == platform["location_geometry"]
    assert platform["geometry"]["type"] == "LineString"
    event = named_event("station", platform)
    links = associate([event], pois, include_legacy_links=False)
    assert len(links) == 1 and links[0]["mention_basis"] == "source_reviewed_context_only"
    assert links[0]["status"] == "context_named_object"
    assert len(associate([named_event("train_station", platform)], pois, include_legacy_links=False)) == 1
    assert associate([named_event("subway_station", platform)], pois, include_legacy_links=False) == []
    assert event["coordinates"] is None and not event["scene_locations"][0]["primary_for_count"]


def test_native_line_clip_preserves_dimension_and_outside_length_is_rejected():
    pois, _ = pois_from_osm({"elements": [native_way()]}, include_reviewed_contexts=True)
    border = box(13.39, 52.49, 13.4005, 52.51)
    assert not geometry_covered_by(border, shape(pois["features"][0]["geometry"]))
    retained, notes = clip_features(deepcopy(pois), border)
    assert notes == {"boundary_clipped": 1}
    assert retained[0]["geometry"]["type"] == "LineString"
    assert retained[0]["geometry"] == retained[0]["location_geometry"]
    assert geometry_covered_by(border, shape(retained[0]["geometry"]))
    assert shape(retained[0]["geometry"]).length < shape(pois["features"][0]["geometry"]).length


@pytest.mark.parametrize("has_in_city_native_vertex", [True, False])
def test_clipped_line_search_center_never_uses_uncovered_clipping_endpoint(has_in_city_native_vertex):
    item = native_way()
    item["geometry"] = [{"lon": 13.38, "lat": 52.5}, {"lon": 13.4 if has_in_city_native_vertex else 13.42, "lat": 52.5}]
    pois, _ = pois_from_osm({"elements": [item]}, include_reviewed_contexts=True)
    pois["features"][0]["properties"]["center"] = [13.38, 52.5]
    border = box(13.39, 52.49, 13.41, 52.51)
    retained, _ = clip_features(deepcopy(pois), border)
    assert len(retained) == 1
    center = retained[0]["properties"]["center"]
    assert center == [13.4, 52.5]
    assert border.covers(Point(center))
    assert retained[0]["geometry"] == retained[0]["location_geometry"]
    assert retained[0]["properties"]["geometry_mode"] == "native_line_reference"
    event = named_event("station", retained[0])
    assert event["coordinates"] is None
    assert not event["scene_locations"][0]["primary_for_count"]


def test_unknown_business_name_and_plain_building_do_not_create_typed_context_pois():
    assert (
        classify_poi(
            {"name": "Hospital mosque courthouse security company", "building": "yes"},
            include_reviewed_contexts=True,
        )
        is None
    )
    assert classify_poi({"amenity": "hospital"}) is None
    assert classify_poi({"amenity": "hospital"}, include_reviewed_contexts=True) == "context"
    assert native_context_kinds({"office": "abandoned"}) == set()
    assert geometry_covered_by(box(0, 0, 1, 1), LineString([(2, 2), (3, 3)])) is False
