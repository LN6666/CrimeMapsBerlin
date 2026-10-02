"""Source-selected native area references, separate from native type inference.

These are explicitly named, checked OSM objects whose tags do not provide a
venue type. They stay neutral reference areas, never guessed businesses,
offence/count points, legal safety zones or synthetic50m circles.
"""

from __future__ import annotations

import codecs
import hashlib
import json
import mmap
import re
from pathlib import Path

from shapely.geometry import shape

from .poi_context_identities import DECISION_KEYS, LEDGER_KEYS, identity_digest

SELECTION_KEYS = {"schema_version", "city", "inventory_digest", "poi_contract_sha256",
                  "geometry_index_sha256", "geometry_index_path", "index_proof_path",
                  "decisions", "ledger_sha256"}
REFERENCE_KEYS = (DECISION_KEYS - {"poi_feature_sha256"}) | {"native_object_sha256"}


def _sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def selected_native_objects(*, index_path: Path, proof_path: Path, expected_index_digest: str,
                            source_pbf_sha256: str, object_ids: list[str]) -> dict[str, dict]:
    """Read only selected objects from a previously validated, hash-bound index."""
    proof = json.loads(proof_path.read_text())
    if (Path(proof["index_path"]).resolve() != index_path.resolve()
            or proof["index_sha256"] != expected_index_digest
            or proof["source_pbf_sha256"] != source_pbf_sha256
            or proof.get("readback_validation") != {"passed": True, "errors": []}
            or _sha(index_path) != proof["index_file_sha256"]):
        raise ValueError("Native named reference index/proof changed")
    result = {}
    with index_path.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
        for ident in object_ids:
            token = json.dumps("id").encode() + b":" + json.dumps(ident).encode()
            pos = mapped.find(token)
            if pos < 0 or mapped.find(token, pos + len(token)) >= 0:
                raise ValueError("Native named reference object missing or ambiguous")
            start = mapped.rfind(b'{"id":', 0, pos + len(token))
            if start < 0:
                raise ValueError("Native named reference object framing changed")
            try:
                text = codecs.getincrementaldecoder("utf-8")().decode(mapped[start:start + 1_048_576], final=False)
                obj, _ = json.JSONDecoder().raw_decode(text)
            except (ValueError, UnicodeError) as exc:
                raise ValueError("Selected native object exceeds bounded supported framing") from exc
            if obj.get("id") != ident or identity_digest(obj.get("geometry")) != obj.get("geometry_sha256"):
                raise ValueError("Native named reference object/geometry digest mismatch")
            result[ident] = obj
    return result


def reference_features(*, events: list[dict], sources: list[dict], inventory: dict, geometry_ledger: dict,
                       poi_index: dict, boundary: dict, contract_sha256: str, source_pbf_sha256: str,
                       ledger: dict) -> tuple[list[dict], dict]:
    """Validate explicit selections; keep native tags/type absence and area vertices."""
    if not isinstance(ledger, dict) or set(ledger) != SELECTION_KEYS:
        raise ValueError("Invalid native named reference selection fields")
    if ledger["ledger_sha256"] != identity_digest({k: v for k, v in ledger.items() if k != "ledger_sha256"}):
        raise ValueError("Native named reference selection digest mismatch")
    if (ledger["schema_version"] != 1 or ledger["city"] != inventory["city"]
            or ledger["inventory_digest"] != inventory["inventory_digest"]
            or ledger["poi_contract_sha256"] != contract_sha256
            or ledger["geometry_index_sha256"] != geometry_ledger["geometry_index_sha256"]
            or not isinstance(ledger["decisions"], list)):
        raise ValueError("Native named reference inputs changed")
    contexts = {f"{s['scene_id']}:poi:{n}": (e, s, c) for e in events for s in e.get("scene_locations", [])
                for n, c in enumerate(s.get("poi_contexts", []), 1)}
    source_by_id = {s["source_id"]: s for s in sources}
    existing = {ident for f in poi_index["features"] for ident in
                [f["properties"]["id"], *f["properties"].get("osm_alias_object_ids", [])]}
    rows = ledger["decisions"]
    if any(not isinstance(r, dict) or set(r) != REFERENCE_KEYS for r in rows):
        raise ValueError("Invalid native named reference decision fields")
    if len({r["context_id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate native named reference context")
    if any(not isinstance(r["native_object_id"], str)
           or re.fullmatch(r"osm/(node|way|relation)/[1-9][0-9]*", r["native_object_id"]) is None for r in rows):
        raise ValueError("Invalid native named reference object ID")
    ids = sorted({r["native_object_id"] for r in rows})
    if any(i in existing for i in ids):
        raise ValueError("Native named reference duplicates an existing POI/alias or has invalid identity")
    objects = selected_native_objects(index_path=Path(ledger["geometry_index_path"]),
        proof_path=Path(ledger["index_proof_path"]), expected_index_digest=ledger["geometry_index_sha256"],
        source_pbf_sha256=source_pbf_sha256, object_ids=ids)
    border = shape(boundary["geometry"])
    features, decisions = [], []
    for ident in ids:
        obj = objects[ident]
        geometry = shape(obj["geometry"])
        if (obj.get("source_url") != f"https://www.openstreetmap.org/{ident.removeprefix('osm/')}"
                or "named_object" not in obj.get("roles", []) or not obj.get("names")
            or geometry.geom_type not in {"Polygon", "MultiPolygon"} or geometry.is_empty or not geometry.is_valid
                or not border.covers(geometry)):
            raise ValueError("Named reference needs a checked in-city native named area")
        bindings = []
        for row in (r for r in rows if r["native_object_id"] == ident):
            current = contexts.get(row["context_id"])
            source = source_by_id.get(row["source_id"])
            if current is None or source is None:
                raise ValueError("Unknown native reference context/source")
            event, scene, context = current
            quotes = row["identity_evidence_quotes"]
            if (row["native_object_sha256"] != identity_digest(obj) or row["context_sha256"] != identity_digest(context)
                    or context.get("scope") != "named_object" or event["id"] != source["source_id"]
                    or (row["source_url"], row["source_sha256"]) != (source["source_url"], source["source_sha256"])
                    or (event["source_url"], event["source_sha256"]) != (source["source_url"], source["source_sha256"])
                    or hashlib.sha256(source["source_body"].encode()).hexdigest() != source["source_sha256"]
                    or not isinstance(quotes, list) or not quotes or context.get("evidence_quote") not in quotes
                    or any(not isinstance(q, str) or not q.strip() or q not in source["source_body"] for q in quotes)
                    or not isinstance(row["review_note"], str) or len(row["review_note"].strip()) < 20):
                raise ValueError("Native named reference source/context/native choice changed")
            bindings.append({k: row[k] for k in ["context_id", "source_id", "source_url", "source_sha256", "context_sha256"]}
                            | {"source_context_kind": context["kind"], "role": scene["role"],
                               "evidence_quotes": quotes, "review_note": row["review_note"]})
        # Explicit native pedestrian typing is not a type inferred from the
        # source's proper name. Other untyped reference areas stay unchanged.
        pedestrian = obj["tags"].get("highway") == "pedestrian"
        if pedestrian and any(binding["source_context_kind"] != "pedestrian_zone" for binding in bindings):
            raise ValueError("Typed pedestrian reference needs an explicitly reviewed pedestrian-zone context")
        native_vertex = (obj["geometry"]["coordinates"][0][0] if geometry.geom_type == "Polygon"
                         else obj["geometry"]["coordinates"][0][0][0])
        feature = {"type": "Feature", "geometry": obj["geometry"], "properties": {
            "id": ident, "name": obj["tags"].get("name", obj["names"][0]), "aliases": obj["names"],
            "kind": "context", "geometry_mode": "native_named_reference_area",
            # Search/display anchor is one actual native vertex, never an event
            # point, representative count point, area centroid or safety radius.
            "center": list(native_vertex[:2]),
            "source_url": obj["source_url"], "geometry_source_id": ident,
            "geometry_source_type": geometry.geom_type, "native_type_unknown": not pedestrian,
            **({"osm_type_tags": {"highway": "pedestrian"}} if pedestrian else {}),
            "native_named_reference": {"selection_sha256": ledger["ledger_sha256"],
                "geometry_index_sha256": ledger["geometry_index_sha256"],
                "native_object_sha256": identity_digest(obj), "native_geometry_sha256": obj["geometry_sha256"],
                "native_tags": obj["tags"], "source_context_bindings": sorted(bindings, key=lambda r: r["context_id"]),
                "association": "source_reviewed_context_only", "changes_scene_geometry_or_counts": False},
        }}
        features.append(feature)
        decisions.extend({**{k: r[k] for k in DECISION_KEYS if k != "poi_feature_sha256"},
                          "poi_feature_sha256": identity_digest(feature)} for r in rows if r["native_object_id"] == ident)
    identities = {"schema_version": 1, "city": inventory["city"], "inventory_digest": inventory["inventory_digest"],
                  "poi_contract_sha256": contract_sha256, "decisions": sorted(decisions, key=lambda r: r["context_id"])}
    identities["ledger_sha256"] = identity_digest(identities)
    return features, identities


def merge_identity_ledgers(ledgers: list[dict]) -> dict:
    """Combine independently hash-checked selections before a single projection."""
    if not ledgers:
        raise ValueError("No named identity ledgers supplied")
    for ledger in ledgers:
        if (set(ledger) != LEDGER_KEYS
                or ledger["ledger_sha256"] != identity_digest({k: v for k, v in ledger.items() if k != "ledger_sha256"})):
            raise ValueError("Named identity merge needs intact ledgers")
        if any(ledger[k] != ledgers[0][k] for k in ["schema_version", "city", "inventory_digest", "poi_contract_sha256"]):
            raise ValueError("Named identity ledgers have different input bindings")
    core = {k: ledgers[0][k] for k in ["schema_version", "city", "inventory_digest", "poi_contract_sha256"]}
    core["decisions"] = sorted([r for ledger in ledgers for r in ledger["decisions"]], key=lambda r: r["context_id"])
    if len({r["context_id"] for r in core["decisions"]}) != len(core["decisions"]):
        raise ValueError("Duplicate context across named identity ledgers")
    return {**core, "ledger_sha256": identity_digest(core)}
