"""Recover literal context tags from the same validated native POI selection.

Optional candidate-only metadata does not reclassify a POI, change geometry,
identify a source venue, or add an event/count point. It must bind the original
validated feature and raw native element. Names/brands are never type evidence.
"""

from __future__ import annotations

import codecs
import hashlib
import json
import mmap
import re
from pathlib import Path

from .poi_context_identities import identity_digest

METADATA_KEYS = frozenset({"delivery", "memorial", "addr:street", "beauty"})
LEDGER_KEYS = {"schema_version", "city", "poi_contract_sha256", "product_proof_path",
               "product_proof_sha256", "raw_checkpoint_path", "raw_checkpoint_sha256",
               "source_pbf_sha256", "decisions", "ledger_sha256"}
DECISION_KEYS = {"poi_id", "poi_feature_sha256", "native_object_id", "native_element_sha256", "tags"}
RESERVED_PROPERTY = "native_context_metadata"


def _sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def selected_raw_elements(path: Path, object_ids: set[str]) -> dict[str, dict]:
    """One bounded extraction from existing selection, not a PBF/GIS rebuild."""
    objects = {}
    framing = re.compile(rb'\{"type":"(node|way|relation)","id":([1-9][0-9]*)[,}]')
    with path.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
        matches = iter(framing.finditer(mapped))
        match = next(matches, None)
        try:
            while match is not None:
                following = next(matches, None)
                ident = f"osm/{match[1].decode()}/{match[2].decode()}"
                if ident not in object_ids:
                    match = following
                    continue
                if ident in objects:
                    raise ValueError("Duplicate selected native metadata element")
                # Stop at the following native record, rather than decoding a
                # megabyte of unrelated records for every small selected object.
                # Retain the same hard per-object limit and all original gates.
                end = min(match.start() + 1_048_576,
                          following.start() if following is not None else len(mapped))
                text = codecs.getincrementaldecoder("utf-8")().decode(
                    mapped[match.start():end], final=False)
                try:
                    element, _ = json.JSONDecoder().raw_decode(text)
                except ValueError as exc:
                    raise ValueError("Native metadata element exceeds supported bounded framing") from exc
                if f"osm/{element.get('type')}/{element.get('id')}" != ident:
                    raise ValueError("Native metadata element framing changed")
                objects[ident] = element
                match = following
        finally:
            # An unexhausted regex scanner pins mmap's exported buffer. Release
            # it on errors too, so the intended validation error is preserved.
            del matches
    if set(objects) != object_ids:
        raise ValueError("Native metadata element is missing from the frozen raw selection")
    return objects


def apply_native_metadata(*, poi_index: dict, poi_root: Path, contract_sha256: str,
                          source_pbf_sha256: str, city: str, ledger: dict) -> tuple[dict, list[dict], dict]:
    """Validate all evidence before projecting missing literal tags."""
    if not isinstance(ledger, dict) or set(ledger) != LEDGER_KEYS:
        raise ValueError("Invalid native context metadata ledger fields")
    if ledger["ledger_sha256"] != identity_digest({k: v for k, v in ledger.items() if k != "ledger_sha256"}):
        raise ValueError("Native context metadata ledger digest mismatch")
    if (ledger["schema_version"] != 1 or ledger["city"] != city
            or ledger["poi_contract_sha256"] != contract_sha256
            or ledger["source_pbf_sha256"] != source_pbf_sha256
            or not isinstance(ledger["decisions"], list)):
        raise ValueError("Native context metadata inputs changed")
    proof_path, raw_path = Path(ledger["product_proof_path"]), Path(ledger["raw_checkpoint_path"])
    if _sha(proof_path) != ledger["product_proof_sha256"]:
        raise ValueError("Native context metadata product proof changed")
    proof = json.loads(proof_path.read_text())
    if (Path(proof["product_path"]).resolve() != poi_root.resolve()
            or Path(proof["raw_native_selection_path"]).resolve() != raw_path.resolve()
            or proof["source_pbf_sha256"] != source_pbf_sha256
            or proof["raw_native_selection_sha256"] != ledger["raw_checkpoint_sha256"]
            or proof["product_file_hashes"].get(str((poi_root / "poi-contract.json").resolve())) != contract_sha256
            or proof.get("validation", {}).get("passed") is not True
            or proof["validation"].get("errors") != []
            or _sha(raw_path) != ledger["raw_checkpoint_sha256"]):
        raise ValueError("Native context metadata raw selection/product proof changed")
    features = {f["properties"]["id"]: f for f in poi_index["features"]}
    if len(features) != len(poi_index["features"]) or any(
            RESERVED_PROPERTY in f["properties"] for f in features.values()):
        raise ValueError("Duplicate or preprojected native context metadata")
    decisions, ids = ledger["decisions"], set()
    for row in decisions:
        if (not isinstance(row, dict) or set(row) != DECISION_KEYS
                or not isinstance(row["poi_id"], str) or row["poi_id"] in ids
                or row["poi_id"] != row["native_object_id"]
                or re.fullmatch(r"osm/(node|way|relation)/[1-9][0-9]*", row["poi_id"]) is None
                or not isinstance(row["tags"], dict) or not row["tags"]
                or not set(row["tags"]) <= METADATA_KEYS
                or any(not isinstance(v, str) or not v for v in row["tags"].values())):
            raise ValueError("Invalid or duplicate native context metadata decision")
        ids.add(row["poi_id"])
    objects = selected_raw_elements(raw_path, ids)
    replacements = {}
    for row in decisions:
        ident = row["poi_id"]
        feature, element = features.get(ident), objects[ident]
        if (feature is None or identity_digest(feature) != row["poi_feature_sha256"]
                or identity_digest(element) != row["native_element_sha256"]
                or any(element.get("tags", {}).get(k) != v for k, v in row["tags"].items())
                or set(row["tags"]) & set(feature["properties"].get("osm_type_tags", {}))):
            raise ValueError("Native context metadata feature/element/literal tags changed")
        metadata = {"tags": row["tags"], "native_object_id": ident,
                    "ledger_sha256": ledger["ledger_sha256"],
                    "raw_checkpoint_sha256": ledger["raw_checkpoint_sha256"],
                    "native_element_sha256": row["native_element_sha256"]}
        replacements[ident] = {**feature, "properties": {**feature["properties"], RESERVED_PROPERTY: metadata}}
    projected = {**poi_index, "features": [replacements.get(f["properties"]["id"], f)
                                           for f in poi_index["features"]]}
    return projected, list(replacements.values()), {
        "ledger_sha256": ledger["ledger_sha256"], "native_pois": len(replacements),
        "literal_tag_keys": sorted({k for r in decisions for k in r["tags"]}),
        "changes_native_geometry_type_or_source_scene": False,
    }
