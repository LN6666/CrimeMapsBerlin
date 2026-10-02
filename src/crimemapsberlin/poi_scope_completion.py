"""Complete neutral background coverage without re-running source associations.

The checked existing selection and native eligibility census are separate
inputs. Existing objects and explicit native aliases take priority; only genuinely
missing stable IDs are appended. Display metadata is the sole allowed change to
retained features. Police records and links are not inputs to this routine.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy

try:
    from .poi_scope import VERSION, _native_ids, core_kind, digest
except ImportError:
    from poi_scope import VERSION, _native_ids, core_kind, digest


DISPLAY_HASH_FIELD = "poi_scope_original_feature_sha256"


def display_manifest_metadata(collection: dict, receipt: dict) -> dict:
    """Recompute display inventories; preserve all unrelated source metadata.

    The assembly caller merges these fields into its new manifest after current
    source/scene/link evidence is bound. No per-object map belongs in the manifest.
    Tile-row counts and encoded byte totals are producer-specific and computed
    after tiling/encoding, never copied from the old generation.
    """
    rows = collection["features"]
    categories, memberships = Counter(), Counter()
    seen = set()
    for feature in rows:
        props = feature["properties"]
        if props["id"] in seen:
            raise ValueError("Manifest inventory needs unique native objects")
        seen.add(props["id"])
        categories[props["scope_category"]] += 1
        memberships.update(set(props.get("context_kinds", [props["kind"]])))
    if len(rows) != receipt["display_native_object_count"] or dict(categories) != receipt["display_category_counts"]:
        raise ValueError("Completed POI inventory differs from its checked receipt")
    return {"poi_count": len(rows), "poi_membership_counts": dict(sorted(memberships.items())),
            "base_native_typed_poi_count": sum(not bool(f["properties"].get("native_named_reference")) for f in rows),
            "poi_scope_groups": deepcopy(receipt["poi_scope_groups"]),
            "poi_scope": {"policy_version": receipt["policy_version"], "policy_sha256": receipt["policy_sha256"],
                          "background_profile": "core13-plus-reviewed-source-linked",
                          "poi_count": len(rows), "source_only_count": categories["source_linked_context"],
                          "background_core_count": len(rows) - categories["source_linked_context"],
                          "native_eligibility_coverage_verified": True,
                          "eligible_native_id_count": receipt["eligible_native_id_count"],
                          "added_neutral_count": receipt["added_neutral_count"],
                          "real_world_facility_completeness_claimed": False}}


def display_feature(feature: dict, category: str) -> dict:
    result = deepcopy(feature)
    props = result["properties"]
    if DISPLAY_HASH_FIELD in props:
        raise ValueError("Display annotation must be applied once to an original feature")
    if props.get("scope_category") not in {None, category}:
        raise ValueError("Original scope category conflicts with checked literal category")
    props["scope_category"] = category
    props[DISPLAY_HASH_FIELD] = digest(feature)
    # Read-back the permitted metadata-only delta, including any prior category.
    original = deepcopy(result)
    original["properties"].pop(DISPLAY_HASH_FIELD)
    if "scope_category" not in feature["properties"]:
        original["properties"].pop("scope_category")
    if original != feature:
        raise ValueError("Scope annotation changed original native feature fields")
    return result


def complete_background(*, retained: dict, eligible: dict, categories: dict,
                        policy: dict) -> tuple[dict, dict]:
    if policy.get("policy_version") != VERSION:
        raise ValueError("Unsupported policy")
    if any(value.get("type") != "FeatureCollection" for value in [retained, eligible]):
        raise ValueError("Explicit feature collections required")
    legal_groups = {rule["kind"] for rule in policy["background_rules"]}
    owners, originals, rows, groups = {}, {}, [], defaultdict(set)
    for feature in retained["features"]:
        ident = feature["properties"]["id"]
        if ident in originals:
            raise ValueError("Retained collection must have unique original native IDs")
        originals[ident] = digest(feature)
        category = categories.get(ident)
        if category == "context":
            category = "source_linked_context"
        if category not in legal_groups | {"source_linked_context"}:
            raise ValueError("Retained object lacks a checked scope category")
        for alias in _native_ids(feature["properties"]):
            if alias in owners and owners[alias] != ident:
                raise ValueError("Explicit native alias has ambiguous ownership")
            owners[alias] = ident
        rows.append(display_feature(feature, category))
        # Existing extra category tiles remain legal but share one UI group.
        groups[category].update(feature["properties"].get("context_kinds", [feature["properties"]["kind"]]))
    if set(categories) != set(originals):
        raise ValueError("Category map differs from the retained original set")
    native, additions, represented = {}, [], {}
    for feature in eligible["features"]:
        props = feature["properties"]
        ident = props["id"]
        if ident in native:
            raise ValueError("Eligibility census contains duplicate native IDs")
        if _native_ids(props) != {ident}:
            raise ValueError("Native census cannot invent alias merging")
        category = core_kind(props.get("osm_type_tags", {}), policy)
        if category is None or props.get("kind") != category or props.get("scope_category") != category:
            raise ValueError("Eligibility census disagrees with literal core13 policy")
        if props.get("neutral_background_only") is not True or props.get("does_not_locate_or_count_event") is not True:
            raise ValueError("New background must have no source/location/count claim")
        if not feature.get("geometry") or not feature.get("location_geometry"):
            raise ValueError("Original native geometry must be present")
        native[ident] = digest(feature)
        if ident in owners:
            represented[ident] = owners[ident]
        else:
            additions.append(feature)
            groups[category].add(category)
    rows.extend(additions)
    coverage = set(represented) | {f["properties"]["id"] for f in additions}
    if coverage != set(native):
        raise ValueError("Supported native eligibility coverage has a gap")
    category_counts = Counter(f["properties"]["scope_category"] for f in rows)
    receipt = {
        "schema_version": 1, "policy_version": VERSION, "policy_sha256": digest(policy),
        "retained_original_count": len(originals), "eligible_native_id_count": len(native),
        "eligible_already_represented_count": len(represented),
        "eligible_represented_by_explicit_alias_count": sum(k != v for k, v in represented.items()),
        "added_neutral_count": len(additions), "display_native_object_count": len(rows),
        "display_category_counts": dict(sorted(category_counts.items())),
        "added_category_counts": dict(sorted(Counter(f["properties"]["kind"] for f in additions).items())),
        "retained_original_set_sha256": digest(originals), "eligible_set_sha256": digest(native),
        "added_original_set_sha256": digest({f["properties"]["id"]: digest(f) for f in additions}),
        "represented_eligible_ids_sha256": digest(represented),
        "supported_native_eligibility_coverage_verified": True,
        "explicit_aliases_preserved": True, "existing_native_fields_geometry_preserved": True,
        "display_metadata_only_added_to_retained_features": ["scope_category", DISPLAY_HASH_FIELD],
        "automatic_source_association_run": False, "source_links_or_count_points_created": False,
        "real_world_facility_completeness_claimed": False,
        "new_generation_assembly_required": True, "publication_ready": False,
        "poi_scope_groups": {group: {"label_key": "poi.context" if group == "source_linked_context"
                                     else f"poi.{group}", "kinds": sorted(kinds)}
                             for group, kinds in sorted(groups.items())},
    }
    return {**retained, "features": rows}, receipt
