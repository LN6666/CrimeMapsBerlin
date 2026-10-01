"""Read back an explicitly reviewed POI product with multiple type memberships.

This checks files, native records, authored choices and browser tiles. It never
classifies a facility, resolves an unnamed police venue or approves publication.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from pathlib import Path

from shapely.geometry import Point, shape

from .payload import compact
from .poi_cities import POI_CITY_SPECS, geometry_covered_by
from .tiles import DX, DY

_OSM_ID = re.compile(r"^osm/(node|way|relation)/(\d+)$")


def _read(path: Path) -> dict:
    return json.loads(path.read_text())


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_reviewed_poi_product(
    *, city: str, poi_root: Path, catalog_path: Path, binding: dict, inventory_digest: str
) -> dict:
    """Require current file hashes and independently check all display payloads."""
    if (
        binding.get("schema_version") != 1
        or binding.get("city") != city
        or binding.get("inventory_digest") != inventory_digest
        or binding.get("status") != "local_reviewed_context_membership_candidate_unpublished"
        or binding.get("owner_approved") is not False
        or binding.get("publication_ready") is not False
    ):
        raise ValueError("Stale or invalid reviewed POI product binding")
    paths = {
        "poi_index_sha256": poi_root / "poi-index.json",
        "poi_contract_sha256": poi_root / "poi-contract.json",
        "catalog_sha256": catalog_path,
    }
    for key, path in paths.items():
        if _sha(path) != binding.get(key):
            raise ValueError(f"Stale reviewed POI file: {key}")
    refs = binding.get("review_files", {})
    documents = {}
    for key in ("native_policy", "native_choices", "native_records"):
        ref = refs.get(key)
        if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
            raise ValueError(f"Missing individually reviewed POI evidence: {key}")
        path = Path(ref["path"])
        if _sha(path) != ref["sha256"]:
            raise ValueError(f"Stale native POI evidence: {key}")
        documents[key] = _read(path)
    policy, choices, raw = (documents[k] for k in ("native_policy", "native_choices", "native_records"))
    if (
        policy.get("raw_capture_sha256") != refs["native_records"]["sha256"]
        or choices.get("policy_sha256") != refs["native_policy"]["sha256"]
        or binding.get("native_taxonomy_policy_sha256") != refs["native_policy"]["sha256"]
        or any(d.get("city") != city for d in documents.values())
        or policy.get("source_pbf_sha256") != binding.get("source_pbf_sha256")
        or raw.get("source_pbf_sha256") != binding.get("source_pbf_sha256")
    ):
        raise ValueError("Native POI review files disagree")
    records = {r["object_id"]: r for r in raw["records"]}
    selected = {r["object_id"]: r for r in choices["choices"]}
    if (
        len(records) != len(raw["records"])
        or len(selected) != len(choices["choices"])
        or records.keys() != selected.keys()
    ):
        raise ValueError("Native POI choices do not cover unique captured objects")
    for ident, record in records.items():
        if (
            _digest({k: v for k, v in record.items() if k != "native_record_sha256"})
            != record["native_record_sha256"]
            or selected[ident]["native_record_sha256"] != record["native_record_sha256"]
            or record.get("source_pbf_sha256") != binding["source_pbf_sha256"]
        ):
            raise ValueError(f"Stale individually reviewed native POI record: {ident}")
    contract, boundary = _read(poi_root / "poi-contract.json"), _read(poi_root / "boundary.geojson")
    catalog, index = _read(catalog_path), _read(poi_root / "poi-index.json")
    spec = POI_CITY_SPECS[city]
    if (
        contract.get("schema_version") != 2
        or contract.get("city") != city
        or contract.get("epsg") != spec.epsg
        or contract.get("tile_size") != [DX, DY]
        or contract.get("status") != "local_poi_only_unpublished"
        or contract.get("publication_ready") is not False
        or contract.get("catalog_sha256") != binding["catalog_sha256"]
        or contract.get("source_pbf_sha256") != binding["source_pbf_sha256"]
        or boundary.get("source_pbf_sha256") != binding["source_pbf_sha256"]
        or boundary.get("id") != contract.get("boundary_source_id")
        or contract.get("native_followup_policy_sha256") != refs["native_policy"]["sha256"]
        or contract.get("native_followup_choices_sha256") != refs["native_choices"]["sha256"]
    ):
        raise ValueError("Reviewed POI contract disagrees with source, city or authored choices")
    border = shape(boundary["geometry"])
    if border.is_empty or not border.is_valid or index.get("type") != "FeatureCollection":
        raise ValueError("Invalid reviewed POI index or municipal boundary")
    features = index["features"]
    by_id = {}
    expected = defaultdict(list)
    counts = defaultdict(int)
    for feature in features:
        p = feature["properties"]
        ident = p["id"]
        osm_match = _OSM_ID.fullmatch(ident)
        if (
            not osm_match
            or ident in by_id
            or p.get("source_url") != f"https://www.openstreetmap.org/{osm_match[1]}/{osm_match[2]}"
        ):
            raise ValueError("Missing, duplicate or foreign reviewed POI object")
        kinds = p.get("context_kinds")
        if (
            not isinstance(kinds, list)
            or kinds != sorted(set(kinds))
            or not kinds
            or p["kind"] not in kinds
            or not set(kinds) <= catalog["poi_types"].keys()
        ):
            raise ValueError(f"Invalid explicitly reviewed POI memberships: {ident}")
        display, actual = shape(feature["geometry"]), shape(feature["location_geometry"])
        center = Point(p["center"])
        if (
            display.is_empty
            or not display.is_valid
            or actual.is_empty
            or not actual.is_valid
            or not geometry_covered_by(border, display)
            or not geometry_covered_by(border, actual)
            or center.is_empty
            or not center.is_valid
            or not border.covers(center)
        ):
            raise ValueError(f"Reviewed POI geometry escaped the city or became invalid: {ident}")
        added = p.get("native_type_addition_binding")
        if added is not None:
            chosen = selected.get(ident)
            if (
                chosen is None
                or added.get("record_sha256") != records[ident]["native_record_sha256"]
                or added.get("policy_sha256") != refs["native_policy"]["sha256"]
                or added.get("source_pbf_sha256") != binding["source_pbf_sha256"]
                or added.get("kinds") != chosen["context_kinds_to_add"]
                or not set(added["kinds"]) <= set(kinds)
                or added.get("mapped_reference_only") is not True
                or added.get("source_venue_identity_verified") is not False
                or added.get("whole_compound_or_legal_boundary_verified") is not False
            ):
                raise ValueError(f"Unreviewed or upgraded native POI membership: {ident}")
        public = compact({k: v for k, v in feature.items() if k != "location_geometry"})
        by_id[ident] = public
        xmin, ymin, xmax, ymax = shape(public["geometry"]).bounds
        for kind in kinds:
            counts[kind] += 1
            for x in range(math.floor(xmin / DX), math.floor(xmax / DX) + 1):
                for y in range(math.floor(ymin / DY), math.floor(ymax / DY) + 1):
                    expected[f"{kind}/{x}_{y}"].append(ident)
    for ident, choice in selected.items():
        if choice["context_kinds_to_add"] and (
            ident not in by_id or not by_id[ident]["properties"].get("native_type_addition_binding")
        ):
            raise ValueError(f"Individually selected native POI additions are missing their binding: {ident}")
    if len(features) != contract.get("poi_count") or len(features) != binding.get("poi_count"):
        raise ValueError("Reviewed POI object count disagrees with bound input")
    expected_search = [
        {k: p[k] for k in ("id", "name", "aliases", "kind", "context_kinds", "center")}
        for f in features
        if (p := f["properties"])["name"] != p["kind"]
    ]
    if json.loads((poi_root / "search.json").read_text()) != compact(expected_search):
        raise ValueError("Reviewed POI search differs from current unique index")
    keys = sorted(expected)
    actual_keys = sorted(f"{p.parent.name}/{p.stem}" for p in (poi_root / "pois").glob("*/*.json"))
    if contract.get("tile_index", {}).get("pois") != keys or actual_keys != keys:
        raise ValueError("Reviewed POI tile files disagree with actual geometry memberships")
    for key in keys:
        tile = _read(poi_root / "pois" / f"{key}.json")
        if tile.get("type") != "FeatureCollection" or tile.get("features") != [
            by_id[i] for i in expected[key]
        ]:
            raise ValueError(f"Reviewed POI tile differs from its current index: {key}")
    return {
        "passed": True,
        "errors": [],
        "city": city,
        "epsg": spec.epsg,
        "source_sha256": binding["source_pbf_sha256"],
        "boundary_source_id": boundary["id"],
        "poi_count": len(features),
        "context_memberships": dict(sorted(counts.items())),
        "tile_count": len(keys),
        "publication_ready": False,
        "owner_approved": False,
    }
