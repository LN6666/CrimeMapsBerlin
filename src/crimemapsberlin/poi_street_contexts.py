"""Source-reviewed whole-street address context, never offence attribution.

The prior scene review supplies the street/type/scope. Native addr:street
supplies an address relationship, not a business identity. Competing same-name
roads disambiguate geography using native geometry; no invented radius/point.
Bounded segments, intersections and unknown locations do not enter this path.
"""

from __future__ import annotations

import codecs
import hashlib
import json
import mmap
import re
from pathlib import Path

from shapely.geometry import shape
from shapely.ops import transform, unary_union
from shapely.strtree import STRtree

from .payload import compact
from .poi_context import matches_reviewed_context
from .poi_context_identities import identity_digest

LEDGER_KEYS = {"schema_version", "city", "inventory_digest", "geometry_ledger_sha256",
               "poi_contract_sha256", "native_metadata_sha256", "geometry_index_sha256",
               "geometry_index_path", "index_proof_path", "decisions", "ledger_sha256"}
DECISION_KEYS = {"context_id", "source_id", "source_url", "source_sha256", "context_sha256",
                 "geometry_request_sha256", "street_names", "evidence_quotes"}
SPELLING_KEYS = {"source_street_spellings", "street_spelling_review_note"}
RESERVED_FIELDS = {"reviewed_street_poi_ids", "native_street_review"}


def _sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def indexed_street_roads(*, index_path: Path, proof_path: Path, expected_digest: str,
                         source_pbf_sha256: str, street_names: set[str] | None,
                         required_ids: set[str]) -> dict[str, dict]:
    """One header-filtered pass; decode only native street roads/required IDs.

    Completeness includes competing same-name roads, not just source choices.
    The full scene index is not parsed into a Python object or recompiled.
    """
    proof = json.loads(proof_path.read_text())
    if (Path(proof["index_path"]).resolve() != index_path.resolve()
            or proof["index_sha256"] != expected_digest
            or proof["source_pbf_sha256"] != source_pbf_sha256
            or proof.get("readback_validation") != {"passed": True, "errors": []}
            or _sha(index_path) != proof["index_file_sha256"]):
        raise ValueError("Street context native index/proof changed")
    framing = re.compile(rb'\{"id":"(osm/(?:node|way|relation)/[1-9][0-9]*)",')
    decoder, result = json.JSONDecoder(), {}
    with index_path.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
        for match in framing.finditer(mapped):
            ident = match[1].decode()
            if ident not in required_ids:
                if ident.startswith("osm/node/"):
                    continue
                prefix = codecs.getincrementaldecoder("utf-8")().decode(
                    mapped[match.start():match.start() + 4096], final=False)
                try:
                    roles, _ = decoder.raw_decode(prefix[prefix.index('"roles":') + 8:])
                    names, _ = decoder.raw_decode(prefix[prefix.index('"names":') + 8:])
                except ValueError as exc:
                    raise ValueError("Street context native header framing changed") from exc
                if "road" not in roles or (street_names is not None and not set(names) & street_names):
                    continue
            end = mapped.find(b'},{"id":"osm/', match.end())
            size = min(1_048_576, end - match.start() + 1) if end >= 0 else 1_048_576
            text = codecs.getincrementaldecoder("utf-8")().decode(
                mapped[match.start():match.start() + size], final=False)
            try:
                obj, _ = decoder.raw_decode(text)
            except ValueError as exc:
                raise ValueError("Street context native object framing exceeded bound") from exc
            if obj.get("id") != ident or identity_digest(obj.get("geometry")) != obj.get("geometry_sha256"):
                raise ValueError("Street context native object/geometry changed")
            road = ("road" in obj.get("roles", []) and obj.get("dimension") == "line"
                    and obj.get("tags", {}).get("highway") and obj["tags"].get("name")
                    and obj["geometry"].get("type") in {"LineString", "MultiLineString"})
            if ident in required_ids or (road and (street_names is None or obj["tags"]["name"] in street_names)):
                if ident in result:
                    raise ValueError("Duplicate native street road identity")
                result[ident] = obj
    if not required_ids <= set(result):
        raise ValueError("Source-selected street road is missing from native index")
    return result


def apply_street_contexts(*, events: list[dict], sources: list[dict], inventory: dict,
                          geometry_ledger: dict, poi_index: dict, contract_sha256: str,
                          metadata_sha256: str, source_pbf_sha256: str,
                          to_metric, ledger: dict) -> tuple[list[dict], dict]:
    """Project address candidates only after full source/native/scope binding."""
    if not isinstance(ledger, dict) or set(ledger) != LEDGER_KEYS:
        raise ValueError("Invalid street context ledger fields")
    if ledger["ledger_sha256"] != identity_digest({k: v for k, v in ledger.items() if k != "ledger_sha256"}):
        raise ValueError("Street context ledger digest mismatch")
    if (ledger["schema_version"] != 1 or ledger["city"] != inventory["city"]
            or ledger["inventory_digest"] != inventory["inventory_digest"]
            or ledger["geometry_ledger_sha256"] != geometry_ledger["ledger_sha256"]
            or ledger["geometry_index_sha256"] != geometry_ledger["geometry_index_sha256"]
            or ledger["poi_contract_sha256"] != contract_sha256
            or ledger["native_metadata_sha256"] != metadata_sha256
            or not isinstance(ledger["decisions"], list)):
        raise ValueError("Street context inputs changed")
    contexts = {f"{s['scene_id']}:poi:{n}": (e, s, c) for e in events for s in e.get("scene_locations", [])
                for n, c in enumerate(s.get("poi_contexts", []), 1)}
    source_by_id = {s["source_id"]: s for s in sources}
    geometry_by_id = {r["request"]["location_id"]: r for r in geometry_ledger["decisions"]}
    selected_ids, seen, names = set(), set(), set()
    for row in ledger["decisions"]:
        if (not isinstance(row, dict) or set(row) not in (DECISION_KEYS, DECISION_KEYS | SPELLING_KEYS)
                or row["context_id"] in seen):
            raise ValueError("Invalid or duplicate street context decision")
        seen.add(row["context_id"])
        current = contexts.get(row["context_id"])
        source = source_by_id.get(row["source_id"])
        if current is None or source is None:
            raise ValueError("Unknown street context source/scene")
        event, scene, context = current
        geometry = geometry_by_id[scene["scene_id"]]
        derived = geometry.get("derived_geometry") or {}
        quotes, streets = row["evidence_quotes"], row["street_names"]
        spellings = row.get("source_street_spellings", {})
        if (not isinstance(spellings, dict) or (SPELLING_KEYS <= set(row) and (
                set(spellings) != set(streets) or not isinstance(row["street_spelling_review_note"], str)
                or len(row["street_spelling_review_note"].strip()) < 20
                or any(not isinstance(spelling, str) or not spelling.strip() for spelling in spellings.values())))):
            raise ValueError("Street spelling needs an explicit source/native-bound review")
        if (set(context) & RESERVED_FIELDS or context.get("scope") != "along_geometry"
                or context.get("association") != "source_reviewed_context_only"
                or scene.get("location_precision") != "street" or scene.get("geocode_method") != "osm_line"
                or derived.get("geometry_usage") or scene.get("geometry_usage")
                or derived.get("source_road_extent") or scene.get("source_road_extent")
                or derived.get("type") not in {"LineString", "MultiLineString"}
                or scene.get("geometry") != compact(derived["geometry"])
                or event["id"] != source["source_id"]
                or (event.get("source_url"), event.get("source_sha256")) != (row["source_url"], row["source_sha256"])
                or (source["source_url"], source["source_sha256"]) != (row["source_url"], row["source_sha256"])
                or hashlib.sha256(source["source_body"].encode()).hexdigest() != source["source_sha256"]
                or identity_digest(context) != row["context_sha256"]
                or geometry["request"]["geometry_request_sha256"] != row["geometry_request_sha256"]
                or not isinstance(streets, list) or not streets or streets != sorted(set(streets))
                or any(not isinstance(name, str) or not name.strip() for name in streets)
                or not isinstance(quotes, list) or not quotes or context.get("evidence_quote") not in quotes
                or any(not isinstance(q, str) or not q.strip() or q not in source["source_body"] for q in quotes)
                or any(not any(spellings.get(name, name) in q for q in quotes) for name in streets)):
            raise ValueError("Street context source/type/scope/geometry evidence changed")
        selected_ids.update(derived["source_object_ids"])
        names.update(streets)
    roads = indexed_street_roads(index_path=Path(ledger["geometry_index_path"]),
        proof_path=Path(ledger["index_proof_path"]), expected_digest=ledger["geometry_index_sha256"],
        source_pbf_sha256=source_pbf_sha256, street_names=names, required_ids=selected_ids)
    roads_by_name = {name: [o for o in roads.values() if o.get("dimension") == "line"
        and o.get("tags", {}).get("name") == name and "road" in o.get("roles", [])] for name in names}
    trees = {name: STRtree([transform(to_metric, shape(o["geometry"])) for o in values])
             for name, values in roads_by_name.items()}
    by_id = {f["properties"]["id"]: f for f in poi_index["features"]}
    addresses = {name: [] for name in names}
    for f in poi_index["features"]:
        metadata = f["properties"].get("native_context_metadata", {})
        name = metadata.get("tags", {}).get("addr:street")
        if name in addresses and metadata.get("ledger_sha256") == metadata_sha256:
            addresses[name].append(f)
    projections, results = {}, []
    for row in ledger["decisions"]:
        event, scene, context = contexts[row["context_id"]]
        derived = geometry_by_id[scene["scene_id"]]["derived_geometry"]
        ids = set(derived["source_object_ids"])
        if any(roads[i].get("dimension") != "line" or "road" not in roads[i].get("roles", []) for i in ids):
            raise ValueError("Street context reference includes a non-road object")
        if not unary_union([shape(roads[i]["geometry"]) for i in ids]).equals(shape(derived["geometry"])):
            raise ValueError("Street context source-selected road union changed")
        selected_names = {roads[i].get("tags", {}).get("name") for i in ids}
        if not set(row["street_names"]) <= selected_names:
            raise ValueError("Street context name does not belong to its source-selected native roads")
        matches, ambiguous = {}, []
        for name in row["street_names"]:
            for feature in addresses[name]:
                props = feature["properties"]
                if not matches_reviewed_context(context["kind"], props, by_id):
                    continue
                actual = transform(to_metric, shape(feature.get("location_geometry", feature["geometry"])))
                nearest, distances = trees[name].query_nearest(actual, all_matches=True, return_distance=True)
                nearest_ids = sorted(roads_by_name[name][int(i)]["id"] for i in nearest)
                if not nearest_ids or not set(nearest_ids) <= ids:
                    ambiguous.append(props["id"])
                    continue
                metadata = props["native_context_metadata"]
                matches[props["id"]] = {"street_name": name, "nearest_native_road_ids": nearest_ids,
                    "native_distance_m": float(min(distances)), "native_address_object_id": metadata["native_object_id"],
                    "native_element_sha256": metadata["native_element_sha256"]}
        review = {"context_id": row["context_id"], "ledger_sha256": ledger["ledger_sha256"],
            "native_metadata_sha256": metadata_sha256, "source_url": row["source_url"],
            "source_sha256": row["source_sha256"], "source_scene_geometry_sha256": scene["geometry_sha256"],
            "geometry_request_sha256": row["geometry_request_sha256"], "evidence_quotes": row["evidence_quotes"],
            "association": "source_reviewed_whole_street_address_context_only",
            "does_not_locate_or_count_scene": True, "matched_native_addresses": matches}
        if spellings := row.get("source_street_spellings"):
            review.update(source_street_spellings=spellings, street_spelling_review_note=row["street_spelling_review_note"])
        projections[row["context_id"]] = {**context, "reviewed_street_poi_ids": sorted(matches), "native_street_review": review}
        results.append({"context_id": row["context_id"], "street_names": row["street_names"],
            "matched_native_address_ids": sorted(matches), "rejected_other_same_name_road_or_ambiguous_ids": sorted(set(ambiguous))})
    projected = [{**e, "scene_locations": [{**s, "poi_contexts": [
        projections.get(f"{s['scene_id']}:poi:{n}", c) for n, c in enumerate(s.get("poi_contexts", []), 1)]}
        if "poi_contexts" in s else s for s in e.get("scene_locations", [])]} for e in events]
    return projected, {"ledger_sha256": ledger["ledger_sha256"], "decisions": len(results),
        "native_address_candidates": sum(len(r["matched_native_address_ids"]) for r in results),
        "results": results, "changes_source_scene_geometry_time_role_count": False,
        "same_name_native_road_disambiguation": "all_nearest_native_parts_must_belong_to_reviewed_source_street",
        "does_not_cover_missing_native_address_tags_or_unreviewed_frontage": True}
