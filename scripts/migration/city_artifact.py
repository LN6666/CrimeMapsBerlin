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


def translation_paths(manifest: dict) -> dict[str, tuple[str, str]]:
    requested = {}
    translations = manifest.get("translations", {})
    if not isinstance(translations, dict):
        raise ValueError("Invalid translation index")
    for locale, months in translations.items():
        if locale not in {"de", "en", "zh"} or not isinstance(months, dict):
            raise ValueError("Unsupported translation locale/index")
        for month, relative in months.items():
            expected = f"translations/{locale}/{month}.json"
            if month not in manifest["months"] or relative != expected:
                raise ValueError("Translation belongs to another month or unsafe path")
            requested[safe_relative(f"{manifest['generation']}/{relative}")] = (locale, month)
    return requested


def validate_translation(path: Path, city: str, locale: str, month: str, manifest: dict) -> None:
    value = json.loads(path.read_text())
    allowed = {"schema_version", "locale", "city", "month", "source_generation", "texts", "fields", "native_text_hashes"}
    aliases = {manifest["generation"], manifest.get("metadata", {}).get("translation_source_generation"),
               manifest.get("metadata", {}).get("transport_source_generation")}
    if (not isinstance(value, dict) or not set(value) <= allowed or value.get("schema_version") != 1
            or value.get("city") != city or value.get("locale") != locale or value.get("month") != month
            or not isinstance(value.get("source_generation"), str) or value["source_generation"] not in aliases):
        raise ValueError("Translation identity/generation mismatch or private pack extension")
    texts = value.get("texts")
    valid_text = lambda text: isinstance(text, str) and bool(text.strip()) and len(text) <= 32000
    valid_sha = lambda sha: isinstance(sha, str) and bool(re.fullmatch(r"[a-f0-9]{64}", sha))
    if not isinstance(texts, dict) or any(not valid_sha(key) or not valid_text(text) for key, text in texts.items()):
        raise ValueError("Invalid public translation text")
    fields = value.get("fields", [])
    native = value.get("native_text_hashes", [])
    if not isinstance(fields, list) or not isinstance(native, list) or any(not valid_sha(key) for key in native):
        raise ValueError("Invalid public translation fields")
    addresses = set()
    for field in fields:
        if (not isinstance(field, dict) or not set(field) <= {"city", "source_id", "field", "text_sha256", "translated_text", "source_sha256", "method"}
                or field.get("city") != city or not isinstance(field.get("source_id"), str)
                or not isinstance(field.get("field"), str) or not field["field"]
                or not valid_sha(field.get("text_sha256")) or not valid_text(field.get("translated_text"))
                or ("source_sha256" in field and not valid_sha(field["source_sha256"]))
                or ("method" in field and field["method"] not in {"official_excerpt", "translated", "unchanged_native"})):
            raise ValueError("Invalid addressed public translation")
        address = (field["source_id"], field["field"])
        if address in addresses:
            raise ValueError("Duplicate addressed public translation")
        addresses.add(address)


def package(source: Path, output: Path, city: str, manifest_sha256: str, provenance: Path,
            provenance_sha256: str, receipt: Path, *, virtual_carrier: bool = False) -> dict:
    if output.exists():
        raise ValueError("Output already exists; retain previous good artifact")
    source = source.resolve()
    manifest_path = source / "manifest.json"
    if digest(manifest_path) != manifest_sha256 or digest(provenance) != provenance_sha256:
        raise ValueError("Manifest/provenance hash changed")
    evidence = json.loads(provenance.read_text())
    if evidence.get("city") != city or evidence.get("manifest_sha256") != manifest_sha256:
        raise ValueError("Provenance city or manifest mismatch")
    if virtual_carrier and (evidence.get("virtual_allowlist_only") is not True
            or evidence.get("raw_or_private_provenance_copied") is not False
            or evidence.get("scientific_judgments_changed") is not False
            or evidence.get("source_data_byte_changes") != 0
            or evidence.get("manifest_path") != str(manifest_path)):
        raise ValueError("Unchecked or mismatched virtual carrier provenance")
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
    translations = translation_paths(manifest)
    requested.update(translations)
    bound = evidence.get("files", {})
    if not isinstance(bound, dict) or set(bound) != requested:
        raise ValueError("Provenance exact file set mismatch; review payload extensions explicitly")
    files = {}
    total = 0
    events = set()
    sources = {}
    for relative in sorted(requested):
        binding = bound[relative]
        if virtual_carrier:
            if (not isinstance(binding, dict) or not isinstance(binding.get("path"), str)
                    or not Path(binding["path"]).is_absolute() or not isinstance(binding.get("bytes"), int)):
                raise ValueError("Invalid virtual file binding")
            path = Path(binding["path"])
            expected = binding.get("sha256")
            if (path.is_symlink() or not path.is_file() or any(parent.is_symlink() for parent in path.parents)
                    or path.stat().st_size != binding["bytes"]):
                raise ValueError("Virtual file size changed or unsafe symlink")
        else:
            path = source / relative
            expected = binding
        if relative == "manifest.json" and (path != manifest_path or expected != manifest_sha256):
            raise ValueError("Manifest file binding differs from the checked entrance")
        if path.is_symlink() or not path.is_file() or (not virtual_carrier and source not in path.resolve().parents):
            raise ValueError(f"Missing file or unsafe symlink: {relative}")
        actual = digest(path)
        if actual != expected:
            raise ValueError(f"Payload hash changed: {relative}")
        if relative in translations:
            validate_translation(path, city, *translations[relative], manifest)
        total += path.stat().st_size
        if total >= BUDGET:
            raise ValueError("Single-city data exceeds growth-safe budget")
        files[relative] = {"sha256": actual, "bytes": path.stat().st_size}
        sources[relative] = path
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
        shutil.copyfile(sources[relative], target)
        if digest(target) != files[relative]["sha256"]:
            raise ValueError("Copied payload differs")
    result = {"city": city, "source": str(source), "manifest_sha256": manifest_sha256,
              "provenance_sha256": provenance_sha256, "generation": generation,
              "files": files, "bytes": total, "budget_bytes": BUDGET,
              "map_announcement_count": len(events), "copy_byte_identical": True,
              "translation_pack_count": len(translations), "virtual_carrier_materialized": virtual_carrier,
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
    parser.add_argument("--virtual-carrier", action="store_true", help="Materialize an explicitly checked hash-bound virtual file allowlist")
    args = parser.parse_args()
    result = package(args.source, args.output, args.city, args.manifest_sha256,
                     args.provenance, args.provenance_sha256, args.receipt, virtual_carrier=args.virtual_carrier)
    print(json.dumps({"city": args.city, "files": len(result["files"]),
                      "bytes": result["bytes"], "announcements": result["map_announcement_count"]}))


if __name__ == "__main__":
    main()
