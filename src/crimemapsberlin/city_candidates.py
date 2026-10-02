"""Stage a city's local source and GIS extraction for per-article review.

This command creates no public map files. City data and source bodies stay in
ignored local directories until source review and owner inspection are complete.
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from crimemapsberlin.city_contract import CITY_SPECS, paths_for
from crimemapsberlin.city_sources import normalized_event_db, read_city_source
from crimemapsberlin.geocode import Gazetteer, events_from_db
from crimemapsberlin.multiple_scenes import scene_decision_index
from crimemapsberlin.payload import compact
from crimemapsberlin.polizeikarte_munich import (
    candidate_snapshot as munich_candidate_snapshot,
)
from crimemapsberlin.review import connect as connect_review
from crimemapsberlin.review import review_summary
from crimemapsberlin.spatial import metric_transforms, pois_from_osm

ROOT = Path(__file__).resolve().parents[2]
CITY_SETTINGS = {city: spec for city, spec in CITY_SPECS.items() if spec.candidate_enabled}


def stage(city: str, *, root: Path = ROOT) -> dict:
    if city not in CITY_SETTINGS:
        raise ValueError(f"No checked city extraction configuration: {city}")
    spec = CITY_SETTINGS[city]
    city_paths = paths_for(city, root)
    runtime = city_paths.runtime
    if city == "munich":
        events, audit = munich_candidate_snapshot(city_paths.source_db)
        runtime.mkdir(parents=True, exist_ok=True)
        candidate_path = runtime / "review-candidates.json"
        tmp = candidate_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(
                {"city": city, "events": events, "changed_locations": []},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        tmp.replace(candidate_path)
        audit_path = runtime / "candidate-audit.json"
        tmp = audit_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(audit, ensure_ascii=False, indent=2))
        tmp.replace(audit_path)
        return audit
    paths = city_paths.osm_indexes(city)
    if not all(path.is_file() for path in paths):
        raise FileNotFoundError(f"Missing checked {city} OSM indexes in {city_paths.raw}")
    if city in {"cologne", "frankfurt"}:
        provenance_path = city_paths.raw / f"{city}-pois.source.json"
        if not provenance_path.is_file():
            raise FileNotFoundError(f"Missing {city} OSM extraction provenance")
        provenance = json.loads(provenance_path.read_text())
        digest = provenance.get("sha256")
        if (not str(provenance.get("url", "")).startswith("https://download.geofabrik.de/")
                or provenance.get("license") != "ODbL-1.0"
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ValueError(f"Invalid {city} OSM extraction provenance")
    source = read_city_source(city, city_paths.source_db)
    coverage = source.coverage
    if not coverage["fetched"]:
        raise ValueError(f"No fetched {city} official announcements")
    if not coverage["selected"]:
        raise ValueError(f"No {city} municipality candidates; source scope needs review")
    to_metric, to_wgs = metric_transforms(spec.epsg)
    pois, poi_notes = pois_from_osm(
        json.loads(paths[0].read_text()), to_metric=to_metric, to_wgs=to_wgs,
    )
    gazetteer = Gazetteer(
        json.loads(paths[1].read_text()), places=pois,
        localities=json.loads(paths[2].read_text()),
        addresses=json.loads(paths[3].read_text()),
        to_metric=to_metric, to_wgs=to_wgs,
    )
    normalized = normalized_event_db(source.reports)
    scene_decision_path = runtime / "scene-decisions.json"
    scene_decisions = (
        scene_decision_index(json.loads(scene_decision_path.read_text()), city=city)
        if scene_decision_path.is_file() else {}
    )
    try:
        events = [
            compact(event) for event in events_from_db(
                normalized, gazetteer, scene_decisions=scene_decisions,
            )
        ]
    finally:
        normalized.close()
    if len(events) != coverage["selected"]:
        raise ValueError("Selected report count differs from extracted candidate count")
    if len({event["id"] for event in events}) != len(events):
        raise ValueError("Duplicate article IDs in candidate extraction")
    review = connect_review(runtime / "review.sqlite")
    counts = review_summary(review, city, events)
    review.close()
    methods = Counter(event["geocode_method"] for event in events)
    scene_report_ids = {
        event["id"] for event in events
        if event.get("scene_review_required") or "scene_locations" in event
    }
    audit = dict(
        city=city, source=spec.source, epsg=spec.epsg,
        archive_complete=source.archive_complete,
        coverage=coverage, located=sum(bool(event["coordinates"]) for event in events),
        geocode_methods=dict(sorted(methods.items())), review_counts=counts,
        missing_scene_decision_ids=sorted(scene_report_ids - set(scene_decisions)),
        poi_count=len(pois["features"]), poi_geometry_notes=poi_notes,
        publication_ready=False,
        publication_block="city map requires source scope and completeness checks, per-article review and owner approval",
    )
    runtime.mkdir(parents=True, exist_ok=True)
    candidate_path = runtime / "review-candidates.json"
    tmp = candidate_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(dict(city=city, events=events, changed_locations=[]),
                              ensure_ascii=False, separators=(",", ":")))
    tmp.replace(candidate_path)
    audit_path = runtime / "candidate-audit.json"
    tmp = audit_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(audit, ensure_ascii=False, indent=2))
    tmp.replace(audit_path)
    return audit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", choices=CITY_SETTINGS, required=True)
    args = parser.parse_args()
    print(json.dumps(stage(args.city), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
