"""Project the accepted Cologne canonical municipal subset into shared map records.

No geocoding or new narrative decisions. Full canonical evidence stays outside the
public product; reviewed facts and source identities are retained in this projection.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path


def dump(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(value) -> str:
    return hashlib.sha256(dump(value)).hexdigest()


def time_record(value):
    if value is None:
        return None
    # Exact reviewed calendar/precision/display. Publication time is never substituted.
    return {k: value.get(k) for k in ["date", "display", "precision", "status"]} | {"evidence_quote": ""}


def phase_record(value):
    return {"incident_id": value["incident_id"], "details": value["details"],
            "category": value["category_decision"]["category"],
            "formal_location_ids": value["formal_location_ids"],
            "event_time": time_record(value["event_time_review"]),
            "count_relation": value["count_decision"]["count_relation"]}


def event_record(value):
    if value["event_position"] is not None or value["spatial_primary_count"] is not None:
        raise ValueError("Unexpected change in accepted no-count-point contract")
    phases = [phase_record(p) for p in value["phases"]]
    phase_by_id = {p["incident_id"]: p for p in phases}
    if len(phase_by_id) != len(phases):
        raise ValueError("Duplicate phase identity")
    scenes = []
    for original in value["scenes"]:
        if original["event_count_point"] or original["coordinates"] is not None:
            raise ValueError("Unexpected event coordinate or count assignment")
        if any(identity not in phase_by_id for identity in original["phase_ids"]):
            raise ValueError("Scene refers to an unknown phase")
        contract = original["source_reference_geometry_contract"] or {}
        decision = original["native_geometry_decision"] or {}
        geometry = original["reference_geometry"]
        scene = {"location_id": original["location_id"], "label": original["label"],
                 "role": original["role"], "city_scope": original["city_scope"],
                 "location_precision": original["precision"], "details": original["details"],
                 "coordinates": original["coordinates"], "geometry": geometry,
                 "geocode_method": decision.get("method", "unresolved_official_location"),
                 "primary_for_count": original["event_count_point"],
                 "actual_event_position_known": original["actual_event_position_known"],
                 "actual_event_extent_known": original["complete_offence_extent_known"],
                 "event_time": time_record(original["event_time_review"]),
                 "incidents": [phase_by_id[identity] for identity in original["phase_ids"]],
                 "source_reference_geometry_contract": contract,
                 "reference_geometry_sha256": original["reference_geometry_sha256"],
                 "native_geometry_binding_status": original["native_geometry_binding_status"],
                 "poi_contexts": [{k: c[k] for k in ["kind", "scope", "radius_m"]} | {"evidence_quote": ""}
                                  for c in original["poi_contexts"]]}
        if geometry is not None:
            # Shared renderer treats these as source references, including native points.
            # The original more specific contract remains intact above.
            scene["geometry_usage"] = ("carrier_line_reference_only" if contract.get("geometry_usage")
                == "source_transit_native_carrier_segment_reference_only"
                else "source_native_collection_reference_only")
        transit = original["transit_review"] or {}
        if transit.get("status") == "reviewed_route":
            scene["transit_route"] = {k: transit[k] for k in ["mode", "line", "extent"]} | {"evidence_quote": ""}
        scenes.append(scene)
    return {"id": value["id"], "source_id": value["source_id"], "source_url": value["source_url"],
            "source_sha256": value["source_sha256"], "source_revision": value["source_revision"],
            "title": value["title"], "published_at": value["published"],
            "publication_month": value["publication_month"], "month": value["publication_month"],
            "time_basis": value["month_filter_basis"], "event_date": None,
            "category": value["article_category"], "coordinates": value["event_position"],
            "location_precision": "unknown", "location_label": "", "poi_mentions": [],
            "feed_url": "https://koeln.polizei.nrw/presse", "mention_basis": "reviewed_source_context_only",
            "geocode_method": "multiple_official_scenes", "outcome": "",
            "source_status": value["current_source_review_status"], "source_scope_verdict": value["scope_verdict"],
            "is_crime_report": value["is_crime_report"], "announcement_kind": value["announcement_kind"],
            "event_relationship": value["event_relationship"], "narrated_course_minimum": value["narrated_course_minimum"],
            "source_statistics": value["source_statistics"],
            "source_relationships": value["current_typed_source_relationships"],
            "incidents": phases, "scene_locations": scenes}


def run(source: Path, expected_sha: str, output: Path, report: Path):
    if output.exists() or hashlib.sha256(source.read_bytes()).hexdigest() != expected_sha:
        raise ValueError("Output exists or accepted canonical input changed")
    canonical = json.loads(source.read_text())
    if canonical["city"] != "cologne":
        raise ValueError("Cross-city input")
    selected = [e for e in canonical["events"] if e["municipal_map_eligible"]]
    if (len(canonical["events"]), len(selected), sum(len(e["phases"]) for e in selected),
            sum(len(e["scenes"]) for e in selected)) != (582, 439, 3012, 2590):
        raise ValueError("Approved municipal population changed")
    rows = [event_record(e) for e in selected]
    # Independent semantic reconstruction checks; hashes of source facts survive aliases.
    for original, row in zip(selected, rows, strict=True):
        if [p["incident_id"] for p in row["incidents"]] != [p["incident_id"] for p in original["phases"]]:
            raise ValueError("Phase population changed")
        for old, new in zip(original["scenes"], row["scene_locations"], strict=True):
            if (old["reference_geometry"] != new["geometry"] or old["coordinates"] != new["coordinates"]
                    or old["label"] != new["label"] or old["role"] != new["role"]
                    or old["details"] != new["details"] or old["precision"] != new["location_precision"]):
                raise ValueError("Reviewed scene fact changed")
    months = defaultdict(list)
    for row in rows:
        months[row["month"]].append(row)
    row_by_source = {row["source_id"]: row for row in rows}
    context_features = canonical["source_bound_POI_reference_features"]["features"]
    references_by_month = defaultdict(list)
    links_by_month = defaultdict(list)
    for feature in context_features:
        properties = feature["properties"]
        if (properties.get("context_only") is not True or properties.get("event_count_point") is not False
                or properties.get("counts_as_crime_point") is not False
                or properties.get("association_radius_m") != 0):
            raise ValueError("Source-context reference cannot establish an offence or count point")
        row = row_by_source.get(properties["source_id"])
        if row is None or row["month"] != properties["publication_month"]:
            raise ValueError("Context reference belongs to an excluded source or wrong month")
        indices = [i for i, scene in enumerate(row["scene_locations"])
                   if scene["location_id"] == properties["location_id"]]
        if len(indices) != 1:
            raise ValueError("Source-context reference has no exact formal location")
        references_by_month[row["month"]].append(feature)
        links_by_month[row["month"]].append({"event_id": row["id"],
            "poi_id": properties["native_object_id"], "status": "source_context_only",
            "source_url": properties["source_url"], "source_sha256": row["source_sha256"],
            "scene_id": f"{row['id']}/{indices[0]}", "mention_basis": properties["context_scope"],
            "native_reference_feature_id": feature["id"],
            "offence_at_native_business_proven": properties["offence_at_native_business_proven"],
            "event_count_point": properties["event_count_point"]})
    if len(context_features) != 90:
        raise ValueError("Accepted native context reference population changed")
    identity = digest({"canonical_sha256": expected_sha, "projected_events": rows})
    translation_generation = identity[:16] + "-20261002T025437"
    generation = digest({"events": rows, "context_features": context_features,
                         "links": dict(links_by_month)})[:16] + "-20261002T025437"
    output.mkdir(parents=True)
    files = {}
    empty = {"type": "FeatureCollection", "features": []}
    for month, events in sorted(months.items()):
        value = {"event_ids": [e["id"] for e in events], "events": events,
                 "hex": {"overview": empty, "detail": empty}, "links": links_by_month[month],
                 "source_poi_reference_features": {"type": "FeatureCollection", "features": references_by_month[month]}}
        path = output / generation / "months" / f"{month}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(dump(value))
        files[path.relative_to(output).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    result = {"city": "cologne", "canonical_sha256": expected_sha, "generation": generation,
              "translation_source_generation": translation_generation,
              "source_articles": 582, "public_map_articles": 439, "excluded_outside": 97,
              "excluded_uncertain": 46, "public_phases": 3012, "public_scenes": 2590,
              "original_reference_geometries_unchanged": True, "event_coordinate_assignments": 0,
              "spatial_primary_count": None, "files": files, "source_id_sha_revision_preserved": True,
              "source_relationships_statistics_preserved": True, "publication_ready": False,
              "native_context_features": 90, "unique_context_native_ids": 69,
              "source_poi_links": 90, "native_context_reference_geometries_unchanged": True,
              "remaining": ["complete core13 background",
                            "manifest/roads/search/boundary assembly", "current translation carrier and browser gates"]}
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_bytes(dump(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for key in ["source", "output", "report"]:
        parser.add_argument(f"--{key}", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    args = parser.parse_args()
    value = run(args.source, args.source_sha256, args.output, args.report)
    print(json.dumps({k: v for k, v in value.items() if k != "files"}))
