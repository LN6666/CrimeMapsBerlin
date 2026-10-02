"""Build an ignored, unapproved Munich map candidate from POLIZEIKARTE.

The owner accepted POLIZEIKARTE's classifications and locations as Munich's
semantic basis. This module performs only integrity and GIS work: it verifies
the complete source checkpoint and validated POI product, checks upstream
coordinates against the municipal boundary, withholds nonpoint and out-of-city
representatives from counts, and writes a browser-shaped local candidate. It
does not reinterpret reports, grant owner approval, or publish files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from shapely.geometry import Point, shape

from .payload import canonical_events, compact
from .polizeikarte_munich import candidate_snapshot
from .spatial import build_months, metric_transforms

CITY = "munich"
EPSG = 25832
SEMANTIC_BASIS = "owner_accepted_polizeikarte_upstream"
LOCAL_STATUS = "local_map_candidate_unapproved"
SCAN_ID = re.compile(r"^(\d{8}T\d{6})(?:\.\d+)?Z$")


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        compact(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _load_json(path: Path) -> object:
    if not path.is_file():
        raise ValueError(f"Required local input is missing: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Required local input is invalid JSON: {path}") from exc


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value) + b"\n")


def _scan_timestamp(scan_id: str) -> tuple[str, str]:
    match = SCAN_ID.fullmatch(scan_id)
    if match is None:
        raise ValueError("Munich POLIZEIKARTE scan ID has an unexpected format")
    parsed = datetime.strptime(match.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
    return parsed.isoformat(), match.group(1)


def _verify_poi_product(poi_root: Path) -> tuple[dict, dict, dict]:
    contract = _load_json(poi_root / "poi-contract.json")
    validation = _load_json(poi_root / "validation.json")
    boundary = _load_json(poi_root / "boundary.geojson")
    index = _load_json(poi_root / "poi-index.json")
    search = _load_json(poi_root / "search.json")
    if not all(isinstance(value, dict) for value in (contract, validation, boundary, index)):
        raise TypeError("Munich POI product has an invalid top-level value")
    if not isinstance(search, list):
        raise TypeError("Munich POI search index is invalid")
    features = index.get("features")
    if index.get("type") != "FeatureCollection" or not isinstance(features, list):
        raise ValueError("Munich POI index is not a FeatureCollection")
    if (
        contract.get("schema_version") != 2
        or contract.get("city") != CITY
        or contract.get("epsg") != EPSG
        or contract.get("status") != "local_poi_only_unpublished"
        or contract.get("publication_ready", False) is not False
    ):
        raise ValueError("Munich POI contract does not match the local-only city contract")
    if validation.get("passed") is not True or validation.get("errors") != []:
        raise ValueError("Munich POI read-back validation has not passed")
    if (
        validation.get("poi_count") != len(features)
        or contract.get("poi_count") != len(features)
        or validation.get("epsg") != EPSG
        or validation.get("source_sha256") != contract.get("source_pbf_sha256")
        or boundary.get("source_pbf_sha256") != contract.get("source_pbf_sha256")
        or validation.get("boundary_source_id") != contract.get("boundary_source_id")
        or boundary.get("id") != contract.get("boundary_source_id")
    ):
        raise ValueError("Munich POI product files disagree")
    try:
        border = shape(boundary["geometry"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Munich municipal boundary is invalid") from exc
    if border.is_empty or not border.is_valid:
        raise ValueError("Munich municipal boundary is empty or invalid")
    tile_keys = contract.get("tile_index", {}).get("pois")
    if not isinstance(tile_keys, list) or tile_keys != sorted(set(tile_keys)):
        raise ValueError("Munich POI tile contract is invalid")
    for key in tile_keys:
        if not isinstance(key, str) or not (poi_root / "pois" / f"{key}.json").is_file():
            raise ValueError(f"Munich POI tile is missing: {key}")
    actual_tiles = {
        f"{path.parent.name}/{path.stem}" for path in (poi_root / "pois").glob("*/*.json")
    }
    if actual_tiles != set(tile_keys):
        raise ValueError("Munich POI tile files differ from the validated contract")
    return contract, validation, boundary


def _prepare_events(events: list[dict], boundary: dict) -> tuple[list[dict], Counter]:
    border = shape(boundary["geometry"])
    counts: Counter = Counter()
    prepared = []
    seen = set()
    for source_event in events:
        event = dict(source_event)
        event_id = event.get("id")
        if not isinstance(event_id, str) or event_id in seen:
            raise ValueError("Munich candidate has a missing or duplicate event ID")
        seen.add(event_id)
        if event.get("semantic_basis") != SEMANTIC_BASIS:
            raise ValueError(f"Munich candidate lacks the accepted semantic basis: {event_id}")
        precision = event.get("location_precision")
        if precision not in {"street", "district", "city"}:
            raise ValueError(f"Munich candidate has an unknown location precision: {event_id}")
        upstream = event.get("upstream_coordinates")
        point = None
        if upstream is not None:
            if (
                not isinstance(upstream, list)
                or len(upstream) != 2
                or any(type(value) not in {int, float} for value in upstream)
            ):
                raise ValueError(f"Munich candidate has invalid upstream coordinates: {event_id}")
            point = Point(upstream)
        if point is None:
            scope = "unresolved_no_upstream_coordinate"
        elif border.covers(point):
            scope = "in_city"
        else:
            scope = "outside_city"
        counts[(precision, scope)] += 1
        candidate_point = event.get("coordinates")
        if candidate_point is not None and (
            precision != "street" or upstream is None or candidate_point != upstream
        ):
            raise ValueError(f"Munich count point differs from upstream precision: {event_id}")
        if candidate_point is not None and scope != "in_city":
            event["coordinates"] = None
            event["geocode_method"] = "polizeikarte_upstream_outside_city_withheld"
        event["location_scope"] = scope
        event["count_unit"] = "polizeikarte_entry"
        event["incident_basis"] = SEMANTIC_BASIS
        event["mention_basis"] = "no_upstream_verified_venue_object"
        event["poi_mentions"] = []
        prepared.append(event)
    return canonical_events(prepared), counts


def _link_or_copy(source: str, destination: str) -> None:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _replace_directory(staging: Path, target: Path) -> None:
    backup = target.with_name(f".{target.name}.previous")
    shutil.rmtree(backup, ignore_errors=True)
    if target.exists():
        target.replace(backup)
    try:
        staging.replace(target)
    except Exception:
        if backup.exists() and not target.exists():
            backup.replace(target)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def build_candidate(
    *, source_db: Path, poi_root: Path, catalog_path: Path, output: Path
) -> dict:
    """Build the complete local candidate while keeping publication blocked."""
    events, source_audit = candidate_snapshot(source_db)
    if (
        source_audit.get("archive_complete") is not True
        or source_audit.get("coverage", {}).get("active") != len(events)
        or source_audit.get("review_basis") != SEMANTIC_BASIS
        or source_audit.get("source_first_llm_rereview_required") is not False
    ):
        raise ValueError("Munich source checkpoint is not a complete accepted snapshot")
    contract, validation, boundary = _verify_poi_product(poi_root)
    catalog = _load_json(catalog_path)
    if not isinstance(catalog, dict) or not isinstance(catalog.get("poi_types"), dict):
        raise TypeError("POI category catalog is invalid")
    if contract.get("catalog_sha256") != hashlib.sha256(catalog_path.read_bytes()).hexdigest():
        raise ValueError("POI category catalog changed after the Munich POI build")

    prepared, scope_counts = _prepare_events(events, boundary)
    to_metric, to_wgs = metric_transforms(EPSG)
    months = build_months(
        prepared, {"type": "FeatureCollection", "features": []},
        to_metric=to_metric, to_wgs=to_wgs,
    )
    if sum(len(value["event_ids"]) for value in months.values()) != len(prepared):
        raise ValueError("Munich monthly candidate files do not cover every upstream entry")
    if any(value["links"] for value in months.values()):
        raise ValueError("Munich candidate unexpectedly inferred a POI association")

    point_count = sum(bool(event.get("coordinates")) for event in prepared)
    expected_points = scope_counts[("street", "in_city")]
    if point_count != expected_points:
        raise ValueError("Munich count points differ from boundary-checked street entries")
    retrieved_at, generation_timestamp = _scan_timestamp(source_audit["scan_id"])
    source_digest = _digest(prepared)
    poi_contract_digest = hashlib.sha256((poi_root / "poi-contract.json").read_bytes()).hexdigest()
    boundary_digest = hashlib.sha256((poi_root / "boundary.geojson").read_bytes()).hexdigest()
    signature = hashlib.sha256(
        f"{source_audit['signature']}:{source_digest}:{poi_contract_digest}:{boundary_digest}".encode()
    ).hexdigest()[:16]
    generation = f"{signature}-{generation_timestamp}"
    precision_scope = {
        f"{precision}:{scope}": count
        for (precision, scope), count in sorted(scope_counts.items())
    }
    known_outside = sum(
        count for (precision, scope), count in scope_counts.items() if scope == "outside_city"
    )
    no_coordinate = sum(
        count
        for (precision, scope), count in scope_counts.items()
        if scope == "unresolved_no_upstream_coordinate"
    )
    in_city_nonpoint = sum(
        count
        for (precision, scope), count in scope_counts.items()
        if scope == "in_city" and precision != "street"
    )
    manifest = {
        "schema_version": 2,
        "city": "München",
        "retrieved_at": retrieved_at,
        "generation": generation,
        "status": LOCAL_STATUS,
        "coverage": {
            "discovered": len(prepared),
            "fetched": len(prepared),
            "failed": 0,
            "pending": 0,
        },
        "last_completed_sync": {
            "scan_id": source_audit["scan_id"],
            "window_days": 365,
            "source_signature": source_audit["signature"],
        },
        "months": {
            month: {"count": len(value["event_ids"])}
            for month, value in months.items()
        },
        "categories": sorted({event["category"] for event in prepared}),
        "tile_index": {
            "pois": contract["tile_index"]["pois"],
            "roads": [],
        },
        "tile_size": contract["tile_size"],
        "catalog": catalog,
        "zones": {"places": [], "features": [], "geometry_status": "not_applicable"},
        "metadata": {
            "source": "POLIZEIKARTE Munich rolling 365-day dataset",
            "upstream_provider": "POLIZEIKARTE",
            "provider_kind": "independent_project_linking_police_reports",
            "semantic_basis": SEMANTIC_BASIS,
            "source_first_llm_rereview_required": False,
            "time_basis": "polizeikarte_occurrence_date",
            "count_unit": "polizeikarte_entry",
            "hex_crs": f"EPSG:{EPSG}",
            "hex_edge_m": [1100, 275],
            "zoom_threshold": 13,
            "attribution": "© OpenStreetMap contributors / Geofabrik (ODbL); POLIZEIKARTE; source police publishers",
            "boundary_source_id": boundary["id"],
            "boundary_sha256": boundary_digest,
            "poi_count": validation["poi_count"],
            "poi_contract_sha256": poi_contract_digest,
            "point_entries_in_city": point_count,
            "known_outside_municipality": known_outside,
            "nonpoint_entries_withheld": in_city_nonpoint + no_coordinate,
            "poi_association_basis": "none_without_upstream_verified_venue_object",
            "review_status": "OWNER_ACCEPTED_UPSTREAM_SEMANTICS_AWAITING_MAP_APPROVAL",
        },
        "owner_approved": False,
        "publication_ready": False,
        "publication_blocks": ["owner_map_inspection_and_approval_missing"],
    }
    audit = {
        "city": CITY,
        "status": LOCAL_STATUS,
        "generation": generation,
        "source_scan_id": source_audit["scan_id"],
        "source_signature": source_audit["signature"],
        "source_event_digest": source_digest,
        "semantic_basis": SEMANTIC_BASIS,
        "source_first_llm_rereview_required": False,
        "events": len(prepared),
        "months": len(months),
        "categories": dict(sorted(Counter(event["category"] for event in prepared).items())),
        "precision_scope": precision_scope,
        "point_entries_in_city": point_count,
        "known_outside_municipality": known_outside,
        "without_count_point": len(prepared) - point_count,
        "in_city_nonpoint_representatives_withheld": in_city_nonpoint,
        "without_upstream_coordinate": no_coordinate,
        "poi_count": validation["poi_count"],
        "poi_tiles": len(contract["tile_index"]["pois"]),
        "poi_associations": 0,
        "owner_approved": False,
        "publication_ready": False,
        "publication_blocks": manifest["publication_blocks"],
    }
    audit["candidate_digest"] = _digest({"manifest": manifest, "audit": audit})

    output = output.resolve()
    staging = output.with_name(f".{output.name}.building")
    shutil.rmtree(staging, ignore_errors=True)
    generation_root = staging / generation
    for month, value in months.items():
        _write_json(
            generation_root / "months" / f"{month}.json",
            {
                **value,
                "events": [event for event in prepared if event["month"] == month],
            },
        )
    shutil.copytree(
        poi_root / "pois", generation_root / "pois", copy_function=_link_or_copy
    )
    shutil.copy2(poi_root / "search.json", generation_root / "search.json")
    shutil.copy2(poi_root / "boundary.geojson", generation_root / "boundary.geojson")
    _write_json(
        generation_root / "roads-overview.json",
        {"type": "FeatureCollection", "features": []},
    )
    _write_json(staging / "manifest.json", manifest)
    _write_json(staging / "build-audit.json", audit)
    _replace_directory(staging, output)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", type=Path,
        default=Path(".runtime/safety/cities/munich/police.sqlite"),
    )
    parser.add_argument(
        "--poi-root", type=Path,
        default=Path(".runtime/safety/poi-cities/cities/munich"),
    )
    parser.add_argument(
        "--catalog", type=Path, default=Path("data/safety/europe_sources.json")
    )
    parser.add_argument(
        "--out", type=Path,
        default=Path(".runtime/safety/cities/munich/map-candidate"),
    )
    args = parser.parse_args()
    runtime = (Path.cwd() / ".runtime").resolve()
    if not args.out.resolve().is_relative_to(runtime):
        parser.error("Munich map candidates must remain under .runtime/")
    result = build_candidate(
        source_db=args.db,
        poi_root=args.poi_root,
        catalog_path=args.catalog,
        output=args.out,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
