"""Filter a checked map's POI display scope after associations are finalized.

This module never geocodes, matches, classifies announcements, rounds coordinates
or changes reviewed records. It produces an overlay and an assembly receipt;
the caller must build a new immutable generation and run its publication gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

VERSION = "crimemaps-poi-scope/1.0.0"
OSM_ID = re.compile(r"osm/(node|way|relation)/[1-9][0-9]*\Z")


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def safe_path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError("Unsafe artifact path")
    return path.as_posix()


def core_kind(tags: dict, policy: dict) -> str | None:
    if not isinstance(tags, dict) or any(not isinstance(v, str) for v in tags.values()):
        raise ValueError("Literal native tags required; names cannot replace tags")
    for rule in policy["background_rules"]:
        if "nonempty_key" in rule:
            value = tags.get(rule["nonempty_key"], "")
            if value.strip() and value not in rule["excluded_values"]:
                return rule["kind"]
        elif any(all(tags.get(key) in values for key, values in alternative.items())
                 for alternative in rule["alternatives"]):
            return rule["kind"]
    return None


def _native_ids(properties: dict) -> set[str]:
    ids = {properties.get("id"), *properties.get("osm_alias_object_ids", [])}
    if any(not isinstance(ident, str) or not OSM_ID.fullmatch(ident) for ident in ids):
        raise ValueError("Stable native POI ID or alias is invalid")
    return ids


def literal_feature_tags(properties: dict) -> dict | None:
    if "osm_type_tags" in properties:
        return properties["osm_type_tags"]
    if "native_tags" in properties and properties.get("tag_provenance") == "original_current_PBF":
        if not re.fullmatch(r"[0-9a-f]{64}", properties.get("source_pbf_sha256", "")):
            raise ValueError("Original PBF native tags lack their source binding")
        return properties["native_tags"]
    return None


def select_feature(feature: dict, protected: set[str], policy: dict,
                   native_tags_by_id: dict | None = None) -> tuple[bool, str | None]:
    properties = feature["properties"]
    ids = _native_ids(properties)
    # Missing type metadata cannot be interpreted as a background exclusion.
    tags = literal_feature_tags(properties)
    if tags is None and native_tags_by_id is not None:
        record = native_tags_by_id.get(properties["id"])
        if record is not None:
            if record.get("input_feature_sha256") != digest(feature):
                raise ValueError("Recovered native tags belong to a changed display feature")
            if properties.get("native_tag_record_sha256") and (
                    record.get("native_record_sha256") != properties["native_tag_record_sha256"]):
                raise ValueError("Recovered native tags differ from the current accepted native record")
            tags = record["tags"]
    if tags is None:
        if (properties.get("native_type_unknown") is True
                and ids & protected
                and properties.get("native_named_reference", {}).get("source_context_bindings")):
            return True, None  # Explicitly reviewed unknown, never a guessed core type.
        raise ValueError(f"{properties['id']}: original osm_type_tags required before scope conversion")
    kind = core_kind(tags, policy)
    return bool(kind or ids & protected or properties.get("native_named_reference", {}).get(
        "source_context_bindings")), kind


def filter_feature_collection(*, collection: dict, source_links: list[dict],
                              explicit_native_ids: set[str], policy: dict,
                              native_tags_by_id: dict | None = None) -> tuple[dict, dict]:
    """Composition entrypoint for custom Cologne/Frankfurt map adapters.

    The adapter supplies its current, accepted finalized links. The routine
    validates stable identity and preserves all input feature fields. Scene
    records, routes, source bodies and unknown dispositions are separate inputs
    owned by the existing city review pipeline and must not be filtered here.
    """
    if collection.get("type") != "FeatureCollection" or policy.get("policy_version") != VERSION:
        raise ValueError("Unsupported normalized feature collection or policy")
    protected = set(explicit_native_ids)
    pairs = set()
    for link in source_links:
        if not link.get("event_id") or not link.get("source_url") or not OSM_ID.fullmatch(link.get("poi_id", "")):
            raise ValueError("Normalized source link needs current announcement and native identities")
        pair = link["event_id"], link["poi_id"]
        if pair in pairs:
            raise ValueError("Duplicate normalized announcement/POI pair")
        pairs.add(pair)
        protected.add(link["poi_id"])
    rows, seen, resolved, categories, category_by_id = [], set(), set(), Counter(), {}
    for feature in collection["features"]:
        ident = feature["properties"]["id"]
        if ident in seen:
            raise ValueError("Normalized collection needs unique stable native identities")
        seen.add(ident)
        keep, kind = select_feature(feature, protected, policy, native_tags_by_id)
        if keep:
            rows.append(feature)
            resolved.update(_native_ids(feature["properties"]) & protected)
            categories[kind or "context"] += 1
            category_by_id[ident] = kind or "context"
    if protected - resolved:
        raise ValueError("Normalized source-linked native POI is absent")
    return {**collection, "features": rows}, {
        "policy_version": VERSION, "policy_sha256": digest(policy),
        "input_poi_count": len(seen), "poi_count": len(rows),
        "display_category_counts": dict(sorted(categories.items())),
        "scope_category_by_native_id": dict(sorted(category_by_id.items())),
        "source_poi_pair_count": len(pairs), "all_protected_ids_retained": True,
        "native_geometry_changed": False, "reviewed_records_changed": False,
        "current_source_review_required_in_adapter": True, "publication_ready": False}


def transform_artifact(*, manifest: dict, read: Callable[[str], bytes], policy: dict,
                       write: Callable[[str, bytes], None] | None = None,
                       native_tag_adapter: dict | None = None) -> tuple[dict, dict]:
    """Inspect every declared tile; optionally write only changed overlay files.

    Existing scene/event/hex/link files are retained byte-for-byte by assembly.
    A source-only object remains in its existing category, with unknown type and
    geometry unchanged. The routine fails when a linked POI is absent or two
    tiles disagree about one stable native identity.
    """
    if policy.get("policy_version") != VERSION or manifest.get("schema_version") != 2:
        raise ValueError("Unsupported POI policy or map schema; adapt explicitly")
    native_tags_by_id = None
    if native_tag_adapter is not None:
        if (native_tag_adapter.get("schema_version") != 1
                or native_tag_adapter.get("input_manifest_sha256") != digest(manifest)
                or not re.fullmatch(r"[0-9a-f]{64}", native_tag_adapter.get("poi_contract_sha256", ""))
                or (manifest.get("metadata", {}).get("poi_contract_sha256") is not None
                    and native_tag_adapter.get("poi_contract_sha256") != manifest["metadata"]["poi_contract_sha256"])
                or not re.fullmatch(r"[0-9a-f]{64}", native_tag_adapter.get("source_pbf_sha256", ""))
                or not re.fullmatch(r"[0-9a-f]{64}", native_tag_adapter.get("accepted_native_proof_sha256", ""))):
            raise ValueError("Recovered native tag adapter lacks current artifact/source bindings")
        native_tags_by_id = native_tag_adapter["records"]
    generation = safe_path(manifest["generation"])
    if "/" in generation:
        raise ValueError("Generation must be a single immutable directory name")
    inputs: dict[str, str] = {}
    overlays: dict[str, str] = {}
    unchanged: list[str] = []
    removed: list[str] = []

    def fetch(path: str) -> bytes:
        path = safe_path(path)
        content = read(path)
        inputs[path] = hashlib.sha256(content).hexdigest()
        return content

    def changed(path: str, value: object):
        data = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        overlays[path] = hashlib.sha256(data).hexdigest()
        if write is not None:
            write(path, data)
        return len(data)

    protected: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    sources: dict[str, dict] = {}
    months: dict[str, dict] = {}
    for month in sorted(manifest["months"]):
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", month):
            raise ValueError("Invalid month artifact path")
        path = f"{generation}/months/{month}.json"
        monthly = json.loads(fetch(path))
        unchanged.append(path)
        months[month] = monthly
        if not isinstance(monthly.get("events"), list) or not isinstance(monthly.get("links"), list):
            raise TypeError("Explicit month events and finalized links are required")
        for event in monthly["events"]:
            ident = event["id"]
            if not isinstance(ident, str):
                raise TypeError("Announcement ID must be a string")
            if ident in sources or not event.get("source_url"):
                raise ValueError("Duplicate announcement or missing source identity")
            sources[ident] = event
            # Explicit identity decisions may be kept even with no spatial match.
            for scene in event.get("scene_locations", []):
                for context in scene.get("poi_contexts", []):
                    protected.update(context.get("reviewed_object_ids", []))
        if (len(monthly["event_ids"]) != len(set(monthly["event_ids"]))
                or set(monthly["event_ids"]) != {event["id"] for event in monthly["events"]}):
            raise ValueError("Month event inventory differs from its explicit records")
    for monthly in months.values():
        for link in monthly["links"]:
            event = sources.get(link["event_id"])
            if event is None or link.get("source_url") != event["source_url"]:
                raise ValueError("POI link source is absent or changed")
            pair = link["event_id"], link["poi_id"]
            if pair in pairs or not OSM_ID.fullmatch(pair[1]):
                raise ValueError("Duplicate announcement/POI pair or invalid native ID")
            pairs.add(pair)
            protected.add(pair[1])

    identities: dict[str, str] = {}
    alias_owners: dict[str, str] = {}
    selected: set[str] = set()
    resolved_protected: set[str] = set()
    core: set[str] = set()
    source_only: set[str] = set()
    source_bound: set[str] = set()
    search_candidates: dict[str, dict] = {}
    scope_categories: dict[str, str] = {}
    memberships: Counter = Counter()
    source_selected_references: set[str] = set()
    categories: Counter = Counter()
    background_categories: Counter = Counter()
    display_categories: dict[str, set[str]] = {}
    modes: Counter = Counter()
    output_tiles: list[str] = []
    input_bytes = output_bytes = input_rows = output_rows = 0
    declared = manifest["tile_index"]["pois"]
    if len(set(declared)) != len(declared):
        raise ValueError("Duplicate declared POI tile")
    for key in sorted(declared):
        safe_path(key)
        if not re.fullmatch(r"[a-z_]+/-?[0-9]+_-?[0-9]+", key):
            raise ValueError("Unsupported tile naming; adapt explicitly")
        path = f"{generation}/pois/{key}.json"
        raw = fetch(path)
        tile = json.loads(raw)
        if tile.get("type") != "FeatureCollection":
            raise ValueError("Expected native feature collection")
        kept = []
        within_tile: set[str] = set()
        for feature in tile["features"]:
            properties = feature["properties"]
            ident = properties["id"]
            aliases = _native_ids(properties)
            tile_category = key.split("/")[0]
            if ident in within_tile or (properties["kind"] != tile_category
                    and tile_category not in properties.get("context_kinds", [])):
                raise ValueError("Duplicate tile identity or category mismatch")
            within_tile.add(ident)
            fingerprint = digest(feature)
            if ident in identities and identities[ident] != fingerprint:
                raise ValueError("Conflicting repeated native POI feature")
            first = ident not in identities
            identities[ident] = fingerprint
            for alias in aliases:
                if alias in alias_owners and alias_owners[alias] != ident:
                    raise ValueError("A stable native alias belongs to multiple POI identities")
                alias_owners[alias] = ident
            keep, background_kind = select_feature(feature, protected, policy, native_tags_by_id)
            bindings = properties.get("native_named_reference", {}).get("source_context_bindings", [])
            for binding in bindings:
                source = sources.get(binding.get("source_id"))
                if source is None or binding.get("source_url") != source["source_url"] or (
                    binding.get("source_sha256") != source.get("source_sha256")
                ):
                    raise ValueError("Native source-selected reference binding changed")
            if keep:
                kept.append(feature)  # No projection: all properties/coordinates survive.
                selected.add(ident)
                scope_categories[ident] = background_kind or "context"
                if properties.get("native_named_reference"):
                    source_selected_references.add(ident)
                resolved_protected.update(aliases & protected)
                if background_kind:
                    core.add(ident)
                else:
                    source_only.add(ident)
                if aliases & protected or bindings:
                    source_bound.add(ident)
                if first:
                    memberships.update(set(properties.get("context_kinds", [properties["kind"]])))
                    if properties.get("name") and properties["name"] != properties["kind"]:
                        search_candidates[ident] = {k: properties[k] for k in
                            ["id", "name", "aliases", "kind", "center"] if k in properties}
                    categories[properties["kind"]] += 1
                    if background_kind:
                        background_categories[background_kind] += 1
                    display_categories.setdefault(properties["kind"], set()).add(background_kind or "context")
                    modes[properties["geometry_mode"]] += 1
        input_rows += len(tile["features"])
        output_rows += len(kept)
        input_bytes += len(raw)
        if kept:
            output_tiles.append(key)
            if len(kept) == len(tile["features"]):
                unchanged.append(path)
                output_bytes += len(raw)
            else:
                output_bytes += changed(path, {**tile, "features": kept})
        else:
            removed.append(path)
    if protected - resolved_protected:
        raise ValueError("Source-linked POI is absent: " + ", ".join(sorted(protected - resolved_protected)[:10]))

    # Search must not expose excluded neutral facilities. Unknown labels remain.
    search_path = f"{generation}/search.json"
    if manifest.get("files", {}).get("search"):
        search_path = safe_path(manifest["files"]["search"])
    try:
        search_raw = fetch(search_path)
    except (KeyError, FileNotFoundError):
        search_raw = None
    search_mode = "absent_in_input"
    if search_raw is not None:
        search = json.loads(search_raw)
        if not isinstance(search, list) or not all(isinstance(row, dict) for row in search):
            raise ValueError("Unsupported search format; adapt explicitly")
        if any("id" not in row for row in search):
            # Older searches omitted IDs. Rebuild from selected native records,
            # never identify an object by name/center or mint a new coordinate.
            filtered = [search_candidates[ident] for ident in sorted(search_candidates)]
            search_mode = "rebuilt_from_retained_native_features"
        else:
            if any(row["id"] not in identities for row in search):
                raise ValueError("Search contains an absent POI; adapt explicitly")
            filtered = [row for row in search if row["id"] in selected]
            search_mode = "exact_stable_id_subset"
        if filtered == search:
            unchanged.append(search_path)
        else:
            changed(search_path, filtered)
    result = deepcopy(manifest)
    result["tile_index"]["pois"] = output_tiles
    policy_binding = {"policy_version": VERSION, "policy_sha256": digest(policy),
                      "background_profile": policy["background_profile"],
                      "count_unit": "unique_native_poi_id",
                      "poi_count": len(selected), "background_core_count": len(core),
                      "source_only_count": len(source_only), "source_linked_count": len(source_bound),
                      "source_poi_pair_count": len(pairs), "poi_bytes": output_bytes,
                      "native_geometry_changed": False, "reviewed_records_changed": False}
    result.setdefault("metadata", {})["poi_scope"] = policy_binding
    result["metadata"]["poi_count"] = len(selected)
    result["metadata"]["poi_scope_baseline_count"] = len(identities)
    baseline_counts = {}
    for key, current in [("poi_membership_counts", dict(sorted(memberships.items()))),
                         ("base_native_typed_poi_count", len(selected - source_selected_references))]:
        if key in result["metadata"]:
            baseline_counts[key] = result["metadata"][key]
            result["metadata"][key] = current
    if baseline_counts:
        result["metadata"]["poi_scope_baseline_counts"] = baseline_counts
    result["metadata"]["poi_scope_rebuild_requires_new_generation"] = True
    if "poi_count" in result:
        result["poi_count"] = len(selected)
    receipt = {"schema_version": 1, **policy_binding, "input_manifest_sha256": digest(manifest),
               "input_file_sha256": inputs, "overlay_file_sha256": overlays,
               "unchanged_files": sorted(unchanged), "removed_files": sorted(removed),
               "input_poi_count": len(identities), "input_poi_bytes": input_bytes,
               "input_tile_rows": input_rows, "output_tile_rows": output_rows,
               "categories": dict(sorted(categories.items())), "geometry_modes": dict(sorted(modes.items())),
               "background_category_counts": dict(sorted(background_categories.items())),
               "display_categories_by_original_kind": {k: sorted(v) for k, v in sorted(display_categories.items())},
               "scope_category_by_native_id": dict(sorted(scope_categories.items())),
               "retained_feature_set_sha256": digest({k: identities[k] for k in sorted(selected)}),
               "source_links_sha256": digest(sorted(pairs)),
               "search_mode": search_mode,
               "source_month_files_unchanged": True, "all_protected_ids_retained": True,
               "assembly_required": True, "publication_ready": False,
               "upstream_review_bindings": manifest.get("metadata", {})}
    if native_tag_adapter is not None:
        receipt["native_tag_adapter_sha256"] = digest(native_tag_adapter)
        receipt["native_tag_adapter_proofs"] = {k: native_tag_adapter[k] for k in
            ["poi_contract_sha256", "source_pbf_sha256", "accepted_native_proof_sha256"]}
    return result, receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--root", type=Path)
    inputs.add_argument("--zip", type=Path)
    parser.add_argument("--prefix", default="site/safety")
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--native-tags", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Output must be fresh; previous good candidates are never replaced")
    policy = json.loads(args.policy.read_text())
    archive = ZipFile(args.zip) if args.zip else None
    prefix = safe_path(args.prefix)

    def read(path: str) -> bytes:
        if archive is not None:
            return archive.read(f"{prefix}/{safe_path(path)}")
        root = args.root.resolve()
        target = (root / safe_path(path)).resolve()
        if not target.is_relative_to(root):
            raise ValueError("Artifact path escaped root")
        return target.read_bytes()

    def write(path: str, data: bytes):
        target = args.out / "overlay" / safe_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    try:
        manifest_raw = read("manifest.json")
        result, receipt = transform_artifact(manifest=json.loads(manifest_raw), read=read,
                                             policy=policy, write=write,
                                             native_tag_adapter=json.loads(args.native_tags.read_text()) if args.native_tags else None)
        receipt["input_manifest_file_sha256"] = hashlib.sha256(manifest_raw).hexdigest()
        receipt["input_location"] = {"zip": str(args.zip.resolve()) if args.zip else None,
                                     "root": str(args.root.resolve()) if args.root else None,
                                     "prefix": prefix}
        args.out.mkdir(parents=True, exist_ok=True)
        for name, value in [("manifest.candidate.json", result), ("poi-scope-receipt.json", receipt)]:
            (args.out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({k: receipt[k] for k in ["policy_version", "poi_count", "background_core_count",
                         "source_only_count", "source_poi_pair_count", "input_poi_bytes", "poi_bytes"]}))
    finally:
        if archive is not None:
            archive.close()


if __name__ == "__main__":
    main()
