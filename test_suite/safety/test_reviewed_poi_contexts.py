"""Synthetic native-type context tests; no police bodies or city data."""

from copy import deepcopy

import pytest
from shapely.geometry import LineString, Point, mapping
from shapely.ops import transform

from crimemapsberlin.poi_context import context_compatibility_digest, context_kind_matches
from crimemapsberlin.spatial import TO_METRIC, TO_WGS, associate, pois_from_osm

X, Y = TO_METRIC(13.4, 52.5)


def node(ident, tags, dx=0, dy=0):
    p = transform(TO_WGS, Point(X + dx, Y + dy))
    return {"type": "node", "id": ident, "lon": p.x, "lat": p.y, "tags": tags}


def report(kind, scope="along_geometry"):
    return {
        "id": "reviewed",
        "source_url": "https://example.org/official",
        "coordinates": None,
        "location_precision": "unknown",
        "poi_mentions": ["bar"],
        "mention_basis": "keyword",
        "scene_locations": [
            {
                "scene_id": "reviewed:location:1",
                "role": "incident",
                "primary_for_count": False,
                # Retain the exact native vertex; a projected straight segment can
                # miss an independently round-tripped point by floating-point noise.
                "geometry": mapping(transform(TO_WGS, LineString([(X - 100, Y), (X, Y), (X + 300, Y), (X + 400, Y)]))),
                "poi_contexts": [
                    {
                        "kind": kind,
                        "scope": scope,
                        "radius_m": 0,
                        "evidence_quote": "Explicit source-reviewed venue-type context.",
                    }
                ],
            }
        ],
    }


def links(kind, elements):
    pois, _ = pois_from_osm({"elements": elements})
    return associate([report(kind)], pois, include_legacy_links=False)


def test_display_circle_cannot_establish_along_street_context():
    pois, _ = pois_from_osm({"elements": [node(1, {"amenity": "pub"}, dy=25)]})
    assert pois["features"][0]["properties"]["geometry_mode"] == "50m_circle"
    assert associate([report("bar")], pois, include_legacy_links=False) == []


def test_along_context_has_no_implicit_numeric_or_display_buffer():
    pois, _ = pois_from_osm({"elements": [node(1, {"amenity": "pub"}, dy=0.01)]})
    assert associate([report("bar")], pois, include_legacy_links=False) == []


def test_display_radius_is_not_added_to_source_reviewed_near_radius():
    pois, _ = pois_from_osm({"elements": [
        node(1, {"amenity": "pub"}, dy=10),
        node(2, {"amenity": "pub"}, dy=45),
    ]})
    event = report("bar", scope="near_geometry")
    event["scene_locations"][0]["poi_contexts"][0]["radius_m"] = 20
    assert [link["poi_id"] for link in associate([event], pois, include_legacy_links=False)] == ["osm/node/1"]


def test_reviewed_circle_without_native_geometry_fails_instead_of_widening_scope():
    pois, _ = pois_from_osm({"elements": [node(1, {"amenity": "pub"})]})
    pois["features"][0].pop("location_geometry")
    with pytest.raises(ValueError, match="requires native geometry"):
        associate([report("bar")], pois, include_legacy_links=False)


def test_native_footprint_is_used_even_when_display_geometry_is_different():
    pois, _ = pois_from_osm({"elements": [node(1, {"amenity": "pub"}, dy=80)]})
    pois["features"][0]["location_geometry"] = mapping(transform(TO_WGS, Point(X, Y).buffer(10)))
    assert [link["poi_id"] for link in associate([report("bar")], pois, include_legacy_links=False)] == ["osm/node/1"]


@pytest.mark.parametrize(
    "kind,tags",
    [
        ("car_dealer", {"shop": "car"}),
        ("car_dealer", {"shop": "caravan"}),
        ("convenience", {"shop": "convenience"}),
        ("convenience_store", {"shop": "convenience"}),
        ("market", {"shop": "supermarket"}),
        ("supermarket", {"shop": "supermarket"}),
        ("shopping_centre", {"shop": "mall"}),
        ("bakery", {"shop": "bakery"}),
        ("pub", {"amenity": "pub"}),
        ("hospitality", {"amenity": "restaurant"}),
        ("venue", {"amenity": "pub"}),
        ("venue", {"amenity": "restaurant"}),
        ("landmark", {"tourism": "attraction", "amenity": "clock"}),
        ("snack_bar", {"amenity": "fast_food"}),
        ("bus_stop", {"highway": "bus_stop"}),
        ("tram_stop", {"railway": "tram_stop"}),
        ("station", {"highway": "bus_stop"}),
        ("station", {"railway": "tram_stop"}),
        ("subway_station", {"railway": "station", "station": "subway"}),
    ],
)
def test_reviewed_subtypes_match_native_types_without_changing_palette(kind, tags):
    found = links(kind, [node(1, tags)])
    assert len(found) == 1 and found[0]["poi_id"] == "osm/node/1"
    assert found[0]["mention_basis"] == "source_reviewed_context_only"
    assert found[0]["status"] == "context_along_geometry"


@pytest.mark.parametrize(
    "kind,tags",
    [
        ("car_dealer", {"shop": "car_repair"}),
        ("car_dealer", {"shop": "car_parts"}),
        ("convenience", {"shop": "supermarket"}),
        ("market", {"shop": "department_store"}),
        ("car_dealer_workshop", {"shop": "car"}),
        ("subway_station", {"railway": "station"}),
        ("train_station", {"highway": "bus_stop"}),
        ("train_station", {"railway": "tram_stop"}),
        ("museum", {"tourism": "attraction"}),
        ("venue", {"office": "company"}),
        ("landmark", {"place": "square"}),
        ("security_company", {"office": "company"}),
    ],
)
def test_subtypes_never_widen_to_unrelated_native_categories(kind, tags):
    assert links(kind, [node(1, dict(tags, name="Convenience car-dealer market station"))]) == []


def test_missing_shop_subtype_is_no_match_not_an_arbitrary_retail_fallback():
    assert context_kind_matches("convenience", {"kind": "shop"}) is False
    assert context_kind_matches("car_dealer", {"kind": "shop"}) is False
    assert context_kind_matches("shop", {"kind": "shop"}) is True


@pytest.mark.parametrize("kind", ["communal_accommodation", "community_accommodation"])
@pytest.mark.parametrize("population", ["refugee", "homeless", "juvenile", "mental_health", None])
def test_communal_context_requires_native_residential_use_never_population_inference(kind, population):
    tags = {"amenity": "social_facility", "social_facility": "group_home"}
    if population:
        tags["social_facility:for"] = population
    assert context_kind_matches(kind, {"kind": "context", "osm_type_tags": tags})
    tags["social_facility"] = "outreach"
    assert not context_kind_matches(kind, {"kind": "context", "osm_type_tags": tags})


def test_broad_contexts_never_infer_native_types_from_palette_name_or_brand():
    for kind in ["venue", "landmark", "communal_accommodation", "security_company"]:
        assert not context_kind_matches(kind, {
            "kind": "bar", "name": "World Clock security shelter", "brand": "Venue",
            "osm_type_tags": {},
        })
    assert context_kind_matches("security_company", {
        "kind": "context", "osm_type_tags": {"office": "security"},
    })


@pytest.mark.parametrize('kind,tags,expected', [
    ('workshop', {'shop': 'car_repair'}, True),
    ('workshop', {'shop': 'truck_repair'}, True),
    ('workshop', {'shop': 'motorcycle_repair'}, True),
    ('workshop', {'amenity': 'workshop'}, True),
    ('workshop', {'shop': 'car', 'name': 'Workshop repair'}, False),
    ('workshop', {'office': 'company'}, False),
    ('food_delivery', {'amenity': 'fast_food', 'delivery': 'yes'}, True),
    ('food_delivery', {'amenity': 'fast_food', 'delivery': 'only'}, True),
    ('food_delivery', {'amenity': 'fast_food', 'delivery': 'no'}, False),
    ('food_delivery', {'amenity': 'fast_food', 'delivery': 'Mo-Fr 08:00-12:00'}, False),
    ('food_delivery', {'amenity': 'fast_food', 'name': 'Delivery'}, False),
    ('food_delivery', {'amenity': 'restaurant', 'delivery': 'yes'}, False),
    ('food_delivery', {'shop': 'supermarket', 'delivery': 'yes'}, False),
    ('memorial_bench', {'historic': 'memorial', 'memorial': 'bench'}, True),
    ('memorial_bench', {'historic': 'memorial', 'amenity': 'bench'}, True),
    ('memorial_bench', {'amenity': 'bench', 'name': 'Memorial bench'}, False),
    ('memorial_bench', {'historic': 'memorial', 'memorial': 'statue'}, False),
])
def test_remaining_source_contexts_require_literal_specific_metadata(kind, tags, expected):
    native = {k: v for k, v in tags.items() if k not in {'delivery', 'memorial'}}
    extra = {k: v for k, v in tags.items() if k in {'delivery', 'memorial'}}
    properties = {'kind': 'context', 'osm_type_tags': native,
                  'native_context_metadata': {'tags': extra}}
    assert context_kind_matches(kind, properties) is expected


def test_native_context_metadata_cannot_override_type_or_infer_from_name():
    with pytest.raises(ValueError, match='projected literal'):
        context_kind_matches('food_delivery', {'osm_type_tags': {'amenity': 'restaurant'},
            'native_context_metadata': {'tags': {'amenity': 'fast_food'}}})


@pytest.mark.parametrize("shop,beauty,expected", [
    ("beauty", "nails", True),
    ("beauty", "nails;spa", True),
    ("hairdresser", "cosmetics; nails", True),
    ("beauty", "cosmetics", False),
    ("beauty", "nails_art", False),
    ("beauty", "", False),
    ("hairdresser", "", False),
    ("cosmetics", "nails", False),
])
def test_nail_salon_requires_literal_service_not_name(shop, beauty, expected):
    properties = {"kind": "shop", "name": "Nails", "brand": "Nails",
                  "osm_type_tags": {"shop": shop},
                  "native_context_metadata": {"tags": {"beauty": beauty}}}
    assert context_kind_matches("nail_salon", properties) is expected


@pytest.mark.parametrize("kind,tags,expected", [
    ("auction_house", {"shop": "auction"}, True),
    ("auction_house", {"shop": "auction_house"}, True),
    ("auction_house", {"shop": "antiques", "name": "Auction House"}, False),
    ("auction_house", {"shop": "art"}, False),
    ("pedestrian_zone", {"highway": "pedestrian"}, True),
    ("pedestrian_zone", {"highway": "footway", "name": "Pedestrian zone"}, False),
    ("pedestrian_zone", {"shop": "mall"}, False),
])
def test_auction_and_pedestrian_contexts_use_native_tags(kind, tags, expected):
    assert context_kind_matches(kind, {"kind": "shop", "osm_type_tags": tags}) is expected


def test_named_generic_venue_matches_only_its_reviewed_object_and_keeps_native_subtype():
    pois, _ = pois_from_osm({"elements": [node(1, {"amenity": "pub"}),
        node(2, {"amenity": "restaurant"})]})
    event = report("venue", scope="named_object")
    scene = event["scene_locations"][0]
    scene["location_object_ids"] = ["osm/node/1"]
    scene["poi_contexts"].append(deepcopy(scene["poi_contexts"][0]))
    found = associate([event], pois, include_legacy_links=False)
    assert [r["poi_id"] for r in found] == ["osm/node/1"]
    assert found[0]["status"] == "context_named_object"
    assert scene["poi_contexts"][0]["kind"] == "venue"
    assert pois["features"][0]["properties"]["osm_type_tags"]["amenity"] == "pub"


def test_compatibility_digest_changes_with_broad_rule_policy(monkeypatch):
    from crimemapsberlin import poi_context

    old = context_compatibility_digest()
    changed = {**poi_context.REVIEWED_BROAD_CONTEXT_RULES, "new_group": ({"amenity": ("clock",)},)}
    monkeypatch.setattr(poi_context, "REVIEWED_BROAD_CONTEXT_RULES", changed)
    assert context_compatibility_digest() != old


def test_near_station_uses_reviewed_radius_without_inventing_a_footprint():
    pois, _ = pois_from_osm(
        {
            "elements": [
                node(1, {"railway": "station"}, dy=30),
                node(2, {"railway": "station"}, dy=80),
            ]
        }
    )
    event = report("station", scope="near_geometry")
    event["scene_locations"][0]["poi_contexts"][0]["radius_m"] = 50
    found = associate([event], pois, include_legacy_links=False)
    assert [r["poi_id"] for r in found] == ["osm/node/1"]
    assert found[0]["status"] == "context_near_geometry"
    assert all(f["geometry"]["type"] == "Point" for f in pois["features"])
    assert all(f["properties"]["geometry_mode"] == "footprint_missing" for f in pois["features"])


def test_along_station_context_does_not_silently_become_a_nearby_search():
    assert links("station", [node(1, {"railway": "station"}, dy=30)]) == []


@pytest.mark.parametrize("scope", ["along_geometry", "near_geometry", "named_object"])
@pytest.mark.parametrize("role", ["incident", "discovery"])
def test_district_polygon_is_not_an_unknown_home_or_venue_vicinity(scope, role):
    pois, _ = pois_from_osm({"elements": [node(1, {"leisure": "park"})]})
    event = report("park", scope=scope)
    scene = event["scene_locations"][0]
    scene.update(location_precision="district", role=role,
                 geometry=mapping(transform(TO_WGS, Point(X, Y).buffer(1000))),
                 location_object_ids=["osm/node/1"])
    scene["poi_contexts"][0]["radius_m"] = 500 if scope == "near_geometry" else 0
    before = deepcopy(event)
    assert associate([event], pois, include_legacy_links=False) == []
    assert event == before and scene["primary_for_count"] is False


def site(ident=9, site_type="supermarket"):
    return {
        "type": "relation",
        "id": ident,
        "tags": {"type": "site", "site": site_type},
        "members": [{"type": "node", "ref": 1}, {"type": "node", "ref": 2}],
    }


def test_market_parking_needs_explicit_compatible_site_membership():
    elements = [
        node(1, {"shop": "supermarket", "name": "Shared name"}),
        node(2, {"amenity": "parking", "name": "Shared name"}),
    ]
    assert links("market_parking", elements) == []  # Co-location/name is not a relation.
    assert links("market_parking", [*elements, site(site_type="school")]) == []
    found = links("market_parking", [*elements, site()])
    assert [r["poi_id"] for r in found] == ["osm/node/2"]
    pois, rejected = pois_from_osm({"elements": [*elements, site()]})
    assert len(pois["features"]) == 2 and rejected == {}
    parking = next(f for f in pois["features"] if f["properties"]["kind"] == "parking")
    assert parking["properties"]["market_site_links"] == [
        {
            "relation_id": "osm/relation/9",
            "market_poi_ids": ["osm/node/1"],
            "source_member_ids": ["osm/node/1", "osm/node/2"],
            "source_tags": {"type": "site", "site": "supermarket"},
        }
    ]


def test_full_street_context_reaches_all_compatible_shops_with_report_cap():
    elements = [
        node(1, {"shop": "convenience"}),
        node(2, {"shop": "convenience"}, dx=300),
        node(3, {"shop": "convenience"}, dx=2000),
        node(4, {"shop": "clothes"}),
    ]
    pois, _ = pois_from_osm({"elements": elements})
    event = report("convenience")
    event["scene_locations"].append(deepcopy(event["scene_locations"][0]))
    found = associate([event], pois, include_legacy_links=False)
    assert {r["poi_id"] for r in found} == {"osm/node/1", "osm/node/2"}
    assert len(found) == 2  # Multiple phases never multiply one report at one POI.
    assert all(r["mention_basis"] != "keyword" for r in found)


def test_native_subtype_dedup_preserves_site_member_aliases():
    market = node(1, {"shop": "supermarket", "name": "Native market"})
    ring = [
        transform(TO_WGS, Point(X + dx, Y + dy))
        for dx, dy in [(-10, -10), (10, -10), (10, 10), (-10, 10), (-10, -10)]
    ]
    area = {
        "type": "way",
        "id": 3,
        "tags": market["tags"],
        "geometry": [{"lon": p.x, "lat": p.y} for p in ring],
    }
    pois, rejected = pois_from_osm({"elements": [market, area, node(2, {"amenity": "parking"}), site()]})
    assert rejected == {"duplicate_node_in_way": 1}
    found = associate([report("market_parking")], pois, include_legacy_links=False)
    assert [r["poi_id"] for r in found] == ["osm/node/2"]
    parking = next(f for f in pois["features"] if f["properties"]["kind"] == "parking")
    assert parking["properties"]["market_site_links"][0]["market_poi_ids"] == ["osm/way/3"]
    named = report("supermarket", scope="named_object")
    named["scene_locations"][0]["location_object_ids"] = ["osm/node/1", "osm/way/3"]
    found = associate([named], pois, include_legacy_links=False)
    assert [r["poi_id"] for r in found] == ["osm/way/3"]
    # Different native subtypes with the same name are not collapsed as one shop.
    market["tags"] = {"shop": "clothes", "name": "Native market"}
    different, _ = pois_from_osm({"elements": [market, area]})
    assert len(different["features"]) == 2


@pytest.mark.parametrize("tags", [{"shop": "vacant"}, {"shop": "no"}, {"disused:shop": "car"}])
def test_closed_or_disused_tags_do_not_create_active_shop_candidates(tags):
    pois, _ = pois_from_osm({"elements": [node(1, tags)]})
    assert pois["features"] == []
