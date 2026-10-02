"""Copy one reviewed schema-2 city payload, preserving bytes and provenance.

This is an artifact packaging check. Source/semantic/geometry/browser acceptance
and approval live in external bound receipts and must be verified separately.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil

NAMES = {"berlin": "Berlin", "hamburg": "Hamburg", "munich": "München", "cologne": "Köln",
         "frankfurt": "Frankfurt", "dusseldorf": "Düsseldorf", "stuttgart": "Stuttgart",
         "leipzig": "Leipzig", "dortmund": "Dortmund", "bremen": "Bremen", "essen": "Essen",
         "dresden": "Dresden", "hannover": "Hannover", "nuremberg": "Nürnberg"}
BUDGET = 900_000_000


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in (".", "..") for part in path.parts) or "\\" in value:
        raise ValueError(f"Unsafe data path: {value}")
    if not value or value != path.as_posix():
        raise ValueError(f"Noncanonical data path: {value}")
    return value


def package(source: Path, output: Path, city: str, manifest_sha256: str, provenance: Path,
            provenance_sha256: str, receipt: Path) -> dict:
    if output.exists():
        raise ValueError("Output already exists; retain previous good artifact")
    source = source.resolve()
    manifest_path = source / "manifest.json"
    if digest(manifest_path) != manifest_sha256 or digest(provenance) != provenance_sha256:
        raise ValueError("Manifest/provenance hash changed")
    evidence = json.loads(provenance.read_text())
    if evidence.get("city") != city or evidence.get("manifest_sha256") != manifest_sha256:
        raise ValueError("Provenance city or manifest mismatch")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema_version") != 2 or manifest.get("city") != NAMES[city]:
        raise ValueError("Wrong city or unsupported manifest schema")
    generation = manifest["generation"]
    if not re.fullmatch(r"[a-f0-9]{16}-\d{8}T\d{6}", generation):
        raise ValueError("Invalid generation")
    requested = {"manifest.json"}
    for month in manifest["months"]:
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise ValueError("Invalid publication month")
        requested.add(f"{generation}/months/{month}.json")
    for kind in ["pois", "roads"]:
        for key in manifest["tile_index"][kind]:
            requested.add(safe_relative(f"{generation}/{kind}/{safe_relative(key)}.json"))
    for name in ["roads-overview.json", "search.json", "boundary.geojson"]:
        requested.add(f"{generation}/{name}")
    bound = evidence.get("files", {})
    if not isinstance(bound, dict) or set(bound) != requested:
        raise ValueError("Provenance exact file set mismatch; review payload extensions explicitly")
    files = {}
    total = 0
    events = set()
    for relative in sorted(requested):
        path = source / relative
        if path.is_symlink() or not path.is_file() or source not in path.resolve().parents:
            raise ValueError(f"Missing file or unsafe symlink: {relative}")
        actual = digest(path)
        if actual != bound[relative]:
            raise ValueError(f"Payload hash changed: {relative}")
        total += path.stat().st_size
        if total >= BUDGET:
            raise ValueError("Single-city data exceeds growth-safe budget")
        files[relative] = {"sha256": actual, "bytes": path.stat().st_size}
        if "/months/" in relative:
            value = json.loads(path.read_text())
            key = path.stem
            ids = [str(event["id"]) for event in value["events"]]
            if len(ids) != len(set(ids)) or events.intersection(ids):
                raise ValueError("Duplicate announcement across publication months")
            if len(ids) != manifest["months"][key]["count"] or set(ids) != set(map(str, value["event_ids"])):
                raise ValueError("Month announcement count/ID mismatch")
            if any(event.get("month") != key for event in value["events"]):
                raise ValueError("Occurrence month replaced publication month")
            events.update(ids)
    output.mkdir(parents=True)
    for relative in sorted(requested):
        target = output / "safety" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
        if digest(target) != files[relative]["sha256"]:
            raise ValueError("Copied payload differs")
    result = {"city": city, "source": str(source), "manifest_sha256": manifest_sha256,
              "provenance_sha256": provenance_sha256, "generation": generation,
              "files": files, "bytes": total, "budget_bytes": BUDGET,
              "map_announcement_count": len(events), "copy_byte_identical": True,
              "source_semantic_geometry_recomputed": False, "publication_gate_passed": False}
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--city", choices=sorted(NAMES), required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--provenance-sha256", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    result = package(args.source, args.output, args.city, args.manifest_sha256,
                     args.provenance, args.provenance_sha256, args.receipt)
    print(json.dumps({"city": args.city, "files": len(result["files"]),
                      "bytes": result["bytes"], "announcements": result["map_announcement_count"]}))


if __name__ == "__main__":
    main()
