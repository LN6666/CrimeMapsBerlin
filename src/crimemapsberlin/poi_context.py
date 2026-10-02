"""Deterministic compatibility of reviewed context kinds with native OSM types.

Names, brands, distance and a report's category never select a venue type.
The existing display palette can group shops/stops, while matching keeps their
source subtypes. Missing tags/relations are an honest no-match, not a fallback.
"""

from __future__ import annotations

import hashlib
import json

from .poi_native_contexts import (
    NATIVE_CONTEXT_RULES,
    NATIVE_CONTEXT_TAG_KEYS,
    native_context_kinds,
    native_context_rule_digest,
    native_platform,
)

OSM_TYPE_KEYS = (
    "amenity",
    "shop",
    "tourism",
    "leisure",
    "railway",
    "building",
    "aeroway",
    "highway",
    "public_transport",
    "station",
    "subway",
    "bus",
    "tram",
    "train",
    *sorted(NATIVE_CONTEXT_TAG_KEYS),
)
HOSPITALITY_KINDS = {"bar", "nightclub", "restaurant", "cafe", "fast_food"}
MARKET_SHOPS = {"supermarket", "convenience"}
SHOP_CONTEXTS = {
    "auction_house": {"auction", "auction_house"},
    "car_dealer": {"car", "caravan"},
    "car_parts_shop": {"car_parts"},
    "convenience": {"convenience"},
    "convenience_store": {"convenience"},
    "late_night_shop": {"convenience"},
    "supermarket": {"supermarket"},
    "market": MARKET_SHOPS,
    "department_store": {"department_store"},
    "shopping_centre": {"mall"},
    "bakery": {"bakery"},
    "beverage_store": {"beverages"},
    "clothing_shop": {"clothes"},
    "fashion_store": {"clothes"},
    "electronics_store": {"electronics"},
    "florist": {"florist"},
    "flower_shop": {"florist"},
    "hairdresser": {"hairdresser"},
    "hair_salon": {"hairdresser"},
    "beauty_salon": {"beauty"},
    "nail_salon": {"beauty", "hairdresser"},
    "household_goods": {"houseware"},
    "jeweller": {"jewelry"},
    "jewellery_shop": {"jewelry"},
    "kiosk": {"kiosk"},
    "lottery_shop": {"lottery"},
    "pawnbroker": {"pawnbroker"},
}
DISPLAY_ALIASES = {
    "pub": {"bar"},
    "bistro": {"restaurant", "cafe"},
    "snack_bar": {"fast_food"},
    "grill_shop": {"fast_food"},
    "retail": {"shop"},
    "museum": {"attraction"},
}

# Broad source-reviewed groups retain the literal native subtype. They do not
# turn "Lokal" into a police finding that a pub, cafe, etc. hosted the event.
# Residential client groups are deliberately absent: communal accommodation
# does not imply refugee status, nationality, disability or a motive.
REVIEWED_BROAD_CONTEXT_RULES = {
    "pedestrian_zone": ({"highway": ("pedestrian",)},),
    "venue": ({"amenity": ("bar", "pub", "restaurant", "cafe", "fast_food", "nightclub")},),
    "landmark": (
        {"tourism": ("attraction",)},
        {"amenity": ("clock",)},
        {"historic": ("memorial", "monument")},
    ),
    "communal_accommodation": (
        {"amenity": ("social_facility",), "social_facility": ("group_home", "shelter")},
    ),
    "community_accommodation": (
        {"amenity": ("social_facility",), "social_facility": ("group_home", "shelter")},
    ),
    "security_company": ({"office": ("security",)},),
    "workshop": (
        {"shop": ("car_repair", "motorcycle_repair", "truck_repair")},
        {"amenity": ("workshop",)},
    ),
    # This frozen source context explicitly says Fast-Food-Lieferdienst.
    # Delivery by a general shop/restaurant, a name or brand is not enough.
    "food_delivery": ({"amenity": ("fast_food",), "delivery": ("yes", "only")},),
    "memorial_bench": (
        {"historic": ("memorial",), "memorial": ("bench",)},
        {"historic": ("memorial",), "amenity": ("bench",)},
    ),
}


def context_compatibility_digest() -> str:
    """Bind candidate generations to type-matching policy, not just POI geometry."""
    value = {
        "matching_policy_version": 10,
        "shop_contexts": {key: sorted(values) for key, values in sorted(SHOP_CONTEXTS.items())},
        "display_aliases": {key: sorted(values) for key, values in sorted(DISPLAY_ALIASES.items())},
        "hospitality_kinds": sorted(HOSPITALITY_KINDS),
        "reviewed_broad_context_rules": REVIEWED_BROAD_CONTEXT_RULES,
        "optional_native_context_metadata_keys": ["addr:street", "beauty", "delivery", "memorial"],
        "nail_salon_service_policy": "literal_nails_semicolon_token_with_shop_beauty_or_hairdresser_never_name_or_brand",
        "whole_street_address_policy": "source_bound_full_street_and_all_nearest_same_name_native_parts_v1",
        "street_spelling_policy": "explicit_literal_source_spellings_and_native_selected_road_names;no_automatic_alias_or_inflection_guess",
        "coarse_scope_policy": "district_geometry_is_not_a_venue_vicinity_without_separate_source_bound_identity",
        "context_geometry_policy": "original_native_geometry_not_display_circle;along_native_wgs_intersection;near_exact_reviewed_metric_radius",
        "explicit_named_place_identity_policy": "separate_source_hash_context_feature_bound_review_and_complete_literal_native_name;no_automatic_type_or_offence_inference",
        "native_reference_area_policy": "native_polygon_or_multipolygon_vertices;explicit_pedestrian_context_requires_literal_native_highway_pedestrian",
        "native_context_rule_digest": native_context_rule_digest(),
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def native_type_tags(tags: dict) -> dict:
    return {key: tags[key] for key in OSM_TYPE_KEYS if isinstance(tags.get(key), str)}


def _station(tags: dict) -> bool:
    return (
        tags.get("railway") in {"station", "halt"}
        or tags.get("building") == "train_station"
        or tags.get("amenity") == "bus_station"
    )


def context_kind_matches(kind: str, properties: dict) -> bool:
    """Type compatibility only; geometry and reviewed evidence are separate gates."""
    display_kind = properties.get("kind")
    tags = properties.get("osm_type_tags", {})
    if not isinstance(tags, dict):
        raise TypeError("Invalid native POI type metadata")
    metadata = properties.get("native_context_metadata", {}).get("tags", {})
    if (not isinstance(metadata, dict) or not set(metadata) <= {"delivery", "memorial", "addr:street", "beauty"}
            or set(metadata) & set(tags) or any(not isinstance(v, str) for v in metadata.values())):
        raise ValueError("Invalid projected literal native context metadata")
    tags = {**tags, **metadata}
    if kind == "nail_salon":
        # beauty=* documents semicolon-separated services, including nails;
        # an unspecified beauty shop or a nail-themed name is not evidence.
        return (
            display_kind == "shop" and tags.get("shop") in SHOP_CONTEXTS[kind]
            and "nails" in {value.strip() for value in tags.get("beauty", "").split(";")}
        )
    if kind in REVIEWED_BROAD_CONTEXT_RULES:
        return any(
            all(tags.get(key) in values for key, values in conditions.items())
            for conditions in REVIEWED_BROAD_CONTEXT_RULES[kind]
        )
    if kind in NATIVE_CONTEXT_RULES or kind == "office":
        return kind in native_context_kinds(tags)
    if kind in SHOP_CONTEXTS:
        return display_kind == "shop" and tags.get("shop") in SHOP_CONTEXTS[kind]
    if kind == "hospitality":
        return display_kind in HOSPITALITY_KINDS
    if kind == "market_parking":
        return False  # Requires a retained explicit site relation as well.
    if kind in {"station", "transit_station"}:
        # The source-reviewed generic group includes rail, bus and tram stops.
        # This display group never asserts a train/subway service or footprint.
        return display_kind == "station"
    if kind in {"subway_station", "train_station"}:
        if not tags:
            return False
        if not (_station(tags) or native_platform(tags)):
            return False
        if kind == "subway_station":
            return tags.get("station") == "subway" or tags.get("subway") == "yes"
        if kind == "train_station":
            return (
                (
                    tags.get("railway") in {"station", "halt"}
                    or (native_platform(tags) and tags.get("train") == "yes")
                )
                and tags.get("station") != "subway"
                and tags.get("subway") != "yes"
            )
        return display_kind == "station"
    if kind == "bus_station":
        return tags.get("amenity") == "bus_station"
    if kind == "bus_stop":
        return tags.get("highway") == "bus_stop" or (
            tags.get("public_transport") == "platform" and tags.get("bus") == "yes"
        )
    if kind == "tram_stop":
        return tags.get("railway") == "tram_stop" or (
            tags.get("public_transport") == "platform" and tags.get("tram") == "yes"
        )
    if kind == "transit_stop":
        return (
            _station(tags)
            or native_platform(tags)
            or context_kind_matches("bus_stop", properties)
            or context_kind_matches("tram_stop", properties)
        )
    if kind == "museum":
        return display_kind == "attraction" and tags.get("tourism") == "museum"
    if kind == "parking_garage":
        return display_kind == "parking" and tags.get("building") == "parking"
    if kind in DISPLAY_ALIASES:
        return display_kind in DISPLAY_ALIASES[kind]
    return display_kind == kind


def _market_site(tags: dict) -> bool:
    return tags.get("type") == "site" and (
        tags.get("site") in MARKET_SHOPS or tags.get("shop") in MARKET_SHOPS
    )


def attach_market_sites(features: list[dict], elements: list[dict]) -> None:
    """Bind parking only to explicit market-site co-members, never proximity/name."""
    by_object = {}
    for feature in features:
        props = feature["properties"]
        for ident in [props["id"], *props.get("osm_alias_object_ids", [])]:
            by_object[ident] = feature
    for relation in elements:
        tags = relation.get("tags", {})
        if relation.get("type") != "relation" or not _market_site(tags):
            continue
        members = {
            f"osm/{m['type']}/{m['ref']}"
            for m in relation.get("members", [])
            if m.get("type") in {"node", "way", "relation"} and type(m.get("ref")) is int
        }
        retained = {by_object[i]["properties"]["id"]: by_object[i] for i in members if i in by_object}
        markets = sorted(i for i, f in retained.items() if context_kind_matches("market", f["properties"]))
        if not markets:
            continue
        for feature in retained.values():
            props = feature["properties"]
            if props.get("kind") != "parking":
                continue
            props.setdefault("market_site_links", []).append(
                {
                    "relation_id": f"osm/relation/{relation['id']}",
                    "market_poi_ids": markets,
                    "source_member_ids": sorted(members),
                    "source_tags": {k: tags[k] for k in ("type", "site", "shop") if k in tags},
                }
            )
    for feature in features:
        props = feature["properties"]
        if "market_site_links" in props:
            props["market_site_links"].sort(key=lambda r: r["relation_id"])


def matches_reviewed_context(kind: str, properties: dict, by_id: dict) -> bool:
    if kind != "market_parking":
        return context_kind_matches(kind, properties)
    if properties.get("kind") != "parking":
        return False
    return any(
        _market_site(link.get("source_tags", {}))
        and any(
            i in by_id and context_kind_matches("market", by_id[i]["properties"])
            for i in link.get("market_poi_ids", [])
        )
        for link in properties.get("market_site_links", [])
    )
