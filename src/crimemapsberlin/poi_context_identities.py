"""Bind explicitly reviewed named POI identities independently of scene geometry.

A broad square, street or unknown incident position is not the identity of a
named landmark. These decisions select existing, validated native POIs only;
they never geocode a scene, change its role/time/count, infer a type from a
name, or approve publication. No native object is selected automatically.
"""

from __future__ import annotations

import hashlib
import json
import re

from .poi_context import matches_reviewed_context


def identity_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


LEDGER_KEYS = {"schema_version", "city", "inventory_digest", "poi_contract_sha256", "decisions", "ledger_sha256"}
DECISION_KEYS = {
    "context_id", "source_id", "source_url", "source_sha256", "context_sha256",
    "native_object_id", "poi_feature_sha256", "identity_evidence_quotes", "review_note",
}


def literal_named_place_matches(context: dict, properties: dict, quotes: list[str]) -> bool:
    """Only an explicit identity decision may retain an unspecified place type.

    This does not add named_place to automatic type matching. A selected native
    object's complete name must occur literally in the source evidence, with
    word boundaries; a brand fragment, guessed type or proximity is not enough.
    """
    if context.get("kind") != "named_place" or context.get("scope") != "named_object":
        return False
    names = [properties.get("name"), *properties.get("aliases", [])]
    normalized_quotes = [" ".join(quote.split()).casefold() for quote in quotes]
    return any(
        isinstance(name, str) and len(name.strip()) >= 4
        and any(re.search(r"(?<!\w)" + re.escape(" ".join(name.split()).casefold()) + r"(?!\w)", quote)
                for quote in normalized_quotes)
        for name in names
    )


def apply_reviewed_identities(
    *, events: list[dict], source_rows: list[dict], inventory: dict, poi_index: dict,
    poi_contract_sha256: str, ledger: dict,
) -> tuple[list[dict], dict]:
    """Validate the entire ledger before projecting any context-only identity."""
    if not isinstance(ledger, dict) or set(ledger) != LEDGER_KEYS:
        raise ValueError("Invalid named POI identity ledger fields")
    core = {key: value for key, value in ledger.items() if key != "ledger_sha256"}
    if ledger["ledger_sha256"] != identity_digest(core):
        raise ValueError("Named POI identity ledger digest mismatch")
    if (
        ledger["schema_version"] != 1 or ledger["city"] != inventory["city"]
        or ledger["inventory_digest"] != inventory["inventory_digest"]
        or ledger["poi_contract_sha256"] != poi_contract_sha256
        or not isinstance(ledger["decisions"], list)
    ):
        raise ValueError("Named POI identities are stale or belong to another input")
    sources = {row["source_id"]: row for row in source_rows}
    contexts = {}
    for event in events:
        for scene in event.get("scene_locations", []):
            for number, context in enumerate(scene.get("poi_contexts", []), 1):
                ident = f"{scene['scene_id']}:poi:{number}"
                if ident in contexts or "reviewed_object_ids" in context or "native_identity_review" in context:
                    raise ValueError("Duplicate or preprojected named POI context")
                contexts[ident] = event, scene, context
    features = {f["properties"]["id"]: f for f in poi_index["features"]}
    if len(features) != len(poi_index["features"]) or len(sources) != len(source_rows):
        raise ValueError("Duplicate native POI or source identity")
    projections = {}
    for row in ledger["decisions"]:
        if not isinstance(row, dict) or set(row) != DECISION_KEYS:
            raise ValueError("Invalid named POI identity decision fields")
        ident = row["context_id"]
        if not isinstance(ident, str) or ident in projections or ident not in contexts:
            raise ValueError("Unknown or duplicate named POI context decision")
        event, _scene, context = contexts[ident]
        source = sources.get(row["source_id"])
        if source is None or event["id"] != row["source_id"] or (
            source["source_url"], source["source_sha256"]
        ) != (row["source_url"], row["source_sha256"]) or (
            event.get("source_url"), event.get("source_sha256")
        ) != (row["source_url"], row["source_sha256"]):
            raise ValueError("Named POI source identity changed")
        if hashlib.sha256(source["source_body"].encode()).hexdigest() != source["source_sha256"]:
            raise ValueError("Named POI source body hash mismatch")
        if context.get("scope") != "named_object" or identity_digest(context) != row["context_sha256"]:
            raise ValueError("Named POI context scope or review changed")
        quotes = row["identity_evidence_quotes"]
        if (
            not isinstance(quotes, list) or not quotes or not all(isinstance(q, str) and q.strip() for q in quotes)
            or len(quotes) != len(set(quotes)) or context.get("evidence_quote") not in quotes
            or any(q not in source["source_body"] for q in quotes)
            or not isinstance(row["review_note"], str) or len(row["review_note"].strip()) < 20
        ):
            raise ValueError("Named POI identity needs current literal evidence and an explicit review")
        native_id = row["native_object_id"]
        feature = features.get(native_id) if isinstance(native_id, str) else None
        native_reference = feature["properties"].get("native_named_reference", {}) if feature else {}
        reference_bound = any(
            binding.get("context_id") == ident and binding.get("source_id") == row["source_id"]
            and binding.get("source_url") == row["source_url"] and binding.get("source_sha256") == row["source_sha256"]
            and binding.get("context_sha256") == row["context_sha256"] and binding.get("source_context_kind") == context["kind"]
            for binding in native_reference.get("source_context_bindings", [])
        ) and native_reference.get("association") == "source_reviewed_context_only"
        literal_named_place = feature is not None and literal_named_place_matches(context, feature["properties"], quotes)
        if (
            not isinstance(native_id, str) or re.fullmatch(r"osm/(node|way|relation)/[1-9][0-9]*", native_id) is None
            or feature is None or identity_digest(feature) != row["poi_feature_sha256"]
            or not (matches_reviewed_context(context["kind"], feature["properties"], features) or reference_bound or literal_named_place)
        ):
            raise ValueError("Named POI native identity, geometry or literal type changed")
        projections[ident] = {
            **context, "reviewed_object_ids": [native_id],
            "native_identity_review": {
                "context_id": ident, "ledger_sha256": ledger["ledger_sha256"],
                "source_url": row["source_url"], "source_sha256": row["source_sha256"],
                "poi_feature_sha256": row["poi_feature_sha256"],
                "evidence_quotes": quotes, "review_note": row["review_note"],
                "association": "source_reviewed_context_only",
                "does_not_locate_or_count_scene": True,
                **({"native_type_basis": "source_bound_named_reference_native_type_unknown"}
                   if reference_bound and feature["properties"].get("native_type_unknown") is True else {}),
                **({"native_type_basis": "source_bound_literal_named_place_identity_source_type_unspecified",
                    "source_context_type_remains_unspecified": True} if literal_named_place else {}),
            },
        }
    # Copy only the event/scene/context containers. Original source decisions and
    # all scene geometry/time/role/count values remain untouched, even on error.
    result = []
    for event in events:
        scenes = []
        for scene in event.get("scene_locations", []):
            contexts = [projections.get(f"{scene['scene_id']}:poi:{n}", context)
                        for n, context in enumerate(scene.get("poi_contexts", []), 1)]
            scenes.append({**scene, "poi_contexts": contexts} if "poi_contexts" in scene else scene)
        result.append({**event, "scene_locations": scenes})
    return result, {"ledger_sha256": ledger["ledger_sha256"], "decisions": len(projections),
                    "association": "source_reviewed_context_only", "changes_scene_geometry_or_counts": False}
