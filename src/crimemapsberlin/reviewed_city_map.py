"""Build an ignored city-map candidate from hash-bound LLM decision ledgers.

The source, scene, category, primary-count and geometry choices are all
supplied by hash-bound LLM decisions. This module performs deterministic
identity checks, GIS assembly, monthly hex aggregation and browser packaging.
It never assigns a category or location, grants owner approval, or publishes
the generated data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from shapely.geometry import shape

from .map_decisions import _count_point, _validate_inputs, displayable_article
from .native_poi_metadata import RESERVED_PROPERTY, apply_native_metadata
from .native_poi_references import merge_identity_ledgers, reference_features
from .payload import canonical_events, compact
from .poi_cities import POI_CITY_SPECS
from .poi_context import context_compatibility_digest
from .poi_context_identities import apply_reviewed_identities
from .poi_street_contexts import RESERVED_FIELDS as STREET_RESERVED_FIELDS
from .poi_street_contexts import apply_street_contexts
from .reviewed_map_display import apply_reviewed_display, copy_display_resources
from .reviewed_poi_product import validate_reviewed_poi_product
from .source_review_pack import read_checkpoint
from .spatial import build_months, metric_transforms
from .tiles import tiles

LOCAL_STATUS = "local_map_candidate_unapproved"
SOURCE_STATUS = "source_geometry_map_decision_coverage_verified_not_full_acceptance"
CANDIDATE_FORMAT_VERSION = 2


def _json_bytes(value: object) -> bytes:
    return json.dumps(compact(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _load(path: Path, label: str) -> dict:
    if not path.is_file():
        raise ValueError(f"{label} does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value) + b"\n")


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


def _verify_poi_product(
    *, city: str, poi_root: Path, catalog_path: Path,
    reviewed_binding: dict | None = None, inventory_digest: str | None = None,
) -> tuple[dict, dict, dict, dict, dict]:
    contract = _load(poi_root / "poi-contract.json", "POI contract")
    validation = _load(poi_root / "validation.json", "POI validation")
    boundary = _load(poi_root / "boundary.geojson", "municipal boundary")
    index = _load(poi_root / "poi-index.json", "POI index")
    search = json.loads((poi_root / "search.json").read_text(encoding="utf-8"))
    catalog = _load(catalog_path, "POI category catalog")
    if reviewed_binding is not None:
        validation = validate_reviewed_poi_product(
            city=city, poi_root=poi_root, catalog_path=catalog_path,
            binding=reviewed_binding, inventory_digest=inventory_digest,
        )
    spec = POI_CITY_SPECS.get(city)
    if spec is None:
        raise ValueError(f"Unsupported city: {city}")
    features = index.get("features")
    if index.get("type") != "FeatureCollection" or not isinstance(features, list):
        raise ValueError("POI index is not a FeatureCollection")
    if any("native_named_reference" in f.get("properties", {}) for f in features):
        raise ValueError("Native named references require separate source-bound selections, not a base POI flag")
    if any(RESERVED_PROPERTY in f.get("properties", {}) for f in features):
        raise ValueError("Native context metadata requires a separately validated ledger, not a base POI flag")
    if not isinstance(search, list) or not isinstance(catalog.get("poi_types"), dict):
        raise TypeError("POI search or category catalog is invalid")
    if (
        contract.get("schema_version") != 2
        or contract.get("city") != city
        or contract.get("epsg") != spec.epsg
        or contract.get("status") != "local_poi_only_unpublished"
        or contract.get("publication_ready", False) is not False
    ):
        raise ValueError("POI contract does not match the local-only city contract")
    if validation.get("passed") is not True or validation.get("errors") != []:
        raise ValueError("POI read-back validation has not passed")
    if contract.get('validation_binding_version') == 1 and (
        validation.get('poi_index_sha256') != hashlib.sha256((poi_root / 'poi-index.json').read_bytes()).hexdigest()
        or validation.get('poi_search_sha256') != hashlib.sha256((poi_root / 'search.json').read_bytes()).hexdigest()
    ):
        raise ValueError('POI index/search changed after independent read-back')
    if (
        validation.get("poi_count") != len(features)
        or contract.get("poi_count") != len(features)
        or validation.get("epsg") != spec.epsg
        or validation.get("source_sha256") != contract.get("source_pbf_sha256")
        or boundary.get("source_pbf_sha256") != contract.get("source_pbf_sha256")
        or validation.get("boundary_source_id") != contract.get("boundary_source_id")
        or boundary.get("id") != contract.get("boundary_source_id")
        or contract.get("catalog_sha256") != hashlib.sha256(catalog_path.read_bytes()).hexdigest()
    ):
        raise ValueError("POI product files disagree")
    border = shape(boundary.get("geometry"))
    if border.is_empty or not border.is_valid:
        raise ValueError("Municipal boundary is empty or invalid")
    tile_keys = contract.get("tile_index", {}).get("pois")
    if not isinstance(tile_keys, list) or tile_keys != sorted(set(tile_keys)):
        raise ValueError("POI tile contract is invalid")
    for key in tile_keys:
        if not isinstance(key, str) or not (poi_root / "pois" / f"{key}.json").is_file():
            raise ValueError(f"POI tile is missing: {key}")
    actual_tiles = {f"{path.parent.name}/{path.stem}" for path in (poi_root / "pois").glob("*/*.json")}
    if actual_tiles != set(tile_keys):
        raise ValueError("POI tile files differ from the validated contract")
    return contract, validation, boundary, catalog, index


def _published(value: object, *, timezone_name: str | None = None) -> datetime:
    if not isinstance(value, str):
        raise TypeError("Official publication timestamp must be a string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid official publication timestamp: {value}") from exc
    if parsed.tzinfo is None:
        if timezone_name is None:
            raise ValueError("Official publication timestamp needs a timezone")
        zone = ZoneInfo(timezone_name)
        localized = parsed.replace(tzinfo=zone)
        if (
            localized.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != parsed
            or parsed.replace(tzinfo=zone, fold=0).utcoffset()
            != parsed.replace(tzinfo=zone, fold=1).utcoffset()
        ):
            raise ValueError("Publication timestamp is ambiguous or nonexistent in the chosen timezone")
        return localized
    return parsed


def _geometry_rows(geometry_ledger: dict) -> dict[str, dict]:
    result = {}
    for row in geometry_ledger.get("decisions", []):
        location_id = row.get("request", {}).get("location_id") if isinstance(row, dict) else None
        if not isinstance(location_id, str) or location_id in result:
            raise ValueError("Geometry ledger has a missing or duplicate location ID")
        result[location_id] = row
    if len(result) != geometry_ledger.get("request_count"):
        raise ValueError("Geometry ledger request count is inconsistent")
    return result


def _map_rows(map_ledger: dict) -> dict[str, dict]:
    result = {}
    for row in map_ledger.get("decisions", []):
        decision = row.get("decision") if isinstance(row, dict) else None
        source_id = decision.get("source_id") if isinstance(decision, dict) else None
        if not isinstance(source_id, str) or source_id in result:
            raise ValueError("Map ledger has a missing or duplicate source ID")
        if row.get("map_decision_sha256") != _digest(decision):
            raise ValueError(f"Map decision hash mismatch: {source_id}")
        result[source_id] = decision
    return result


def _verify_map_ledger(map_ledger: dict) -> None:
    core = {
        key: map_ledger.get(key)
        for key in (
            "schema_version",
            "city",
            "inventory_digest",
            "geometry_ledger_sha256",
            "decisions",
        )
    }
    if map_ledger.get("ledger_sha256") != _digest(core):
        raise ValueError("Map decision ledger digest does not match its current contents")


def _scene(
    location: dict,
    geometry_row: dict | None,
    incidents: dict[str, dict],
    incident_categories: dict[str, str],
    primary_location_id: str | None,
) -> dict:
    if any(
        "reviewed_object_ids" in context or "native_identity_review" in context or set(context) & STREET_RESERVED_FIELDS
        for context in location.get("poi_contexts", [])
    ):
        raise ValueError("Native POI projections require the separately validated identity ledger or street context ledger")
    location_id = location["location_id"]
    derived = geometry_row.get("derived_geometry") if geometry_row else None
    decision = geometry_row.get("decision", {}) if geometry_row else {}
    geometry = derived.get("geometry") if isinstance(derived, dict) else None
    primary = location_id == primary_location_id
    reference_only = isinstance(derived, dict) and str(derived.get("geometry_usage", "")).endswith("reference_only")
    coordinates = None
    water_reference = decision.get("method") == "osm_water_footprint_reference"
    official_reference = decision.get("method") == "official_district_footprint_reference"
    if official_reference and primary:
        raise ValueError("official district reference cannot be a primary count scene")
    if water_reference and primary:
        raise ValueError("water footprint reference cannot be a primary count scene")
    if decision.get("method") == "osm_station_footprint_reference" and primary:
        raise ValueError("station footprint reference cannot be a primary count scene")
    junction_reference = isinstance(derived, dict) and derived.get("geometry_usage") == "source_junction_reference_only"
    road_reference = isinstance(derived, dict) and derived.get("geometry_usage") == "source_road_reference_only"
    collection_reference = isinstance(derived, dict) and derived.get("geometry_usage") == "source_native_collection_reference_only"
    if collection_reference and primary:
        raise ValueError("native collection reference cannot be a primary count scene")
    if junction_reference and primary:
        raise ValueError("junction reference cannot be a primary count scene")
    if road_reference and primary:
        raise ValueError("road reference cannot be a primary count scene")
    if primary and reference_only:
        raise ValueError(f"Display reference cannot be a primary count location: {location_id}")
    if isinstance(derived, dict) and derived.get("type") == "Point" and not reference_only:
        coordinates = list(derived["geometry"]["coordinates"][:2])
    elif primary:
        coordinates = _count_point(geometry_row)
    incident_ids = [
        ident
        for ident, incident in incidents.items()
        if location_id in incident.get("formal_location_ids", [])
    ]
    method = decision.get("method") if decision.get("verdict") == "resolved" else "none"
    scene = {
        "scene_id": location_id,
        "label": location["label"],
        "role": location["role"],
        "location_precision": location["precision"],
        "geocode_method": method,
        "coordinates": coordinates,
        "geometry": geometry,
        "primary_for_count": primary,
        "evidence_quote": location["evidence_quotes"][0],
        "incident_ids": incident_ids,
        "incident_categories": sorted(
            {incident_categories[ident] for ident in incident_ids if ident in incident_categories}
        ),
        "location_scope": location["city_scope"],
        "location_object_ids": (derived.get("source_object_ids", []) if isinstance(derived, dict) else []),
        "geometry_sha256": (derived.get("geometry_sha256") if isinstance(derived, dict) else None),
    }
    scene["incidents"] = [
        {
            key: value
            for key, value in {
                "incident_id": ident,
                "category": incident_categories.get(ident),
                "event_time": incidents[ident].get("event_time"),
                "details": incidents[ident].get("details"),
            }.items()
            if value is not None
        }
        for ident in incident_ids
    ]
    for key in ("event_time", "details", "transit_route", "poi_contexts", "poi_review", "transit_review"):
        if key in location:
            scene[key] = location[key]
    if geometry_row:
        scene["geometry_review"] = {
            "verdict": decision.get("verdict"),
            "method": method,
            "review_note": decision.get("review_note", ""),
        }
    if isinstance(derived, dict):
        if "road_under_bridge_reference" in derived:
            scene["road_under_bridge_reference"] = derived["road_under_bridge_reference"]
        if "rail_crossing_reference" in derived:
            scene["rail_crossing_reference"] = derived["rail_crossing_reference"]
        if derived.get("source_reference_ids"):
            scene["source_reference_ids"] = derived["source_reference_ids"]
            scene["source_reference_provenance"] = derived["source_reference_provenance"]
        for key in ("native_platform_count", "native_platform_sources", "actual_platform_side_known",
                    "native_park_sources", "park_reference_identity", "source_document_binding",
                    "static_road_reference", "coordinates_generated", "source_platform_side_known",
                    "static_scene_reference", "actual_static_scene_extent_known", "source_attachment_url",
                    "source_attachment_sha256", "height_known", "full_legal_definition_verified",
                    "geodesic_model", "radius_metres", "complete_park_boundary_known",
                    "source_document_id", "source_object_groups"):
            if key in derived:
                scene[key] = derived[key]
        usage = derived.get("geometry_usage")
        if isinstance(usage, str) and usage.endswith("reference_only"):
            scene["geometry_usage"] = usage
            if derived.get("actual_event_position_known") is False:
                scene["actual_event_position_known"] = False
            if derived.get("actual_event_extent_known") is False:
                scene["actual_event_extent_known"] = False
            if derived.get("actual_non_transit_extent_known") is False:
                scene["actual_non_transit_extent_known"] = False
        if (usage in {"source_road_reference_only", "carrier_line_reference_only", "source_transit_corridor_reference_only"}
                and derived.get("actual_non_transit_extent_known") is not False):
            scene["complete_transit_line"] = False
        if derived.get("source_road_extent") in {"native_endpoint_bounded", "native_bridge_outline_bounded"}:
            scene["source_road_extent"] = derived["source_road_extent"]
        if usage == "carrier_line_reference_only" or derived.get("actual_transit_extent_known") is False:
            scene["actual_transit_extent_known"] = False
        if usage == "source_transit_corridor_reference_only":
            scene["service_identity_known"] = False
    return scene


def _event_time_basis(incidents: dict[str, dict], published: datetime) -> tuple[str | None, str, str]:
    dates = [
        incident.get("event_time", {}).get("date")
        for incident in incidents.values()
        if isinstance(incident.get("event_time"), dict)
    ]
    known = [value for value in dates if isinstance(value, str)]
    unique = set(known)
    if incidents and len(known) == len(incidents) and len(unique) == 1:
        event_date = known[0]
        return event_date, event_date[:7], "reviewed_incident_time"
    if known:
        return (
            None,
            published.strftime("%Y-%m"),
            "mixed_reviewed_event_times_publication_month_filter",
        )
    return None, published.strftime("%Y-%m"), "event_time_unknown_publication_month_filter"


def _prepare_events(
    *,
    city: str,
    source_rows: list[dict],
    inventory: dict,
    geometry_ledger: dict,
    map_ledger: dict,
    publication_timezone: str | None = None,
    month_basis: str = "reviewed_incident_time",
) -> tuple[list[dict], Counter, datetime]:
    if month_basis not in {"reviewed_incident_time", "publication_month"}:
        raise ValueError("Unknown map month filter basis")
    _validate_inputs(inventory, geometry_ledger, city)
    if (
        inventory.get("city") != city
        or not inventory.get("all_current_reviews_supported")
        or geometry_ledger.get("city") != city
        or geometry_ledger.get("inventory_digest") != inventory.get("inventory_digest")
        or geometry_ledger.get("geometry_review_complete") is not True
        or map_ledger.get("city") != city
        or map_ledger.get("inventory_digest") != inventory.get("inventory_digest")
        or map_ledger.get("geometry_ledger_sha256") != geometry_ledger.get("ledger_sha256")
        or map_ledger.get("map_review_complete") is not True
        or map_ledger.get("pending_count") != 0
    ):
        raise ValueError("Reviewed map inputs are stale or incomplete")
    _verify_map_ledger(map_ledger)
    sources = {row["source_id"]: row for row in source_rows}
    if len(sources) != len(source_rows):
        raise ValueError("Source checkpoint has duplicate IDs")
    _geometry_rows(geometry_ledger)
    map_decisions = _map_rows(map_ledger)
    expected = {
        article["source_id"]
        for article in inventory.get("articles", [])
        if displayable_article(inventory, article)
    }
    if set(map_decisions) != expected:
        raise ValueError("Map ledger does not cover every current mappable article")

    events = []
    audit: Counter = Counter()
    latest = None
    for article in inventory.get("articles", []):
        scope = article.get("scope_verdict")
        if not displayable_article(inventory, article):
            audit[f"excluded_scope:{scope}"] += 1
            continue
        source_id = article["source_id"]
        source = sources.get(source_id)
        decision = map_decisions[source_id]
        if (
            source is None
            or source["source_sha256"] != article["source_sha256"]
            or source["source_sha256"] != decision["source_sha256"]
            or article["decision_sha256"] != decision["source_review_sha256"]
        ):
            raise ValueError(f"Map inputs disagree for source {source_id}")
        published = _published(source["published"], timezone_name=publication_timezone)
        latest = published if latest is None or published > latest else latest
        incident_categories = {row["incident_id"]: row["category"] for row in decision["incident_categories"]}
        incidents = {
            row["incident_id"]: row for row in article.get("incidents", [])
        }
        geometry_locations = {
            row["request"]["location_id"]: row
            for row in geometry_ledger.get("decisions", [])
            if row.get("request", {}).get("source_id") == source_id
        }
        scenes = [
            _scene(
                location,
                geometry_locations.get(location["location_id"]),
                incidents,
                incident_categories,
                decision["primary_count_location_id"],
            )
            for location in article.get("formal_locations", [])
        ]
        primaries = [scene for scene in scenes if scene["primary_for_count"]]
        if len(primaries) > 1:
            raise ValueError(f"Multiple primary scenes survived validation: {source_id}")
        primary = primaries[0] if primaries else None
        coordinates = primary["coordinates"] if primary else None
        if primary and coordinates is None:
            raise ValueError(f"Primary scene lost its checked count point: {source_id}")
        event_date, month, time_basis = _event_time_basis(incidents, published)
        if month_basis == "publication_month":
            month = published.strftime("%Y-%m")
        event = {
            "id": source_id,
            "title": source["title"],
            "category": decision["article_category"],
            "is_crime_report": decision["is_crime_report"],
            "published_at": published.isoformat(),
            "event_date": event_date,
            "month": month,
            "time_basis": time_basis,
            "month_basis": month_basis,
            "published_at_source_literal": source["published"],
            "published_at_timezone_basis": publication_timezone or "explicit_source_offset",
            "source_url": source["source_url"],
            "feed_url": source["source_url"],
            "source_status": (
                "frozen_owner_batch_decision_coverage_verified_not_full_acceptance"
                if inventory.get("coverage", {}).get("scope") == "frozen_owner_batch_not_full_crime_inventory"
                else SOURCE_STATUS
            ),
            "source_scope_verdict": scope,
            "source_sha256": source["source_sha256"],
            "source_revision": source["revision"],
            "source_review_sha256": article["decision_sha256"],
            "map_decision_sha256": _digest(decision),
            "coordinates": coordinates,
            "location_precision": primary["location_precision"] if primary else "unknown",
            "location_label": primary["label"] if primary else "",
            "location_scope": "in_city" if primary else "no_countable_primary_scene",
            "geocode_method": primary["geocode_method"] if primary else "none",
            "geocode_candidates": [],
            "geocode_version": "source-bound-llm-geometry-ledger-1",
            "location_object_ids": primary["location_object_ids"] if primary else [],
            "geocode_evidence": [primary["evidence_quote"]] if primary else [],
            "poi_mentions": [],
            "mention_basis": "none_without_source_verified_venue_object",
            "outcome": "unknown",
            "scene_locations": scenes,
            "incident_count": article["incident_count"],
            "incident_categories": decision["incident_categories"],
            "classification_evidence_quotes": decision["classification_evidence_quotes"],
            "map_review_note": decision["review_note"],
            "source_incidents": article["incidents"],
        }
        for key in ("source_reference_binding", "source_attachment_binding", "source_document_binding"):
            if key in article:
                event[key] = article[key]
        if "source_supporting_material_binding" in article:
            from .supporting_material_reviews import visible_materials
            event["source_supporting_materials"] = visible_materials(
                article["source_supporting_material_binding"],
                source={"id": source["source_id"], "url": source["source_url"],
                        "body": source["source_body"], "sha256": source["source_sha256"]},
            )
            event["public_display_fields"] = ["source_supporting_materials"]
        events.append(event)
        audit["events"] += 1
        if scope == "uncertain":
            audit["retained_uncertain_scope_articles"] += 1
        audit["incidents"] += article["incident_count"]
        audit["formal_locations"] += len(scenes)
        audit["primary_count_points"] += int(primary is not None)
        audit["resolved_display_geometries"] += sum(scene["geometry"] is not None for scene in scenes)
        audit["unresolved_display_locations"] += sum(scene["geometry"] is None for scene in scenes)
    if latest is None:
        raise ValueError("Reviewed city map has no mappable articles")
    return canonical_events(events), audit, latest


def build_candidate(
    *,
    city: str,
    source_db: Path,
    inventory_path: Path,
    geometry_ledger_path: Path,
    map_ledger_path: Path,
    poi_root: Path,
    catalog_path: Path,
    output: Path,
    poi_context_identities_path: Path | None = None,
    poi_reference_selections_path: Path | None = None,
    poi_native_metadata_path: Path | None = None,
    poi_street_contexts_path: Path | None = None,
    reviewed_poi_binding_path: Path | None = None,
    reviewed_display_path: Path | None = None,
    publication_timezone: str | None = None,
    month_basis: str = "reviewed_incident_time",
) -> dict:
    """Assemble a local candidate; decision coverage is not full acceptance."""
    inventory = _load(inventory_path, "scene inventory")
    geometry_ledger = _load(geometry_ledger_path, "geometry ledger")
    map_ledger = _load(map_ledger_path, "map decision ledger")
    source_rows, source_coverage = read_checkpoint(source_db)
    if (
        not source_coverage.get("channel_scan_complete")
        or source_coverage.get("missing_bodies") != 0
        or source_coverage.get("source_errors") != 0
    ):
        raise ValueError("Official source checkpoint is incomplete")
    contract, validation, boundary, catalog, poi_index = _verify_poi_product(
        city=city, poi_root=poi_root, catalog_path=catalog_path,
        reviewed_binding=_load(reviewed_poi_binding_path, "reviewed POI binding") if reviewed_poi_binding_path else None,
        inventory_digest=inventory["inventory_digest"],
    )
    events, counts, latest = _prepare_events(
        city=city,
        source_rows=source_rows,
        inventory=inventory,
        geometry_ledger=geometry_ledger,
        map_ledger=map_ledger,
        publication_timezone=publication_timezone, month_basis=month_basis,
    )
    display = None
    if reviewed_display_path is not None:
        display = _load(reviewed_display_path, "reviewed display annotations")
        apply_reviewed_display(events, display, inventory=inventory, geometry_ledger=geometry_ledger, map_ledger=map_ledger)
    poi_contract_digest = hashlib.sha256((poi_root / "poi-contract.json").read_bytes()).hexdigest()
    identity_review = None
    identity_ledgers = []
    named_references = []
    reference_selections = None
    if poi_context_identities_path is not None:
        identity_ledgers.append(_load(poi_context_identities_path, "named POI identity ledger"))
    if poi_reference_selections_path is not None:
        reference_selections = _load(poi_reference_selections_path, "native named reference selections")
        named_references, reference_identities = reference_features(
            events=events, sources=source_rows, inventory=inventory, geometry_ledger=geometry_ledger,
            poi_index=poi_index, boundary=boundary, contract_sha256=poi_contract_digest,
            source_pbf_sha256=contract["source_pbf_sha256"], ledger=reference_selections,
        )
        if named_references and "context" not in catalog["poi_types"]:
            raise ValueError("Native named reference neutral category is absent from the reviewed catalog")
        poi_index = {**poi_index, "features": [*poi_index["features"], *named_references]}
        identity_ledgers.append(reference_identities)
    if identity_ledgers:
        events, identity_review = apply_reviewed_identities(
            events=events, source_rows=source_rows, inventory=inventory, poi_index=poi_index,
            poi_contract_sha256=poi_contract_digest,
            ledger=merge_identity_ledgers(identity_ledgers),
        )
    metadata_review, metadata_features = None, []
    if poi_native_metadata_path is not None:
        poi_index, metadata_features, metadata_review = apply_native_metadata(
            poi_index=poi_index, poi_root=poi_root, contract_sha256=poi_contract_digest,
            source_pbf_sha256=contract["source_pbf_sha256"], city=city,
            ledger=_load(poi_native_metadata_path, "native context metadata ledger"))
    extra_tiles = tiles([compact(f) for f in named_references]) if named_references else {}
    tile_keys = sorted(set(contract["tile_index"]["pois"]) | {f"context/{key}" for key in extra_tiles})
    spec = POI_CITY_SPECS[city]
    to_metric, to_wgs = metric_transforms(spec.epsg)
    street_review = None
    if poi_street_contexts_path is not None:
        if metadata_review is None:
            raise ValueError("Street context requires separately validated native address metadata")
        events, street_review = apply_street_contexts(events=events, sources=source_rows, inventory=inventory,
            geometry_ledger=geometry_ledger, poi_index=poi_index, contract_sha256=poi_contract_digest,
            metadata_sha256=metadata_review["ledger_sha256"], source_pbf_sha256=contract["source_pbf_sha256"],
            to_metric=to_metric, ledger=_load(poi_street_contexts_path, "source-reviewed street context ledger"))
    months = build_months(
        events,
        poi_index,
        to_metric=to_metric,
        to_wgs=to_wgs,
        include_legacy_links=False,
        validated_context_memberships={f["properties"]["id"]: f["properties"]["context_kinds"]
            for f in poi_index["features"] if "context_kinds" in f["properties"]}
            if reviewed_poi_binding_path is not None else None,
    )
    if sum(len(value["event_ids"]) for value in months.values()) != len(events):
        raise ValueError("Monthly candidate files do not cover every mappable article")
    links = [link for value in months.values() for link in value["links"]]
    if any(
        not link.get("status", "").startswith("context_")
        or link.get("mention_basis") != "source_reviewed_context_only"
        for link in links
    ):
        raise ValueError("Reviewed candidate contains a non-contextual POI association")

    matching_policy_digest = context_compatibility_digest()
    boundary_digest = hashlib.sha256((poi_root / "boundary.geojson").read_bytes()).hexdigest()
    producer_digest = hashlib.sha256(b"".join((Path(__file__).parent / name).read_bytes()
        for name in ("reviewed_city_map.py", "reviewed_map_display.py", "reviewed_poi_product.py", "spatial.py"))).hexdigest()
    signature = hashlib.sha256(
        (
            f"reviewed-city-map-v{CANDIDATE_FORMAT_VERSION}:"
            f"{inventory['inventory_digest']}:{geometry_ledger['ledger_sha256']}:"
            f"{map_ledger['ledger_sha256']}:{poi_contract_digest}:{matching_policy_digest}:{boundary_digest}"
            + f":display:{_digest(display)}:month-basis:{month_basis}:timezone:{publication_timezone}:producer:{producer_digest}"
            + (f":reviewed-poi-binding:{hashlib.sha256(reviewed_poi_binding_path.read_bytes()).hexdigest()}" if reviewed_poi_binding_path else "")
            + (f":named-poi-identities:{identity_review['ledger_sha256']}" if identity_review else "")
            + (f":native-named-references:{reference_selections['ledger_sha256']}" if reference_selections else "")
            + (f":native-context-metadata:{metadata_review['ledger_sha256']}" if metadata_review else "")
            + (f":native-street-contexts:{street_review['ledger_sha256']}" if street_review else "")
        ).encode()
    ).hexdigest()[:16]
    generation_timestamp = latest.astimezone(UTC).strftime("%Y%m%dT%H%M%S")
    generation = f"{signature}-{generation_timestamp}"
    excluded_scope = {
        key.split(":", 1)[1]: value
        for key, value in sorted(counts.items())
        if key.startswith("excluded_scope:")
    }
    manifest = {
        "schema_version": 2,
        "city": spec.name,
        "retrieved_at": latest.astimezone(UTC).isoformat(),
        "generation": generation,
        "status": LOCAL_STATUS,
        "coverage": {
            "discovered": source_coverage["discovered"],
            "fetched": source_coverage["bodies_in_pack"],
            "failed": source_coverage["source_errors"],
            "pending": source_coverage["missing_bodies"],
        },
        "months": {month: {"count": len(value["event_ids"])} for month, value in months.items()},
        "categories": sorted({event["category"] for event in events}),
        "tile_index": {"pois": tile_keys, "roads": []},
        "tile_size": contract["tile_size"],
        "catalog": catalog,
        "zones": {"places": [], "features": [], "geometry_status": "not_applicable"},
        "metadata": {
            "source": "official police announcement archive",
            "semantic_basis": "source_first_hash_bound_llm_review",
            "coverage_scope": inventory.get("coverage", {}).get("scope", "source_checkpoint_not_full_crime_inventory"),
            "time_basis": "reviewed_incident_time_or_explicit_publication_month_fallback",
            "month_filter_basis": month_basis,
            "producer_sha256": producer_digest,
            "publication_timezone_display_assumption": publication_timezone,
            "count_unit": "at_most_one_reviewed_announcement_primary",
            "hex_crs": f"EPSG:{spec.epsg}",
            "hex_edge_m": [1100, 275],
            "zoom_threshold": 13,
            "attribution": "© OpenStreetMap contributors / Geofabrik (ODbL); source police publishers",
            "boundary_source_id": boundary["id"],
            "boundary_sha256": boundary_digest,
            "poi_count": len(poi_index["features"]),
            "base_native_typed_poi_count": validation["poi_count"],
            "source_selected_native_reference_count": len(named_references),
            "native_reference_selection_sha256": reference_selections["ledger_sha256"] if reference_selections else None,
            "poi_contract_sha256": poi_contract_digest,
            "poi_context_compatibility_sha256": matching_policy_digest,
            "named_poi_identity_review": identity_review,
            "native_context_metadata_review": metadata_review,
            "native_street_context_review": street_review,
            "source_inventory_sha256": inventory["inventory_digest"],
            "geometry_ledger_sha256": geometry_ledger["ledger_sha256"],
            "map_decision_ledger_sha256": map_ledger["ledger_sha256"],
            "mappable_articles": len(events),
            "excluded_scope_counts": excluded_scope,
            "retained_uncertain_scope_articles": counts["retained_uncertain_scope_articles"],
            "primary_count_points": counts["primary_count_points"],
            "unresolved_display_locations": counts["unresolved_display_locations"],
            "poi_association_basis": "source_reviewed_context_only",
            "candidate_format_version": CANDIDATE_FORMAT_VERSION,
            "review_status": "DECISION_COVERAGE_VERIFIED_INDEPENDENT_ACCEPTANCE_REQUIRED",
            "independent_technical_acceptance": "not_established_by_this_builder",
            "decision_coverage_does_not_imply_precise_geometry": True,
        },
        "owner_approved": False,
        "publication_ready": False,
        "publication_blocks": [
            "independent_full_technical_acceptance_not_established_by_builder",
            "owner_map_inspection_and_approval_missing",
        ],
    }
    audit = {
        "city": city,
        "status": LOCAL_STATUS,
        "generation": generation,
        "source_coverage": source_coverage,
        "inventory_digest": inventory["inventory_digest"],
        "geometry_ledger_sha256": geometry_ledger["ledger_sha256"],
        "map_decision_ledger_sha256": map_ledger["ledger_sha256"],
        "mappable_articles": len(events),
        "excluded_scope_counts": excluded_scope,
        "retained_uncertain_scope_articles": counts["retained_uncertain_scope_articles"],
        "incidents": counts["incidents"],
        "formal_locations": counts["formal_locations"],
        "resolved_display_geometries": counts["resolved_display_geometries"],
        "unresolved_display_locations": counts["unresolved_display_locations"],
        "primary_count_points": counts["primary_count_points"],
        "categories": dict(sorted(Counter(event["category"] for event in events).items())),
        "months": len(months),
        "poi_count": len(poi_index["features"]),
        "base_native_typed_poi_count": validation["poi_count"],
        "source_selected_native_reference_count": len(named_references),
        "native_reference_selection_sha256": reference_selections["ledger_sha256"] if reference_selections else None,
        "poi_tiles": len(tile_keys),
        "poi_associations": len(links),
        "named_poi_identity_review": identity_review,
        "native_context_metadata_review": metadata_review,
        "native_street_context_review": street_review,
        "owner_approved": False,
        "publication_ready": False,
        "publication_blocks": manifest["publication_blocks"],
    }
    if display is not None:
        manifest["metadata"].update(display["metadata"])
        for key in ("source_reference_review_url", "historical112_service_review_url"):
            if key in manifest["metadata"]:
                manifest["metadata"][key] = f"{generation}/{manifest['metadata'][key]}"
        manifest["publication_blocks"] = sorted(
            set(manifest["publication_blocks"] + display["publication_blocks"])
        )
        audit["publication_blocks"] = manifest["publication_blocks"]
        audit["reviewed_display_sha256"] = _digest(display)
    audit["candidate_digest"] = _digest({"manifest": manifest, "audit": audit})

    output = output.resolve()
    staging = output.with_name(f".{output.name}.building")
    shutil.rmtree(staging, ignore_errors=True)
    generation_root = staging / generation
    if display is not None:
        copy_display_resources(display, generation_root)
    for month, value in months.items():
        _write_json(
            generation_root / "months" / f"{month}.json",
            {**value, "events": [event for event in events if event["month"] == month]},
        )
    shutil.copytree(poi_root / "pois", generation_root / "pois", copy_function=_link_or_copy)
    shutil.copy2(poi_root / "search.json", generation_root / "search.json")
    for key, additional in extra_tiles.items():
        path = generation_root / "pois" / "context" / f"{key}.json"
        existing = _load(path, "base neutral POI tile")["features"] if path.exists() else []
        value = {"type": "FeatureCollection", "features": sorted(
            [*existing, *additional["features"]], key=lambda f: f["properties"]["id"])}
        # Existing tiles may be hardlinked to the protected base product.
        # Atomic replacement gives the candidate its own inode before editing.
        temporary = path.with_suffix(".merging")
        _write_json(temporary, value)
        os.replace(temporary, path)
    # Patch every affected tile after copying; never mutate hardlinked base
    # tiles. Geometry, stable IDs, palette and search anchors stay unchanged.
    for kind in sorted({f["properties"]["kind"] for f in metadata_features}):
        for key, updates in tiles([compact(f) for f in metadata_features if f["properties"]["kind"] == kind]).items():
            path = generation_root / "pois" / kind / f"{key}.json"
            value = _load(path, "base POI metadata tile")
            replacements = {f["properties"]["id"]: f for f in updates["features"]}
            current_ids = {f["properties"]["id"] for f in value["features"]}
            if not set(replacements) <= current_ids:
                raise ValueError("Native metadata projection changed base tile membership")
            value["features"] = [replacements.get(f["properties"]["id"], f) for f in value["features"]]
            temporary = path.with_suffix(".metadata")
            _write_json(temporary, value)
            os.replace(temporary, path)
    if named_references:
        search_path = generation_root / "search.json"
        search = json.loads(search_path.read_text()) + [
            {k: compact(f["properties"][k]) for k in ("id", "name", "aliases", "kind", "center")}
            for f in named_references]
        _write_json(search_path, sorted(search, key=lambda row: row["id"]))
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
    parser.add_argument("--city", choices=sorted(POI_CITY_SPECS), required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--geometry-ledger", type=Path, required=True)
    parser.add_argument("--map-ledger", type=Path, required=True)
    parser.add_argument("--poi-root", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=Path("data/safety/europe_sources.json"))
    parser.add_argument("--poi-context-identities", type=Path)
    parser.add_argument("--poi-reference-selections", type=Path)
    parser.add_argument("--poi-native-metadata", type=Path)
    parser.add_argument("--poi-street-contexts", type=Path)
    parser.add_argument("--reviewed-poi-binding", type=Path)
    parser.add_argument("--reviewed-display", type=Path)
    parser.add_argument("--publication-timezone", choices=["Europe/Berlin"])
    parser.add_argument("--month-basis", choices=["reviewed_incident_time", "publication_month"], default="reviewed_incident_time")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    runtime = (Path.cwd() / ".runtime").resolve()
    if not args.out.resolve().is_relative_to(runtime):
        parser.error("Reviewed city map candidates must remain under .runtime/")
    result = build_candidate(
        city=args.city,
        source_db=args.db,
        inventory_path=args.inventory,
        geometry_ledger_path=args.geometry_ledger,
        map_ledger_path=args.map_ledger,
        poi_root=args.poi_root,
        catalog_path=args.catalog,
        output=args.out,
        poi_context_identities_path=args.poi_context_identities,
        poi_reference_selections_path=args.poi_reference_selections,
        poi_native_metadata_path=args.poi_native_metadata,
        poi_street_contexts_path=args.poi_street_contexts,
        reviewed_poi_binding_path=args.reviewed_poi_binding, reviewed_display_path=args.reviewed_display,
        publication_timezone=args.publication_timezone, month_basis=args.month_basis,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
