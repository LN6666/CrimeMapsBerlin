"""Create an ignored statistics metadata sidecar from an accepted city artifact.

The acceptance descriptor is supplied by the migration/city owner from existing
checks. This helper verifies bindings; it does not perform semantic review,
approve a map or publish it. Never overwrite the input manifest.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(manifest_path: Path, acceptance: dict, facts: dict) -> dict:
    manifest = json.loads(manifest_path.read_text())
    city = acceptance["city"]
    if acceptance.get("schema_version") != 1 or acceptance["generation"] != manifest["generation"]:
        raise ValueError("Stale or unsupported acceptance descriptor")
    if acceptance["manifest_sha256"] != digest(manifest_path):
        raise ValueError("Manifest changed after accepted checks")
    required = {"source", "semantic", "geometry", "browser"}
    if set(acceptance["checks"]) != required or any(v is not True for v in acceptance["checks"].values()):
        raise ValueError("Current required checks are not all accepted")
    if not acceptance.get("evidence_files"):
        raise ValueError("No existing check evidence supplied")
    for evidence in acceptance["evidence_files"]:
        if digest(Path(evidence["path"])) != evidence["sha256"]:
            raise ValueError("Check evidence changed")
    city_facts = next(c for c in facts["cities"] if c["city"] == city)
    if manifest.get("city") not in city_facts["artifact_city_names"]:
        raise ValueError("Acceptance belongs to a different city")
    if not re.fullmatch(r"[a-f0-9]{16}-\d{8}T\d{6}", manifest["generation"]):
        raise ValueError("Unsafe artifact generation")
    expected_files = {"manifest.json": digest(manifest_path)}
    identities = {}
    for month in sorted(manifest["months"]):
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise ValueError("Unsafe month path")
        relative = f"{manifest['generation']}/months/{month}.json"
        path = manifest_path.parent / relative
        expected = acceptance["month_sha256"].get(month)
        if expected is None or digest(path) != expected:
            raise ValueError("Month data changed after accepted checks")
        expected_files[relative] = expected
        payload = json.loads(path.read_text())
        if len(payload["events"]) != manifest["months"][month]["count"]:
            raise ValueError("Manifest month count mismatch")
        for item in payload["events"]:
            if item["id"] in identities:
                raise ValueError("Duplicate city announcement ID across months")
            identities[item["id"]] = item["source_url"]
    if set(acceptance["month_sha256"]) != set(manifest["months"]):
        raise ValueError("Acceptance month set mismatch")
    assessments = acceptance.get("complete_tag_assessments", [])
    for assessment in assessments:
        if identities.get(assessment["id"]) != assessment["source_url"]:
            raise ValueError("Stale tag assessment identity")
    # An empty list means missing interval inventory, not perfect source coverage.
    return {"announcement_statistics": {
        "schema_version": 1, "method_version": "announcement-statistics-v1",
        "city": city, "publisher_namespace": city_facts["publisher_namespace"],
        "data_basis": city_facts["data_basis"], "time_basis": city_facts["time_basis"],
        "generation": manifest["generation"],
        "artifact_sha256": hashlib.sha256(json.dumps(expected_files, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "data_as_of": manifest.get("retrieved_at"),
        "coverage_note": city_facts["coverage"],
        "missing_intervals": acceptance.get("known_missing_intervals", []),
        "complete_tag_assessments": assessments,
    }}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "acceptance", "fact-pack", "out"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    if ".runtime" not in args.out.resolve().parts:
        raise ValueError("Sidecar must be generated in ignored runtime storage")
    result = build(args.manifest, json.loads(args.acceptance.read_text()), json.loads(args.fact_pack.read_text()))
    if args.out.resolve() == args.manifest.resolve():
        raise ValueError("Do not overwrite source manifest")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__": main()
