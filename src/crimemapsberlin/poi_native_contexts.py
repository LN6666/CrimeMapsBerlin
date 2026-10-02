"""Explicit native tags for additional reviewed context types, never names.

Candidate-only opt-in selection keeps the public/other-city catalog unchanged.
Rules are alternatives of conjunctive literal tags; unspecified identity,
client group, motive, service or subtype is not supplied by a label/brand.
See OSM Map_features, Public_transport, Key:office and social_facility docs.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict


def _one(key: str, *values: str) -> tuple[dict, ...]:
    return ({key: frozenset(values)},)


def _all(**values: str) -> tuple[dict, ...]:
    return ({key: frozenset([value]) for key, value in values.items()},)


NATIVE_CONTEXT_RULES = {
    "atm": _one("amenity", "atm"),
    "bank": _one("amenity", "bank"),
    "bicycle_parking": _one("amenity", "bicycle_parking"),
    "brothel": _one("amenity", "brothel"),
    "car_rental": _one("amenity", "car_rental"),
    "casino": _one("amenity", "casino"),
    "clinic": _one("amenity", "clinic") + _one("healthcare", "clinic"),
    "college": _one("amenity", "college", "university"),
    "courthouse": _one("amenity", "courthouse"),
    "daycare": _one("amenity", "kindergarten"),
    "doctors": _one("amenity", "doctors") + _one("healthcare", "doctor"),
    "driving_school": _one("amenity", "driving_school"),
    "emergency_department": _one("healthcare", "emergency_ward"),
    "event_venue": _one("amenity", "events_venue", "conference_centre"),
    "fire_station": _one("amenity", "fire_station"),
    "fountain": _one("amenity", "fountain"),
    "fuel_station": _one("amenity", "fuel"),
    "hospital": _one("amenity", "hospital") + _one("healthcare", "hospital"),
    "institute": _one("amenity", "research_institute") + _one("office", "research"),
    "pharmacy": _one("amenity", "pharmacy"),
    "school": _one("amenity", "school"),
    "secondary_school": _all(amenity="school", **{"isced:level": "2"})
    + _all(amenity="school", **{"isced:level": "3"})
    + _all(amenity="school", **{"isced:level": "2;3"}),
    "place_of_worship": _one("amenity", "place_of_worship"),
    "police_station": _one("amenity", "police"),
    "public_toilet": _one("amenity", "toilets"),
    "social_facility": _one("amenity", "social_facility", "nursing_home"),
    "town_hall": _one("amenity", "townhall"),
    "vending_machine": _one("amenity", "vending_machine"),
    "bench": _one("amenity", "bench"),
    "memorial": _one("historic", "memorial", "monument"),
    "palace": _one("historic", "palace"),
    "planetarium": _one("amenity", "planetarium"),
    "hostel": _one("tourism", "hostel"),
    "cemetery": _one("landuse", "cemetery") + _one("amenity", "grave_yard"),
    "allotment_garden": _one("landuse", "allotments"),
    "residential_area": _one("landuse", "residential"),
    "residential_building": _one(
        "building", "residential", "apartments", "house", "detached", "terrace", "semidetached_house"
    ),
    "warehouse": _one("building", "warehouse"),
    "construction_site": _one("landuse", "construction") + _one("building", "construction"),
    "square": _one("place", "square"),
    "beach": _one("natural", "beach"),
    "green_space": _one("landuse", "grass", "village_green")
    + _one("leisure", "park", "garden")
    + _one("natural", "grassland"),
    "playground": _one("leisure", "playground"),
    "dog_park": _one("leisure", "dog_park"),
    "sports_facility": _one("leisure", "sports_centre", "sports_hall", "pitch", "stadium"),
    "sports_complex": _one("leisure", "sports_centre"),
    "sports_ground": _one("leisure", "pitch"),
    "sports_hall": _one("leisure", "sports_hall"),
    "stadium": _one("leisure", "stadium"),
    "swimming_pool": _one("leisure", "swimming_pool", "water_park"),
    "basketball_court": _all(leisure="pitch", sport="basketball"),
    "government_office": _one("office", "government"),
    "company": _one("office", "company"),
    "law_office": _one("office", "lawyer"),
    "political_office": _one("office", "political_party", "politician"),
    "constituency_office": _one("office", "politician"),
    "telecommunications_company": _one("office", "telecommunication"),
    "embassy": _all(office="diplomatic", diplomatic="embassy") + _one("amenity", "embassy"),
    "correctional_facility": _one("amenity", "prison"),
    "church": _all(amenity="place_of_worship", religion="christian"),
    "mosque": _all(amenity="place_of_worship", religion="muslim"),
    "synagogue": _all(amenity="place_of_worship", religion="jewish"),
    "clothing_container": _all(
        amenity="recycling", recycling_type="container", **{"recycling:clothes": "yes"}
    ),
    "cigarette_vending_machine": _all(amenity="vending_machine", vending="cigarettes"),
    "refugee_accommodation": _all(
        amenity="social_facility", social_facility="group_home", **{"social_facility:for": "refugee"}
    )
    + _all(amenity="social_facility", social_facility="shelter", **{"social_facility:for": "refugee"}),
    "homeless_shelter": _all(
        amenity="social_facility", social_facility="shelter", **{"social_facility:for": "homeless"}
    ),
    "care_facility": _one("amenity", "nursing_home")
    + _all(amenity="social_facility", social_facility="nursing_home")
    + _all(amenity="social_facility", social_facility="assisted_living"),
    "senior_residence": _all(
        amenity="social_facility", social_facility="group_home", **{"social_facility:for": "senior"}
    )
    + _all(amenity="social_facility", social_facility="nursing_home", **{"social_facility:for": "senior"})
    + _all(amenity="social_facility", social_facility="assisted_living", **{"social_facility:for": "senior"}),
    "youth_facility": _all(amenity="social_facility", **{"social_facility:for": "juvenile"}),
    "youth_club": _all(amenity="community_centre", **{"community_centre:for": "juvenile"}),
    "youth_welfare_facility": _all(
        amenity="social_facility", social_facility="group_home", **{"social_facility:for": "juvenile"}
    ),
    "building_entrance": _one("entrance", "yes", "main", "secondary", "service", "staircase", "home"),
    "pedestrian_crossing": _one("highway", "crossing") + _all(highway="footway", footway="crossing"),
    "bridge": _one("man_made", "bridge") + _one("bridge", "yes"),
    "tunnel": _one("tunnel", "yes"),
    "car_dealer_workshop": _all(shop="car", **{"service:vehicle:car_repair": "yes"})
    + _all(shop="caravan", **{"service:vehicle:car_repair": "yes"}),
}
NATIVE_CONTEXT_ALIASES = {
    "allotment": "allotment_garden",
    "allotments": "allotment_garden",
    "garden_colony": "allotment_garden",
    "arena": "stadium",
    "sports_stadium": "stadium",
    "court": "courthouse",
    "construction": "construction_site",
    "fuel": "fuel_station",
    "petrol_station": "fuel_station",
    "government": "government_office",
    "government_building": "government_office",
    "plaza": "square",
    "public_square": "square",
    "police": "police_station",
    "police_office": "police_station",
    "political_party_office": "political_office",
    "youth_hostel": "hostel",
}
for alias, canonical in NATIVE_CONTEXT_ALIASES.items():
    NATIVE_CONTEXT_RULES[alias] = NATIVE_CONTEXT_RULES[canonical]

# Exact tag lookup prevents every source node testing every predicate.
_RULE_LOOKUP = defaultdict(list)
for kind, alternatives in NATIVE_CONTEXT_RULES.items():
    for conditions in alternatives:
        first = next(iter(conditions))
        for value in conditions[first]:
            _RULE_LOOKUP[first, value].append((kind, conditions))
NATIVE_CONTEXT_TAG_KEYS = frozenset(
    key for alternatives in NATIVE_CONTEXT_RULES.values() for conditions in alternatives for key in conditions
)


def native_context_kinds(tags: dict) -> set[str]:
    result = set()
    for key, value in tags.items():
        if not isinstance(value, str):
            continue
        for kind, conditions in _RULE_LOOKUP.get((key, value), ()):
            if all(tags.get(k) in values for k, values in conditions.items()):
                result.add(kind)
    # Office existence is explicit; its subtype/organisation is never guessed.
    if isinstance(tags.get("office"), str) and tags["office"] not in {
        "",
        "no",
        "vacant",
        "closed",
        "abandoned",
        "demolished",
    }:
        result.add("office")
    return result


def native_platform(tags: dict) -> bool:
    return (
        tags.get("railway") == "platform"
        or tags.get("highway") == "platform"
        or tags.get("public_transport") == "platform"
    )


def native_context_line(tags: dict) -> bool:
    return (
        native_platform(tags)
        or tags.get("man_made") == "bridge"
        or tags.get("bridge") == "yes"
        or tags.get("tunnel") == "yes"
    )


def native_context_rule_digest() -> str:
    """Bind opt-in cache/contracts to this literal rule registry and policy."""
    value = {
        "selection_version": 1,
        "rules": {
            k: [{key: sorted(values) for key, values in c.items()} for c in alternatives]
            for k, alternatives in sorted(NATIVE_CONTEXT_RULES.items())
        },
        "generic_office_excluded_values": ["", "no", "vacant", "closed", "abandoned", "demolished"],
        "native_lines": ["platform", "bridge", "tunnel"],
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
