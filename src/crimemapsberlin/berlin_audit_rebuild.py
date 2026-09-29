"""Legacy Berlin audit-migration diagnostic.

This adapter predates the owner's six-rule per-article re-review.  It cannot
prove explicit event-time, transit and POI review for all 1,100 articles and its
output must not be presented as the corrected candidate or completion evidence.
It remains available only to reproduce the invalidated migration diagnostic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from shapely.geometry import Point, shape

from .city_geometry_index import normalized_name as osm_name
from .geometry_decisions import _derived_geometry, compile_geometry_decisions
from .location_text import normalize
from .map_decisions import compile_map_decisions
from .reviewed_city_map import build_candidate
from .source_review_pack import read_checkpoint

CITY = "berlin"
SCHEMA_VERSION = 1
REVIEWER = "Codex Berlin audit migration"
MIGRATION_REVIEWED_AT = "2026-09-29T19:30:00+09:00"
COUNT_ROLES = {"incident", "accident"}
BERLIN_DISTRICTS = {
    "Mitte",
    "Friedrichshain-Kreuzberg",
    "Pankow",
    "Charlottenburg-Wilmersdorf",
    "Spandau",
    "Steglitz-Zehlendorf",
    "Tempelhof-Schöneberg",
    "Neukölln",
    "Treptow-Köpenick",
    "Marzahn-Hellersdorf",
    "Lichtenberg",
    "Reinickendorf",
    "bezirksübergreifend",
    "berlinweit",
}
CATEGORY_MAP = {
    "Bedrohung": "gewalt",
    "Betrug": "betrug",
    "Betäubungsmittel": "drogen",
    "Brand": "brand",
    "Diebstahl": "diebstahl",
    "Drogen": "drogen",
    "Einbruch": "einbruch",
    "Eigentumsdelikt": "diebstahl",
    "Gewalt": "gewalt",
    "Raub": "raub",
    "Sachbeschädigung": "sonstige",
    "Sexualdelikt": "sexualdelikte",
    "Unklassifiziert": "sonstige",
    "Verkehr / sonstige Meldung": "verkehr",
    "Waffendelikt": "sonstige",
}
POI_TERMS = {
    "attraction": ("museum", "sehenswürd", "denkmal", "attraktion"),
    "bar": (" bar", "kneipe", "pub", "gaststätte"),
    "cafe": ("café", "cafe"),
    "fast_food": ("imbiss", "snack", "fast food"),
    "hotel": ("hotel", "herberge", "hostel"),
    "marketplace": ("markt", "marktplatz"),
    "nightclub": ("club", "diskothek", "nachtclub"),
    "park": ("park", "grünanlage", "grünfläche"),
    "parking": ("parkplatz", "parkhaus", "parkfläche"),
    "restaurant": ("restaurant", "lokal"),
    "shop": ("geschäft", "laden", "supermarkt", "kiosk", "verkaufsfiliale"),
    "station": ("bahnhof", "haltestelle", "station"),
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON root must be an object: {path}")
    return value


def _write(path: Path, value: object, *, pretty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    if pretty:
        data = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode()
    else:
        data = _json_bytes(value)
    temporary.write_bytes(data + b"\n")
    temporary.replace(path)


def _normalized(value: str) -> str:
    return " ".join(value.split())


def _evidence_quote(raw: str, body: str) -> str:
    """Return an exact normalized source excerpt of at least 15 characters."""
    quote = _normalized(raw)
    normalized_body = _normalized(body)
    if quote not in normalized_body:
        raise ValueError("Audit evidence quote is absent from the current body")
    if len(quote) >= 15:
        return quote
    start = normalized_body.index(quote)
    left = max(normalized_body.rfind(marker, 0, start) for marker in (". ", "! ", "? "))
    left = 0 if left < 0 else left + 2
    ends = [
        position
        for marker in (". ", "! ", "? ")
        if (position := normalized_body.find(marker, start + len(quote))) >= 0
    ]
    right = min(ends) + 1 if ends else len(normalized_body)
    expanded = normalized_body[left:right]
    if len(expanded) < 15:
        expanded = normalized_body[max(0, start - 40) : start + len(quote) + 80]
    if quote not in expanded or len(expanded) < 15:
        raise ValueError("Could not expand short audit evidence")
    return expanded


def _audit_files(audit_root: Path, stem: str) -> list[Path]:
    paths = sorted(audit_root.glob(f"{stem}-[0-9][0-9][0-9].json"))
    crosslink = audit_root / f"{stem}-crosslink-001.json"
    if crosslink.is_file():
        paths.append(crosslink)
    return paths


def _audit_items(audit_root: Path, stem: str) -> tuple[list[dict], dict[str, str]]:
    items: list[dict] = []
    file_hashes = {}
    for path in _audit_files(audit_root, stem):
        payload = _load(path)
        rows = payload.get("items")
        if not isinstance(rows, list):
            raise TypeError(f"Audit file has no item list: {path}")
        if stem == "source":
            manifest_name = path.name.replace("source-", "manifest-", 1)
            manifest_path = audit_root / manifest_name
            if manifest_path.is_file():
                manifest_items = {row["id"]: row for row in _load(manifest_path).get("items", [])}
                for row in rows:
                    manifest = manifest_items.get(row.get("id"), {})
                    row.setdefault("source_sha256", manifest.get("sha256"))
                    row.setdefault("related_source_ids", [])
        items.extend(rows)
        file_hashes[path.name] = _file_digest(path)
    return items, file_hashes


def _candidate_index(audit_root: Path, current_candidate: Path) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    batch_root = audit_root / "gpt-web-handoff-2026-09-28" / "build" / "candidate-upload" / "batches"
    for path in sorted(batch_root.glob("candidate-batch-*.json")):
        for row in _load(path).get("items", []):
            ident = row.get("id")
            candidate = row.get("extracted")
            if not isinstance(ident, str) or not isinstance(candidate, dict) or ident in indexed:
                raise ValueError("Candidate batches contain invalid or duplicate IDs")
            indexed[ident] = candidate
    current = _load(current_candidate)
    for candidate in current.get("events", []):
        ident = candidate.get("id")
        if isinstance(ident, str):
            indexed[ident] = candidate
    return indexed


def _source_override_index(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    payload = _load(path)
    if payload.get("city") != CITY:
        raise ValueError("Source revision overrides are for another city")
    articles = payload.get("articles")
    if not isinstance(articles, list):
        raise TypeError("Source revision override file has no article list")
    indexed = {row.get("id"): row for row in articles if isinstance(row, dict)}
    if None in indexed or len(indexed) != len(articles):
        raise ValueError("Source revision overrides contain invalid or duplicate IDs")
    return indexed


def _current_audits(source_by_id: dict[str, dict], source_overrides: dict[str, dict]) -> dict[str, dict]:
    unexpected = set(source_overrides) - set(source_by_id)
    if unexpected:
        raise ValueError(f"Source revision overrides contain unknown IDs: {sorted(unexpected)}")
    current = dict(source_by_id)
    for ident, override in source_overrides.items():
        if override.get("supersedes_source_sha256") != source_by_id[ident].get("source_sha256"):
            raise ValueError(f"Source revision override does not bind the prior audit: {ident}")
        current[ident] = override
    return current


def verify_audit(
    *,
    audit_root: Path,
    source_db: Path,
    current_candidate: Path,
    source_overrides_path: Path,
) -> dict:
    checkpoint = _load(audit_root / "checkpoint-2026-09-29-candidate-comparison-complete.json")
    source_checkpoint = _load(audit_root / "checkpoint-2026-09-29-source-only-complete.json")
    comparison_validation = _load(audit_root / "candidate-comparison-validation.json")
    correction_index = _load(audit_root / "correction-index.json")
    uncertainty_index = _load(audit_root / "uncertainty-index.json")
    report = audit_root / "report-2026-09-29-candidate-comparison-complete.md"
    expected_artifacts = {
        "validation": audit_root / "candidate-comparison-validation.json",
        "correction_index": audit_root / "correction-index.json",
        "uncertainty_index": audit_root / "uncertainty-index.json",
        "report": report,
    }
    errors = []
    for key, path in expected_artifacts.items():
        expected = checkpoint.get("artifacts", {}).get(f"{key}_sha256")
        if expected != _file_digest(path):
            errors.append(f"checkpoint hash mismatch: {key}")
    source_items, source_file_hashes = _audit_items(audit_root, "source")
    comparison_items, comparison_file_hashes = _audit_items(audit_root, "comparison")
    source_by_id = {row.get("id"): row for row in source_items}
    comparison_by_id = {row.get("id"): row for row in comparison_items}
    source_overrides = _source_override_index(source_overrides_path)
    current_audits = _current_audits(source_by_id, source_overrides)
    if len(source_items) != 1100 or len(source_by_id) != 1100:
        errors.append("source audit does not contain 1,100 unique IDs")
    if len(comparison_items) != 1100 or len(comparison_by_id) != 1100:
        errors.append("candidate comparison does not contain 1,100 unique IDs")
    if set(source_by_id) != set(comparison_by_id):
        errors.append("source and comparison IDs differ")

    source_rows, coverage = read_checkpoint(source_db)
    current_sources = {row["source_id"]: row for row in source_rows}
    candidates = _candidate_index(audit_root, current_candidate)
    invalid_quotes = 0
    stale_sources = 0
    stale_candidates = 0
    checkpoint_scene_count = sum(len(row.get("scenes", [])) for row in source_items)
    checkpoint_uncertainty_count = sum(len(row.get("uncertainty", [])) for row in source_items)
    current_scene_count = 0
    current_uncertainty_count = 0
    for ident, audit in current_audits.items():
        source = current_sources.get(ident)
        if (
            source is None
            or source["source_sha256"] != audit.get("source_sha256")
            or hashlib.sha256(source["source_body"].encode()).hexdigest() != source["source_sha256"]
        ):
            stale_sources += 1
            continue
        for scene in audit.get("scenes", []):
            current_scene_count += 1
            try:
                _evidence_quote(scene.get("evidence_quote", ""), source["source_body"])
                event_time = scene.get("event_time")
                if isinstance(event_time, dict):
                    _evidence_quote(event_time.get("evidence_quote", ""), source["source_body"])
            except ValueError:
                invalid_quotes += 1
        current_uncertainty_count += len(audit.get("uncertainty", []))
        candidate = candidates.get(ident)
        if candidate is None or candidate.get("source_sha256") != source["source_sha256"]:
            stale_candidates += 1

    declared = checkpoint.get("results", {})
    checks = {
        "source_items": len(source_items),
        "comparison_items": len(comparison_items),
        "unique_source_ids": len(source_by_id),
        "unique_comparison_ids": len(comparison_by_id),
        "checkpoint_source_scenes": checkpoint_scene_count,
        "checkpoint_source_uncertainties": checkpoint_uncertainty_count,
        "current_source_scenes": current_scene_count,
        "current_source_uncertainties": current_uncertainty_count,
        "invalid_evidence_quotes": invalid_quotes,
        "stale_sources": stale_sources,
        "stale_candidates": stale_candidates,
        "revalidated_source_revisions": sorted(source_overrides),
    }
    if checkpoint_scene_count != declared.get("source_scenes"):
        errors.append("source scene count differs from completed checkpoint")
    if checkpoint_uncertainty_count != declared.get("source_uncertainty_items"):
        errors.append("uncertainty count differs from completed checkpoint")
    if invalid_quotes or stale_sources or stale_candidates:
        errors.append("source, evidence or candidate revisions are stale")
    if comparison_validation.get("integrity_errors") != []:
        errors.append("completed candidate validation contains errors")
    if correction_index.get("counts", {}).get("source_ids") not in {None, 1100}:
        errors.append("correction index count differs")
    if uncertainty_index.get("counts", {}).get("items") not in {None, 4772}:
        errors.append("uncertainty index count differs")
    if not source_checkpoint.get("source_only_complete"):
        errors.append("source-only checkpoint is incomplete")
    if not checkpoint.get("candidate_comparison_complete"):
        errors.append("candidate comparison checkpoint is incomplete")
    return {
        "schema_version": SCHEMA_VERSION,
        "city": CITY,
        "status": "validated" if not errors else "failed",
        "errors": errors,
        "checks": checks,
        "source_db_coverage_at_validation": coverage,
        "candidate_snapshot_sha256": checkpoint["candidate_snapshot_sha256"],
        "audit_checkpoint_sha256": _file_digest(
            audit_root / "checkpoint-2026-09-29-candidate-comparison-complete.json"
        ),
        "source_file_hashes": source_file_hashes,
        "comparison_file_hashes": comparison_file_hashes,
        "formal_review_ledger_changed": False,
        "owner_approved": False,
        "publication_ready": False,
    }


def _precision_from_audit(scene: dict, candidate: dict | None) -> str:
    text = normalize(f"{scene.get('precision', '')} {scene.get('place', '')}")
    if re.search(r"\b(?:u|s)(?:\+u)?\s*\d{1,2}\b", text) and re.search(
        r"\b(?:zug|bahn|bus|linie|route)\b", text
    ):
        return "route"
    method = candidate.get("geocode_method") if candidate else None
    if method == "osm_address" and "address" in text:
        return "address"
    if method == "named_street_intersection" and re.search(r"junction|intersection|corner|kreuz", text):
        return "point"
    if re.search(r"\b(?:district|locality|city|borough) only\b|citywide|district-level", text):
        return "district"
    if re.search(r"named (?:junction|intersection|corner)|full named address|exact address", text):
        return "address" if "address" in text else "point"
    if re.search(
        r"named (?:road|street|bridge|road segment|closure segment|roads)|road only|street only",
        text,
    ):
        return "street"
    if re.search(
        r"named (?:station|park|square|area|court|building|venue)|"
        r"(?:station|park|square|campus|premises|building|venue) area",
        text,
    ):
        return "area"
    if re.search(r"\baddress\b", text) and "unknown" not in text:
        return "address"
    return "unknown"


def _scope_for_scene(scene: dict, district: str, precision: str) -> str:
    text = normalize(f"{scene.get('place', '')} {scene.get('precision', '')}")
    if re.search(
        r"\b(?:netherlands|belgium|luxembourg|france|switzerland|poland|"
        r"brandenburg|potsdam|bundesweit|deutschlandweit|outside berlin)\b",
        text,
    ):
        return "out_of_city"
    if district in BERLIN_DISTRICTS and precision != "unknown":
        return "in_city"
    if re.search(r"\bberlin\b", text):
        return "in_city"
    return "uncertain"


def _candidate_matches_scene(candidate: dict, scene: dict) -> bool:
    names = [candidate.get("location_label", ""), *candidate.get("geocode_candidates", [])]
    text = normalize(f"{scene.get('place', '')} {scene.get('evidence_quote', '')}")
    return any(len(name := normalize(str(raw))) >= 4 and name in text for raw in names if raw)


def _poi_contexts(candidate: dict | None, scene: dict, precision: str) -> list[dict]:
    if not candidate or precision not in {"street", "route", "area", "place", "point"}:
        return []
    text = normalize(f" {scene.get('place', '')} {scene.get('evidence_quote', '')} {scene.get('note', '')} ")
    contexts = []
    for kind in candidate.get("poi_mentions", []):
        terms = POI_TERMS.get(kind, ())
        if not any(term in text for term in terms):
            continue
        scope = "along_geometry" if precision in {"street", "route"} else "near_geometry"
        contexts.append(
            {
                "kind": kind,
                "scope": scope,
                "radius_m": 0 if scope == "along_geometry" else 50,
                "evidence_quote": scene["evidence_quote"],
            }
        )
    return contexts


def _override_index(corrections_path: Path) -> dict[str, dict]:
    if not corrections_path.is_file():
        return {}
    payload = _load(corrections_path)
    return {row["id"]: row for row in payload.get("articles", [])}


def build_inventory(
    *,
    audit_root: Path,
    source_db: Path,
    current_candidate: Path,
    corrections_path: Path,
    source_overrides_path: Path,
) -> tuple[dict, dict[str, dict], dict[str, dict], dict[str, dict]]:
    source_rows, _ = read_checkpoint(source_db)
    sources = {row["source_id"]: row for row in source_rows}
    source_items, _ = _audit_items(audit_root, "source")
    audits = _current_audits(
        {row["id"]: row for row in source_items},
        _source_override_index(source_overrides_path),
    )
    candidates = _candidate_index(audit_root, current_candidate)
    overrides = _override_index(corrections_path)
    articles = []
    geometry_requests = []
    current_decisions = []
    role_counts: Counter = Counter()
    precision_counts: Counter = Counter()
    uncertainty_items = []
    reviewed_at = MIGRATION_REVIEWED_AT

    for ident in sorted(audits):
        audit = audits[ident]
        source = sources[ident]
        candidate = candidates[ident]
        override = overrides.get(ident)
        district = override.get("district_heading") if override else candidate.get("district", "")
        raw_scenes = override.get("scenes", []) if override else audit["scenes"]
        locations = []
        incidents = []
        for index, raw_scene in enumerate(raw_scenes, start=1):
            if override:
                role = raw_scene["role"]
                label = raw_scene["label"]
                precision = raw_scene["location_precision"]
                raw_quote = raw_scene["evidence_quote"]
                note = raw_scene.get("details", "")
                transit = raw_scene.get("transit_route")
                contexts = raw_scene.get("poi_contexts", [])
                event_time = raw_scene.get("event_time")
            else:
                role = raw_scene["role"]
                label = raw_scene["place"]
                matched_candidate = candidate if _candidate_matches_scene(candidate, raw_scene) else None
                precision = _precision_from_audit(raw_scene, matched_candidate)
                raw_quote = raw_scene["evidence_quote"]
                note = raw_scene.get("note", "")
                transit = None
                contexts = _poi_contexts(matched_candidate, raw_scene, precision)
                event_time = raw_scene.get("event_time")
            quote = _evidence_quote(raw_quote, source["source_body"])
            location_id = f"{ident}:location:{index}"
            city_scope = _scope_for_scene(
                {
                    "place": label,
                    "precision": raw_scene.get("source_precision", raw_scene.get("precision", "")),
                },
                district,
                precision,
            )
            location = {
                "location_id": location_id,
                "label": _normalized(label),
                "role": role,
                "precision": precision,
                "city_scope": city_scope,
                "evidence_quotes": [quote],
                "coordinates": None,
            }
            if transit:
                location["transit_route"] = {
                    **transit,
                    "evidence_quote": _evidence_quote(transit["evidence_quote"], source["source_body"]),
                }
            if contexts:
                location["poi_contexts"] = [
                    {
                        **context,
                        "evidence_quote": _evidence_quote(context["evidence_quote"], source["source_body"]),
                    }
                    for context in contexts
                ]
            locations.append(location)
            role_counts[role] += 1
            precision_counts[precision] += 1
            if role in COUNT_ROLES:
                incident = {
                    "incident_id": f"{ident}:incident:{len(incidents) + 1}",
                    "evidence_quotes": [quote],
                    "formal_location_ids": [location_id],
                    "details": _normalized(f"{note} Audit relationship: {audit['event_relationship']}"),
                }
                if event_time:
                    incident["event_time"] = {
                        **event_time,
                        "evidence_quote": _evidence_quote(
                            event_time["evidence_quote"], source["source_body"]
                        ),
                    }
                incidents.append(incident)

        if any(row["city_scope"] == "in_city" for row in locations):
            scope = "mixed" if any(row["city_scope"] != "in_city" for row in locations) else "in_city"
        elif district in BERLIN_DISTRICTS:
            scope = "in_city"
        else:
            scope = "uncertain"
        decision_core = {
            "city": CITY,
            "source_id": ident,
            "source_url": source["source_url"],
            "source_sha256": source["source_sha256"],
            "audit_source_sha256": audit["source_sha256"],
            "announcement_kind": audit["announcement_kind"],
            "event_relationship": audit["event_relationship"],
            "minimum_independent_events": audit["minimum_independent_events"],
            "formal_locations": locations,
            "incidents": incidents,
        }
        decision_sha = _digest(decision_core)
        current_decisions.append(
            {
                "source_id": ident,
                "source_sha256": source["source_sha256"],
                "decision_sha256": decision_sha,
            }
        )
        article = {
            "source_id": ident,
            "source_url": source["source_url"],
            "source_sha256": source["source_sha256"],
            "decision_sha256": decision_sha,
            "scope_verdict": scope,
            "incident_count": len(incidents),
            "incidents": incidents,
            "formal_locations": locations,
            "audit": {
                "announcement_kind": audit["announcement_kind"],
                "event_relationship": audit["event_relationship"],
                "minimum_independent_events": audit["minimum_independent_events"],
                "uncertainty": audit["uncertainty"],
                "related_source_ids": audit["related_source_ids"],
                "candidate_comparison_verdict": "needs_correction",
                "owner_correction_override": ident in overrides,
                "source_revision_override": "supersedes_source_sha256" in audit,
            },
        }
        articles.append(article)
        for number, uncertainty in enumerate(audit["uncertainty"], start=1):
            uncertainty_items.append(
                {
                    "source_id": ident,
                    "source_url": source["source_url"],
                    "source_sha256": source["source_sha256"],
                    "decision_sha256": decision_sha,
                    "uncertainty_id": f"{ident}:uncertainty:{number}",
                    "text": uncertainty,
                }
            )
        for location in locations:
            if scope not in {"in_city", "mixed"} or location["city_scope"] != "in_city":
                continue
            precision = location["precision"]
            task = {
                "point": "checked_point_geocode_required",
                "address": "checked_point_geocode_required",
                "place": "checked_point_geocode_required",
                "street": "checked_road_geometry_required",
                "route": "checked_transit_route_geometry_required",
                "area": "checked_area_geometry_required",
                "district": "checked_district_geometry_required",
                "unknown": "unresolved_no_geometry",
            }[precision]
            request = {
                "source_id": ident,
                "source_url": source["source_url"],
                "source_sha256": source["source_sha256"],
                "decision_sha256": decision_sha,
                "location_id": location["location_id"],
                "incident_ids": [
                    incident["incident_id"]
                    for incident in incidents
                    if location["location_id"] in incident["formal_location_ids"]
                ],
                "label": location["label"],
                "role": location["role"],
                "precision": precision,
                "city_scope": "in_city",
                "evidence_quotes": location["evidence_quotes"],
                "coordinates": None,
                "geometry_task": task,
            }
            for key in ("transit_route", "poi_contexts"):
                if key in location:
                    request[key] = location[key]
            request["geometry_request_sha256"] = _digest(request)
            geometry_requests.append(request)

    inventory_core = {
        "city": CITY,
        "decision_set_digest": _digest(current_decisions),
        "articles": articles,
        "geometry_requests": geometry_requests,
    }
    inventory = {
        "schema_version": SCHEMA_VERSION,
        **inventory_core,
        "inventory_digest": _digest(inventory_core),
        "coverage": {
            "discovered": len(articles),
            "bodies_in_pack": len(articles),
            "missing_bodies": 0,
            "source_errors": 0,
            "channel_scan_complete": True,
        },
        "review_counts": {
            "supported": len(articles),
            "needs_correction": 0,
            "uncertain": 0,
            "stale": 0,
            "pending": 0,
        },
        "reviewed_articles": len(articles),
        "reviewed_incidents": sum(row["incident_count"] for row in articles),
        "reviewed_formal_locations": sum(len(row["formal_locations"]) for row in articles),
        "in_city_geometry_requests": len(geometry_requests),
        "geometry_task_counts": dict(
            sorted(Counter(row["geometry_task"] for row in geometry_requests).items())
        ),
        "role_counts": dict(sorted(role_counts.items())),
        "precision_counts": dict(sorted(precision_counts.items())),
        "audit_uncertainty_count": len(uncertainty_items),
        "migration_reviewed_at": reviewed_at,
        "all_current_reviews_supported": True,
        "geometry_complete": not geometry_requests,
        "owner_approval_required": True,
        "owner_approved": False,
        "publication_ready": False,
        "publication_blocks": [
            "checked_geometry_incomplete",
            "owner_approval_missing",
            "approved_map_build_absent",
        ],
    }
    uncertainty = {
        "schema_version": 1,
        "city": CITY,
        "inventory_digest": inventory["inventory_digest"],
        "item_count": len(uncertainty_items),
        "items": uncertainty_items,
        "owner_approved": False,
        "publication_ready": False,
    }
    return inventory, sources, candidates, uncertainty


def _object_groups_for_request(
    request: dict,
    candidate: dict,
    correction: dict | None,
    geometry_index: dict,
) -> tuple[str, list[list[str]], str]:
    objects = {row["id"]: row for row in geometry_index["objects"]}
    name_index = geometry_index["name_index"]

    def named_ids(raw: str) -> list[str]:
        ids = []
        for key in (osm_name(raw), normalize(raw)):
            for ident in name_index.get(key, []):
                if ident not in ids:
                    ids.append(ident)
        return ids

    def administrative_polygons() -> list:
        label = request["label"]
        scope_names = []
        for raw in [*label.split(",")[1:], label.rsplit(" in ", 1)[-1], candidate.get("district")]:
            value = str(raw or "").strip()
            for prefix in ("Berlin-", "Berlin "):
                value = value.removeprefix(prefix)
            if value and value != label and value not in scope_names:
                scope_names.append(value)
        for scope_name in scope_names:
            polygons = [
                shape(objects[ident]["geometry"])
                for ident in named_ids(scope_name)
                if objects[ident]["dimension"] == "polygon"
                and "administrative_boundary" in objects[ident]["roles"]
            ]
            if polygons:
                return polygons
        return []

    def checked_road(ids: list[str]) -> list[str]:
        ids = [
            ident
            for ident in ids
            if "road" in objects[ident]["roles"] and objects[ident]["dimension"] == "line"
        ]
        if not ids:
            return []
        polygons = administrative_polygons()
        if polygons:
            scoped = [
                ident
                for ident in ids
                if any(shape(objects[ident]["geometry"]).intersects(polygon) for polygon in polygons)
            ]
            if scoped:
                return scoped
        coordinates = candidate.get("coordinates")
        if not (
            isinstance(coordinates, list)
            and len(coordinates) >= 2
            and all(type(value) in {int, float} for value in coordinates[:2])
        ):
            return ids if len(ids) == 1 else []
        point = Point(coordinates[:2])
        geometries = {ident: shape(objects[ident]["geometry"]) for ident in ids}
        seed = min(ids, key=lambda ident: geometries[ident].distance(point))
        if geometries[seed].distance(point) > 0.03:
            return []
        component = {seed}
        pending = [seed]
        while pending:
            current = pending.pop()
            for ident in ids:
                if ident in component:
                    continue
                if geometries[current].distance(geometries[ident]) <= 0.0001:
                    component.add(ident)
                    pending.append(ident)
        return [ident for ident in ids if ident in component]

    if correction:
        scene_number = int(request["location_id"].rsplit(":", 1)[1]) - 1
        scene = correction["scenes"][scene_number]
        ids = [ident for ident in scene.get("geometry_object_ids", []) if ident in objects]
        precision = request["precision"]
        if not ids:
            return "none", [], "Owner correction retains unknown geometry."
        if precision == "route":
            return "osm_transit_route", [ids], "Owner-reviewed complete transit route."
        dimensions = {objects[ident]["dimension"] for ident in ids}
        if precision == "street" and dimensions <= {"line"}:
            return "osm_line", [ids], "Owner-reviewed full named road geometry."
        if precision == "area" and dimensions <= {"polygon"}:
            return "osm_polygon", [ids], "Owner-reviewed named area geometry."
        if precision in {"point", "place", "address"} and len(ids) == 1:
            method = "osm_point" if objects[ids[0]]["dimension"] == "point" else "osm_footprint"
            return method, [ids], "Owner-reviewed named object geometry."
        return "none", [], "Correction geometry cannot be expressed as one checked method."

    names = []
    for raw in [candidate.get("location_label"), *candidate.get("geocode_candidates", [])]:
        name = normalize(str(raw or ""))
        if name and name not in names:
            names.append(name)
    if request["precision"] == "route":
        line = request.get("transit_route", {}).get("line")
        ids = [
            ident
            for ident in named_ids(str(line or ""))
            if objects[ident]["dimension"] == "line"
            and (objects[ident]["tags"].get("railway") or objects[ident]["tags"].get("public_transport"))
        ]
        return (
            ("osm_transit_route", [ids], "Exact reviewed transit-line name in checked OSM index.")
            if ids
            else ("none", [], "No exact checked transit-line geometry.")
        )
    if request["precision"] == "street":
        for name in names:
            ids = checked_road(named_ids(name))
            if ids:
                return "osm_line", [ids], "Exact audited road name; every checked segment retained."
    if request["precision"] == "point" and len(names) >= 2:
        groups = []
        for name in names[:4]:
            ids = checked_road(named_ids(name))
            if ids:
                groups.append(ids)
        if len(groups) >= 2:
            return "osm_intersection", groups, "Exact audited road groups for junction."
    if request["precision"] in {"point", "place", "address", "area", "district"}:
        ids = [ident for ident in candidate.get("location_object_ids", []) if ident in objects]
        if ids:
            if request["precision"] == "district":
                polygons = [
                    ident
                    for ident in ids
                    if objects[ident]["dimension"] == "polygon"
                    and "administrative_boundary" in objects[ident]["roles"]
                ]
                if polygons:
                    return "osm_polygon", [polygons], "Reviewed administrative OSM objects."
            polygons = [ident for ident in ids if objects[ident]["dimension"] == "polygon"]
            points = [ident for ident in ids if objects[ident]["dimension"] == "point"]
            if polygons:
                return "osm_footprint", [polygons], "Exact named OSM footprint from old lookup hint."
            if len(points) == 1:
                return "osm_point", [points], "Exact named OSM point from old lookup hint."
    return "none", [], "No unambiguous source-equivalent checked OSM selection."


def build_geometry_decisions(
    *, inventory: dict, geometry_index: dict, candidates: dict, corrections: dict
) -> tuple[dict, dict]:
    objects = {row["id"]: row for row in geometry_index["objects"]}
    decisions = []
    reviewed_at = MIGRATION_REVIEWED_AT
    for request in inventory["geometry_requests"]:
        ident = request["source_id"]
        method, groups, note = _object_groups_for_request(
            request, candidates[ident], corrections.get(ident), geometry_index
        )
        decision = {
            "schema_version": 1,
            "city": CITY,
            "source_id": ident,
            "source_sha256": request["source_sha256"],
            "decision_sha256": request["decision_sha256"],
            "location_id": request["location_id"],
            "geometry_request_sha256": request["geometry_request_sha256"],
            "verdict": "resolved" if method != "none" else "unresolved",
            "method": method,
            "osm_object_groups": groups,
            "review_note": note,
            "reviewer": REVIEWER,
            "reviewed_at": reviewed_at,
        }
        decisions.append(decision)
    envelope = {
        "schema_version": 1,
        "city": CITY,
        "inventory_digest": inventory["inventory_digest"],
        "geometry_index_sha256": geometry_index["index_sha256"],
        "decisions": decisions,
    }
    return envelope, objects


def _map_category(candidate: dict, role: str) -> str:
    if role == "accident":
        return "verkehr"
    return CATEGORY_MAP.get(candidate.get("category"), "sonstige")


def build_map_decisions(*, inventory: dict, geometry_ledger: dict, candidates: dict, sources: dict) -> dict:
    reviewed_at = MIGRATION_REVIEWED_AT
    decisions = []
    for article in inventory["articles"]:
        if article["scope_verdict"] not in {"in_city", "mixed"}:
            continue
        ident = article["source_id"]
        candidate = candidates[ident]
        incidents = []
        locations = {row["location_id"]: row for row in article["formal_locations"]}
        for incident in article["incidents"]:
            role = locations[incident["formal_location_ids"][0]]["role"]
            incidents.append(
                {
                    "incident_id": incident["incident_id"],
                    "category": _map_category(candidate, role),
                    "evidence_quotes": incident["evidence_quotes"],
                }
            )
        quotes = (
            article["incidents"][0]["evidence_quotes"]
            if article["incidents"]
            else article["formal_locations"][0]["evidence_quotes"]
        )
        article_category = (
            incidents[0]["category"] if incidents else CATEGORY_MAP.get(candidate.get("category"), "sonstige")
        )
        decisions.append(
            {
                "schema_version": 1,
                "city": CITY,
                "source_id": ident,
                "source_sha256": article["source_sha256"],
                "source_review_sha256": article["decision_sha256"],
                "article_category": article_category,
                "is_crime_report": bool(article["incidents"] and article_category != "verkehr"),
                "classification_evidence_quotes": quotes,
                "incident_categories": incidents,
                "primary_count_incident_id": None,
                "primary_count_location_id": None,
                "review_note": (
                    "Category migrated from the source-audited scene and frozen diagnostic category. "
                    "No announcement count point is selected without an individually defensible point."
                ),
                "reviewer": REVIEWER,
                "reviewed_at": reviewed_at,
            }
        )
    return {
        "schema_version": 1,
        "city": CITY,
        "inventory_digest": inventory["inventory_digest"],
        "geometry_ledger_sha256": geometry_ledger["ledger_sha256"],
        "decisions": decisions,
    }


def frozen_source_db(*, source_db: Path, output: Path, source_ids: set[str]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    for path in (
        temporary,
        Path(f"{temporary}-wal"),
        Path(f"{temporary}-shm"),
    ):
        path.unlink(missing_ok=True)
    with sqlite3.connect(source_db) as source, sqlite3.connect(temporary) as target:
        source.backup(target)
        target.execute("PRAGMA journal_mode=DELETE")
        target.execute("PRAGMA foreign_keys=OFF")
        placeholders = ",".join("?" for _ in source_ids)
        target.execute(f"DELETE FROM reports WHERE id NOT IN ({placeholders})", tuple(sorted(source_ids)))
        berlin_timezone = ZoneInfo("Europe/Berlin")
        for ident, published in target.execute("SELECT id,published FROM reports"):
            timestamp = datetime.fromisoformat(published)
            if timestamp.tzinfo is None:
                target.execute(
                    "UPDATE reports SET published=? WHERE id=?",
                    (timestamp.replace(tzinfo=berlin_timezone).isoformat(), ident),
                )
        if "revisions" in {
            row[0] for row in target.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }:
            columns = {row[1] for row in target.execute("PRAGMA table_info(revisions)")}
            ident = "id" if "id" in columns else "report_id" if "report_id" in columns else None
            if ident:
                target.execute(
                    f"DELETE FROM revisions WHERE {ident} NOT IN ({placeholders})",
                    tuple(sorted(source_ids)),
                )
        target.execute("CREATE TABLE IF NOT EXISTS archive_coverage (complete INTEGER NOT NULL)")
        target.execute("DELETE FROM archive_coverage")
        target.execute("INSERT INTO archive_coverage (complete) VALUES (1)")
        target.commit()
    for path in (Path(f"{output}-wal"), Path(f"{output}-shm")):
        path.unlink(missing_ok=True)
    temporary.replace(output)
    rows, coverage = read_checkpoint(output)
    if (
        len(rows) != len(source_ids)
        or coverage["discovered"] != len(source_ids)
        or coverage["channel_scan_complete"] is not True
    ):
        raise ValueError("Frozen migration database does not contain the audited source set")


def build_diff(*, inventory: dict, candidates: dict, geometry_ledger: dict, uncertainty: dict) -> dict:
    geometry = {row["request"]["location_id"]: row for row in geometry_ledger["decisions"]}
    uncertainty_counts = Counter(row["source_id"] for row in uncertainty["items"])
    items = []
    for article in inventory["articles"]:
        ident = article["source_id"]
        old = candidates[ident]
        scenes = article["formal_locations"]
        items.append(
            {
                "source_id": ident,
                "source_url": article["source_url"],
                "source_sha256": article["source_sha256"],
                "source_review_sha256": article["decision_sha256"],
                "old_candidate": {
                    "category": old.get("category"),
                    "is_crime_report": old.get("is_crime_report"),
                    "coordinates": old.get("coordinates"),
                    "location_precision": old.get("location_precision"),
                    "geocode_method": old.get("geocode_method"),
                    "location_label": old.get("location_label"),
                    "poi_mentions": old.get("poi_mentions", []),
                    "scene_locations": len(old.get("scene_locations", [])),
                },
                "rebuilt": {
                    "incidents": article["incident_count"],
                    "formal_locations": len(scenes),
                    "roles": dict(sorted(Counter(row["role"] for row in scenes).items())),
                    "resolved_geometries": sum(
                        geometry.get(row["location_id"], {}).get("decision", {}).get("verdict") == "resolved"
                        for row in scenes
                    ),
                    "unresolved_geometries": sum(
                        geometry.get(row["location_id"], {}).get("decision", {}).get("verdict") != "resolved"
                        for row in scenes
                    ),
                    "uncertainty_items": uncertainty_counts[ident],
                    "primary_count_location_id": None,
                },
            }
        )
    core = {"city": CITY, "inventory_digest": inventory["inventory_digest"], "items": items}
    return {
        "schema_version": 1,
        **core,
        "diff_digest": _digest(core),
        "item_count": len(items),
        "owner_approved": False,
        "publication_ready": False,
    }


def write_owner_review_pack(output: Path, checkpoint: dict) -> dict:
    """Write a deterministic, source-excerpt-only owner review bundle."""
    included = [
        "audit-validation.json",
        "reviewed-scene-inventory.json",
        "uncertainty-index.json",
        "geometry-decisions.json",
        "geometry-ledger.json",
        "map-decisions.json",
        "map-decision-ledger.json",
        "old-new-diff.json",
        "checkpoint.json",
        "map-candidate/manifest.json",
        "map-candidate/build-audit.json",
    ]
    files = {name: _file_digest(output / name) for name in included}
    manifest = {
        "schema_version": 1,
        "city": CITY,
        "checkpoint_sha256": checkpoint["checkpoint_sha256"],
        "files": files,
        "contains_raw_source_bodies": False,
        "formal_review_ledger_changed": False,
        "owner_approved": False,
        "publication_ready": False,
        "publication_blocks": ["owner_map_inspection_and_approval_missing"],
    }
    manifest_path = output / "owner-review-manifest.json"
    _write(manifest_path, manifest, pretty=True)
    archive = output / "owner-review.zip"
    temporary = archive.with_suffix(".zip.tmp")
    temporary.unlink(missing_ok=True)
    archive_files = ["owner-review-manifest.json", *included]
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name in sorted(archive_files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, (output / name).read_bytes())
    temporary.replace(archive)
    digest = _file_digest(archive)
    sidecar = output / "owner-review.zip.sha256"
    sidecar.write_text(f"{digest}  owner-review.zip\n", encoding="ascii")
    return {
        "path": str(archive),
        "sha256": digest,
        "manifest_sha256": _file_digest(manifest_path),
        "sidecar": str(sidecar),
    }


def run(args: argparse.Namespace) -> dict:
    validation = verify_audit(
        audit_root=args.audit_root,
        source_db=args.source_db,
        current_candidate=args.current_candidate,
        source_overrides_path=args.source_overrides,
    )
    if validation["status"] != "validated":
        raise ValueError("Audit validation failed: " + "; ".join(validation["errors"][:10]))
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    _write(output / "audit-validation.json", validation, pretty=True)
    inventory, sources, candidates, uncertainty = build_inventory(
        audit_root=args.audit_root,
        source_db=args.source_db,
        current_candidate=args.current_candidate,
        corrections_path=args.corrections,
        source_overrides_path=args.source_overrides,
    )
    _write(output / "reviewed-scene-inventory.json", inventory)
    _write(output / "uncertainty-index.json", uncertainty)
    frozen_db = output / "berlin-audit-1100.sqlite"
    frozen_source_db(
        source_db=args.source_db,
        output=frozen_db,
        source_ids={row["source_id"] for row in inventory["articles"]},
    )
    geometry_index = _load(args.geometry_index)
    corrections = _override_index(args.corrections)
    geometry_envelope, _ = build_geometry_decisions(
        inventory=inventory,
        geometry_index=geometry_index,
        candidates=candidates,
        corrections=corrections,
    )
    boundary = shape(_load(args.boundary)["geometry"])
    # Validate selections one at a time so an ambiguous old hint becomes unresolved.
    objects = {row["id"]: row for row in geometry_index["objects"]}
    requests = {row["location_id"]: row for row in inventory["geometry_requests"]}
    for decision in geometry_envelope["decisions"]:
        if decision["verdict"] != "resolved":
            continue
        try:
            _derived_geometry(decision, requests[decision["location_id"]], objects, boundary, CITY)
        except (TypeError, ValueError) as exc:
            decision.update(
                verdict="unresolved",
                method="none",
                osm_object_groups=[],
                review_note=f"Checked selection rejected conservatively: {exc}",
            )
    _write(output / "geometry-decisions.json", geometry_envelope)
    geometry_ledger = compile_geometry_decisions(
        inventory=inventory,
        geometry_index=geometry_index,
        decision_envelope=geometry_envelope,
        border=boundary,
    )
    _write(output / "geometry-ledger.json", geometry_ledger)
    source_rows, _ = read_checkpoint(frozen_db)
    map_envelope = build_map_decisions(
        inventory=inventory,
        geometry_ledger=geometry_ledger,
        candidates=candidates,
        sources=sources,
    )
    _write(output / "map-decisions.json", map_envelope)
    map_ledger = compile_map_decisions(
        city=CITY,
        source_rows=source_rows,
        inventory=inventory,
        geometry_ledger=geometry_ledger,
        decision_envelope=map_envelope,
    )
    _write(output / "map-decision-ledger.json", map_ledger)
    candidate_dir = output / "map-candidate"
    candidate_audit = build_candidate(
        city=CITY,
        source_db=frozen_db,
        inventory_path=output / "reviewed-scene-inventory.json",
        geometry_ledger_path=output / "geometry-ledger.json",
        map_ledger_path=output / "map-decision-ledger.json",
        poi_root=args.poi_root,
        catalog_path=args.catalog,
        output=candidate_dir,
    )
    diff = build_diff(
        inventory=inventory,
        candidates=candidates,
        geometry_ledger=geometry_ledger,
        uncertainty=uncertainty,
    )
    _write(output / "old-new-diff.json", diff)
    artifacts = {}
    for path in sorted(output.glob("*.json")):
        if path.name in {"checkpoint.json", "owner-review-manifest.json"}:
            continue
        artifacts[path.name] = _file_digest(path)
    artifacts["berlin-audit-1100.sqlite"] = _file_digest(frozen_db)
    artifacts["map-candidate/manifest.json"] = _file_digest(candidate_dir / "manifest.json")
    artifacts["map-candidate/build-audit.json"] = _file_digest(candidate_dir / "build-audit.json")
    checkpoint_core = {
        "city": CITY,
        "source_count": len(inventory["articles"]),
        "scene_count": inventory["reviewed_formal_locations"],
        "incident_count": inventory["reviewed_incidents"],
        "uncertainty_count": uncertainty["item_count"],
        "inventory_digest": inventory["inventory_digest"],
        "geometry_ledger_sha256": geometry_ledger["ledger_sha256"],
        "map_decision_ledger_sha256": map_ledger["ledger_sha256"],
        "candidate_digest": candidate_audit["candidate_digest"],
        "artifacts": artifacts,
    }
    checkpoint = {
        "schema_version": 1,
        **checkpoint_core,
        "checkpoint_sha256": _digest(checkpoint_core),
        "owner_approved": False,
        "publication_ready": False,
        "formal_review_ledger_changed": False,
        "tracked_publication_changed": False,
        "publication_blocks": ["owner_map_inspection_and_approval_missing"],
    }
    _write(output / "checkpoint.json", checkpoint, pretty=True)
    owner_review_pack = write_owner_review_pack(output, checkpoint)
    return {**checkpoint, "owner_review_pack": owner_review_pack}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-root", type=Path, required=True)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--current-candidate", type=Path, required=True)
    parser.add_argument("--corrections", type=Path, required=True)
    parser.add_argument("--source-overrides", type=Path, required=True)
    parser.add_argument("--geometry-index", type=Path, required=True)
    parser.add_argument("--boundary", type=Path, required=True)
    parser.add_argument("--poi-root", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=Path("data/safety/europe_sources.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--acknowledge-incomplete-migration",
        action="store_true",
        help="Reproduce the invalidated diagnostic; never use it as review completion.",
    )
    args = parser.parse_args()
    if not args.acknowledge_incomplete_migration:
        parser.error(
            "This legacy migration is incomplete under the owner's six-rule review. "
            "Use berlin_semantic_review; pass --acknowledge-incomplete-migration "
            "only to reproduce the invalidated diagnostic."
        )
    runtime = (Path.cwd() / ".runtime").resolve()
    if not args.output.resolve().is_relative_to(runtime):
        parser.error("Berlin audit rebuild output must remain under .runtime/")
    result = run(args)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
