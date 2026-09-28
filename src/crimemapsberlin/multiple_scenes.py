"""Validate source-first LLM scene decisions.

Narrative meaning is not inferred here. Reviewed decisions are checked against
the exact source text, hashes, allowed roles and defensible WGS84 geometry.
"""

from copy import deepcopy
import math

from shapely.geometry import shape

SCENE_DECISION_VERSION = 1
SCENE_ROLES = {
    "incident", "accident", "discovery", "operation", "arrest", "search",
    "background", "unknown",
}
SCENE_PRECISIONS = {"point", "street", "place", "address", "area", "district", "unknown"}
CASE_RELATIONS = {
    "independent_case", "same_case_phase", "search_arrest_operation", "background_reference",
    "unresolved_relation",
}
REVIEWED_CATEGORIES = {
    "Betrug", "Betäubungsmittel", "Diebstahl", "Eigentumsdelikt", "Gewalt",
    "Raub", "Sachbeschädigung", "Sexualdelikt", "Unklassifiziert",
    "Verkehr / sonstige Meldung", "Waffendelikt",
}

def _valid_lonlat(value):
    return (
        isinstance(value, (list, tuple))
        and len(value) >= 2
        and all(type(number) in {int, float} and math.isfinite(number) for number in value[:2])
        and -180 <= value[0] <= 180
        and -90 < value[1] < 90
    )


def _validate_reviewed_geometry(scene, ident):
    coordinates = scene.get("coordinates")
    geometry_value = scene.get("geometry")
    road_value = scene.get("candidate_road_geometry")
    if coordinates is not None and not _valid_lonlat(coordinates):
        raise ValueError(f"Invalid scene coordinates for {ident}")
    for value, field in ((geometry_value, "geometry"), (road_value, "road geometry")):
        if value is None:
            continue
        if not isinstance(value, dict):
            raise ValueError(f"Invalid scene {field} for {ident}")
        try:
            parsed = shape(value)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid scene {field} for {ident}") from exc
        if parsed.is_empty or not parsed.is_valid:
            raise ValueError(f"Invalid scene {field} for {ident}")
        min_x, min_y, max_x, max_y = parsed.bounds
        if not (-180 <= min_x <= max_x <= 180 and -90 < min_y <= max_y < 90):
            raise ValueError(f"Out-of-range scene {field} for {ident}")
    precision = scene["location_precision"]
    if road_value is not None and (
        road_value.get("type") not in {"LineString", "MultiLineString"}
        or precision != "street" or coordinates is not None or geometry_value is not None
    ):
        raise ValueError(f"Invalid scene road semantics for {ident}")
    if precision in {"area", "district"} and (
        geometry_value is None
        or geometry_value.get("type") not in {"Polygon", "MultiPolygon"}
        or coordinates is not None or road_value is not None
    ):
        raise ValueError(f"Invalid scene area semantics for {ident}")
    if geometry_value is not None and geometry_value.get("type") == "Point":
        point = geometry_value.get("coordinates")
        if not _valid_lonlat(point) or coordinates is None or list(point[:2]) != list(coordinates[:2]):
            raise ValueError(f"Scene point differs from coordinates for {ident}")
    if precision == "unknown" and (coordinates is not None or geometry_value is not None or road_value is not None):
        raise ValueError(f"Unknown scene has geometry for {ident}")


def scene_decision_index(payload, *, city=None):
    """Validate the envelope for local, source-backed semantic scene reviews."""
    if not isinstance(payload, dict) or payload.get("version") != SCENE_DECISION_VERSION:
        raise ValueError("Unsupported scene decision file")
    if city is not None and payload.get("city") != city:
        raise ValueError("Scene decisions belong to another city")
    articles = payload.get("articles")
    if not isinstance(articles, list):
        raise ValueError("Scene decisions need an article list")
    indexed = {}
    for article in articles:
        if not isinstance(article, dict) or not str(article.get("id", "")):
            raise ValueError("Invalid scene decision article")
        ident = str(article["id"])
        if ident in indexed:
            raise ValueError(f"Duplicate scene decision article: {ident}")
        indexed[ident] = article
    return indexed


def validated_article_semantics(row, decision, source_hashes=None):
    """Validate optional human-reviewed article semantics without inferring them."""
    ident = str(row["id"])
    result = {}
    classification = decision.get("classification")
    followup = decision.get("followup")
    if classification is None and followup is None:
        return result
    try:
        title = row["title"]
    except (KeyError, IndexError):
        title = ""
    haystack = " ".join(f"{title} {row['body']}".split())
    if classification is not None:
        if not isinstance(classification, dict):
            raise ValueError(f"Invalid reviewed classification for {ident}")
        category = classification.get("category")
        crime = classification.get("is_crime_report")
        evidence = " ".join(str(classification.get("evidence_quote", "")).split())
        if (
            category not in REVIEWED_CATEGORIES
            or type(crime) is not bool
            or len(evidence) < 15
            or evidence not in haystack
        ):
            raise ValueError(f"Invalid reviewed classification for {ident}")
        result.update(category=category, is_crime_report=crime)
    if followup is not None:
        if not isinstance(followup, dict):
            raise ValueError(f"Invalid reviewed followup for {ident}")
        source_id = str(followup.get("source_id", ""))
        supplied_hash = followup.get("source_sha256")
        evidence = " ".join(str(followup.get("evidence_quote", "")).split())
        expected_hash = (source_hashes or {}).get(source_id)
        if (
            not source_id
            or source_id == ident
            or expected_hash is None
            or supplied_hash != expected_hash
            or len(evidence) < 15
            or evidence not in haystack
        ):
            raise ValueError(f"Invalid reviewed followup for {ident}")
        result["followup_of_source_id"] = source_id
    return result


def validated_scene_decision(row, decision, source_hashes=None):
    """Bind an LLM-reviewed scene list to the exact official source revision."""
    ident = str(row["id"])
    if str(decision.get("id")) != ident or decision.get("source_sha256") != row["sha256"]:
        raise ValueError(f"Stale scene decision for {ident}")
    validated_article_semantics(row, decision, source_hashes)
    scenes = decision.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ValueError(f"Scene decision has no scenes for {ident}")
    reviewed = deepcopy(scenes)
    body = " ".join(str(row["body"]).split())
    seen = set()
    primaries = 0
    for scene in reviewed:
        if not isinstance(scene, dict):
            raise ValueError(f"Invalid scene decision for {ident}")
        scene_id = str(scene.get("scene_id", ""))
        quote = " ".join(str(scene.get("evidence_quote", "")).split())
        if not scene_id.startswith(ident + ":") or scene_id in seen:
            raise ValueError(f"Invalid or duplicate scene ID for {ident}")
        seen.add(scene_id)
        if scene.get("role") not in SCENE_ROLES:
            raise ValueError(f"Invalid scene role for {ident}")
        if scene.get("location_precision") not in SCENE_PRECISIONS:
            raise ValueError(f"Invalid scene precision for {ident}")
        relation = scene.get("case_relation")
        if relation not in CASE_RELATIONS:
            raise ValueError(f"Invalid scene case relation for {ident}")
        minimum = scene.get("minimum_incidents")
        if relation == "independent_case":
            if type(minimum) is not int or minimum < 1:
                raise ValueError(f"Missing independent incident count for {ident}")
        elif minimum is not None:
            raise ValueError(f"Non-independent scene has incident count for {ident}")
        if not isinstance(scene.get("label"), str) or not scene["label"].strip():
            raise ValueError(f"Missing scene label for {ident}")
        if not isinstance(scene.get("geocode_method"), str):
            raise ValueError(f"Missing scene method for {ident}")
        if type(scene.get("primary_for_count")) is not bool:
            raise ValueError(f"Missing primary marker for {ident}")
        if len(quote) < 15 or quote not in body:
            raise ValueError(f"Scene evidence is absent from source for {ident}")
        scene["evidence_quote"] = quote
        _validate_reviewed_geometry(scene, ident)
        if scene["primary_for_count"]:
            primaries += 1
            if (
                relation != "independent_case"
                or scene["role"] not in {"incident", "accident"}
                or not scene.get("coordinates")
            ):
                raise ValueError(f"Invalid primary scene for {ident}")
        duplicate = scene.get("duplicate_of_source_id")
        if duplicate is not None:
            duplicate = str(duplicate)
            if duplicate not in body:
                raise ValueError(f"Scene source relationship is absent for {ident}")
            expected_hash = (source_hashes or {}).get(duplicate)
            supplied_hash = scene.get("duplicate_source_sha256")
            if expected_hash is not None and supplied_hash != expected_hash:
                raise ValueError(f"Stale linked scene source for {ident}")
            if expected_hash is None and supplied_hash is not None:
                raise ValueError(f"Unverifiable linked scene source for {ident}")
    if primaries > 1:
        raise ValueError(f"Multiple primary scenes for {ident}")
    return reviewed
