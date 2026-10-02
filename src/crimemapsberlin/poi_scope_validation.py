"""Validate a versioned display scope receipt without approving publication."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

VERSION = "crimemaps-poi-scope/1.0.0"


def validate_receipt(receipt: dict, policy: dict) -> list[str]:
    errors = []
    digest = hashlib.sha256(json.dumps(policy, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()
    if receipt.get("policy_version") != VERSION or receipt.get("policy_sha256") != digest:
        errors.append("POI policy version or digest changed")
    for field in ["poi_count", "background_core_count", "source_only_count", "source_linked_count",
                  "source_poi_pair_count", "input_poi_count", "input_poi_bytes", "poi_bytes"]:
        if type(receipt.get(field)) is not int or receipt[field] < 0:
            errors.append(f"Invalid nonnegative count: {field}")
    if not errors:
        if receipt["poi_count"] != receipt["background_core_count"] + receipt["source_only_count"]:
            errors.append("Core/source-only partition differs from unique POI total")
        if receipt["source_linked_count"] > receipt["poi_count"] or receipt["poi_count"] > receipt["input_poi_count"]:
            errors.append("Invalid native identity subset")
        if sum(receipt.get("categories", {}).values()) != receipt["poi_count"]:
            errors.append("Original native category totals differ from unique identities")
        if sum(receipt.get("geometry_modes", {}).values()) != receipt["poi_count"]:
            errors.append("Geometry mode totals differ from unique identities")
    for field in ["native_geometry_changed", "reviewed_records_changed", "publication_ready"]:
        if receipt.get(field) is not False:
            errors.append(f"Scope conversion cannot claim {field}")
    for field in ["source_month_files_unchanged", "all_protected_ids_retained", "assembly_required"]:
        if receipt.get(field) is not True:
            errors.append(f"Missing scope guarantee: {field}")
    inputs = receipt.get("input_file_sha256", {})
    overlays = receipt.get("overlay_file_sha256", {})
    removed, unchanged = set(receipt.get("removed_files", [])), set(receipt.get("unchanged_files", []))
    if not inputs or not (removed | unchanged | set(overlays)) <= set(inputs):
        errors.append("Overlay assembly references an unbound input")
    if removed & unchanged or removed & set(overlays) or unchanged & set(overlays):
        errors.append("Assembly operations overlap")
    for binding in [inputs, overlays]:
        if any(not re.fullmatch(r"[0-9a-f]{64}", v) for v in binding.values()):
            errors.append("Invalid file SHA-256")
    return errors


def validate_completion_receipt(receipt: dict, policy: dict) -> list[str]:
    errors = []
    digest = hashlib.sha256(json.dumps(policy, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()
    if receipt.get("policy_version") != VERSION or receipt.get("policy_sha256") != digest:
        errors.append("POI policy version or digest changed")
    counts = ["retained_original_count", "eligible_native_id_count", "eligible_already_represented_count",
              "eligible_represented_by_explicit_alias_count", "added_neutral_count", "display_native_object_count"]
    for field in counts:
        if type(receipt.get(field)) is not int or receipt[field] < 0:
            errors.append(f"Invalid nonnegative count: {field}")
    if not errors:
        if receipt["eligible_native_id_count"] != receipt["eligible_already_represented_count"] + receipt["added_neutral_count"]:
            errors.append("Supported eligibility coverage partition differs")
        if receipt["display_native_object_count"] != receipt["retained_original_count"] + receipt["added_neutral_count"]:
            errors.append("Completed native display count differs")
        if receipt["eligible_represented_by_explicit_alias_count"] > receipt["eligible_already_represented_count"]:
            errors.append("Explicit alias count exceeds represented eligibility")
        if sum(receipt.get("display_category_counts", {}).values()) != receipt["display_native_object_count"]:
            errors.append("Display categories differ from completed unique native objects")
        if sum(receipt.get("added_category_counts", {}).values()) != receipt["added_neutral_count"]:
            errors.append("Added categories differ from genuinely missing native IDs")
    for field in ["supported_native_eligibility_coverage_verified", "explicit_aliases_preserved",
                  "existing_native_fields_geometry_preserved", "new_generation_assembly_required"]:
        if receipt.get(field) is not True:
            errors.append(f"Missing completion guarantee: {field}")
    for field in ["automatic_source_association_run", "source_links_or_count_points_created",
                  "real_world_facility_completeness_claimed", "publication_ready"]:
        if receipt.get(field) is not False:
            errors.append(f"Background completion cannot claim {field}")
    for field in ["retained_original_set_sha256", "eligible_set_sha256", "added_original_set_sha256",
                  "represented_eligible_ids_sha256"]:
        if not re.fullmatch(r"[0-9a-f]{64}", receipt.get(field, "")):
            errors.append(f"Invalid completion SHA-256: {field}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--completion", action="store_true")
    args = parser.parse_args()
    validator = validate_completion_receipt if args.completion else validate_receipt
    errors = validator(json.loads(args.receipt.read_text()), json.loads(args.policy.read_text()))
    print(json.dumps({"passed": not errors, "errors": errors, "publication_ready": False}))
    raise SystemExit(bool(errors))


if __name__ == "__main__":
    main()
