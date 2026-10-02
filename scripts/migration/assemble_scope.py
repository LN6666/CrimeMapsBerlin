"""Assemble a bound scope overlay into a new single-city immutable generation.

Copies only declared map payload files. It does not approve a source batch, translate
text, compute geometry, or publish the candidate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def safe(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if (not relative or relative != path.as_posix() or path.is_absolute() or "\\" in relative
            or any(p in {".", ".."} for p in path.parts)):
        raise ValueError("Unsafe payload path")
    result = root / relative
    if result.is_symlink() or root.resolve() not in result.resolve().parents or not result.is_file():
        raise ValueError("Missing payload or unsafe link")
    return result


def declared(manifest: dict) -> set[str]:
    generation = manifest["generation"]
    if not re.fullmatch(r"[a-f0-9]{16}-\d{8}T\d{6}", generation):
        raise ValueError("Invalid source generation")
    paths = {f"{generation}/{name}" for name in ["search.json", "boundary.geojson", "roads-overview.json"]}
    for month in manifest["months"]:
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise ValueError("Invalid month")
        paths.add(f"{generation}/months/{month}.json")
    for kind in ["pois", "roads"]:
        paths.update(f"{generation}/{kind}/{key}.json" for key in manifest["tile_index"][kind])
    return paths


def assemble(source: Path, overlay: Path, receipt_sha: str, output: Path, report: Path,
             supplemental: Path | None = None, supplemental_sha: str | None = None,
             overlay_manifest_sha: str | None = None) -> dict:
    if output.exists():
        raise ValueError("Retain previous candidate; output must be new")
    receipt_path = overlay / "poi-scope-receipt.json"
    if sha(receipt_path) != receipt_sha:
        raise ValueError("Scope receipt changed")
    if not overlay_manifest_sha or sha(overlay / "manifest.candidate.json") != overlay_manifest_sha:
        raise ValueError("Scope manifest differs from its accepted detached binding")
    receipt = json.loads(receipt_path.read_text())
    if (receipt.get("native_geometry_changed") is not False or receipt.get("reviewed_records_changed") is not False
            or receipt.get("all_protected_ids_retained") is not True or receipt.get("publication_ready") is not False):
        raise ValueError("Scope preservation conditions not satisfied")
    if sha(source / "manifest.json") != receipt["input_manifest_file_sha256"]:
        raise ValueError("Source manifest changed")
    old = json.loads((source / "manifest.json").read_text())
    manifest = json.loads((overlay / "manifest.candidate.json").read_text())
    if any(manifest.get(k) != old.get(k) for k in ["city", "generation", "months", "categories"]):
        raise ValueError("Unexpected city/month/source category change")
    extra = {}
    if supplemental is not None:
        if not supplemental_sha or sha(supplemental) != supplemental_sha:
            raise ValueError("Supplemental source binding changed")
        value = json.loads(supplemental.read_text())
        if value["source_manifest_sha256"] != receipt["input_manifest_file_sha256"]:
            raise ValueError("Supplemental binding belongs to another candidate")
        extra = value["files"]
        if set(extra).intersection(receipt["input_file_sha256"]):
            raise ValueError("Supplemental binding cannot override scope inputs")
    source_bound = dict(receipt["input_file_sha256"], **extra)
    # Validate every bound source and overlay file before assembling any output.
    for relative, digest in source_bound.items():
        if sha(safe(source, relative)) != digest:
            raise ValueError("Bound source payload changed")
    for relative, digest in receipt["overlay_file_sha256"].items():
        if sha(safe(overlay / "overlay", relative)) != digest:
            raise ValueError("Bound scope payload changed")
    removed = set(receipt["removed_files"])
    expected = declared(manifest)
    if expected.intersection(removed):
        raise ValueError("Manifest still references removed scope files")
    files = {}
    total = 0
    for relative in sorted(expected):
        changed = relative in receipt["overlay_file_sha256"]
        path = safe(overlay / "overlay" if changed else source, relative)
        bound = receipt["overlay_file_sha256"] if changed else source_bound
        if relative not in bound or sha(path) != bound[relative]:
            raise ValueError("Unbound requested payload")
        if "/months/" in relative and changed:
            raise ValueError("Scope cannot modify reviewed source-month files")
        total += path.stat().st_size
        if total > 900_000_000:
            raise ValueError("Single-city payload exceeds budget")
        files[relative] = {"sha256": sha(path), "bytes": path.stat().st_size, "changed_by_scope": changed}
    identity = {"scope_receipt_sha256": receipt_sha, "manifest": manifest, "files": files}
    generation = hashlib.sha256(dump(identity)).hexdigest()[:16] + "-" + old["generation"].split("-")[1]
    if generation == old["generation"]:
        raise ValueError("Changed data cannot reuse its old generation")
    output.mkdir(parents=True)
    copied = {}
    for relative, detail in files.items():
        path = safe(overlay / "overlay" if detail["changed_by_scope"] else source, relative)
        new_relative = generation + "/" + relative.split("/", 1)[1]
        target = output / new_relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        if sha(target) != detail["sha256"]:
            raise ValueError("Copy verification failed")
        copied[new_relative] = detail
    manifest["generation"] = generation
    manifest["publication_ready"] = False
    manifest["metadata"]["poi_scope_rebuild_requires_new_generation"] = False
    manifest["metadata"]["migration_source_generation"] = old["generation"]
    manifest["metadata"]["poi_scope_receipt_sha256"] = receipt_sha
    (output / "manifest.json").write_bytes(dump(manifest))
    result = {"city": manifest["city"], "source_generation": old["generation"], "generation": generation,
              "scope_receipt_sha256": receipt_sha, "manifest_sha256": sha(output / "manifest.json"),
              "overlay_manifest_sha256": overlay_manifest_sha,
              "supplemental_sha256": supplemental_sha,
              "files": copied, "bytes": total, "months_byte_identical": True, "publication_ready": False}
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_bytes(dump(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for key in ["source", "overlay", "output", "report"]:
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--receipt-sha256", required=True)
    parser.add_argument("--overlay-manifest-sha256", required=True)
    parser.add_argument("--supplemental-hashes", type=Path)
    parser.add_argument("--supplemental-sha256")
    args = parser.parse_args()
    value = assemble(args.source, args.overlay, args.receipt_sha256, args.output, args.report,
                     args.supplemental_hashes, args.supplemental_sha256, args.overlay_manifest_sha256)
    print(json.dumps({k: v for k, v in value.items() if k != "files"}))
