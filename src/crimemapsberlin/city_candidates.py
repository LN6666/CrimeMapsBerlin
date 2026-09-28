"""Stage a city's local source and GIS extraction for per-article review.

This command creates no public map files. City data and source bodies stay in
ignored local directories until source review and owner inspection are complete.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from crimemapsberlin.collector import connect as connect_source
from crimemapsberlin.geocode import Gazetteer, events_from_db
from crimemapsberlin.payload import compact
from crimemapsberlin.review import connect as connect_review, review_summary
from crimemapsberlin.spatial import metric_transforms, pois_from_osm

ROOT = Path(__file__).resolve().parents[2]
CITY_SETTINGS = {"hamburg": dict(epsg=25832, source="Polizei Hamburg / Presseportal")}


def stage(city: str, *, root: Path = ROOT) -> dict:
    if city not in CITY_SETTINGS:
        raise ValueError(f"No checked city extraction configuration: {city}")
    runtime = root / ".runtime/safety/cities" / city
    raw = root / "data/raw/safety/cities" / city
    paths = [raw / f"{city}-pois.json", raw / "streets.json",
             raw / "localities.json", raw / "addresses.json"]
    if not all(path.is_file() for path in paths):
        raise FileNotFoundError(f"Missing {city} OSM indexes; fetch and extract the city PBF first")
    db_path = runtime / "police.sqlite"
    if not db_path.is_file():
        raise FileNotFoundError(f"Missing {city} official announcement checkpoint")
    source = connect_source(db_path)
    source.execute("BEGIN")
    coverage_row = source.execute(
        """SELECT count(*) AS discovered, sum(body IS NOT NULL) AS fetched,
        sum(body IS NULL) AS pending, sum(error IS NOT NULL) AS failed FROM reports"""
    ).fetchone()
    coverage = {key: coverage_row[key] or 0 for key in coverage_row.keys()}
    if not coverage["fetched"]:
        raise ValueError(f"No fetched {city} official announcements")
    to_metric, to_wgs = metric_transforms(CITY_SETTINGS[city]["epsg"])
    pois, poi_notes = pois_from_osm(
        json.loads(paths[0].read_text()), to_metric=to_metric, to_wgs=to_wgs,
    )
    gazetteer = Gazetteer(
        json.loads(paths[1].read_text()), places=pois,
        localities=json.loads(paths[2].read_text()),
        addresses=json.loads(paths[3].read_text()),
        to_metric=to_metric, to_wgs=to_wgs,
    )
    events = [compact(event) for event in events_from_db(source, gazetteer)]
    if len(events) != coverage["fetched"]:
        raise ValueError("Fetched report count differs from extracted candidate count")
    if len({event["id"] for event in events}) != len(events):
        raise ValueError("Duplicate article IDs in candidate extraction")
    review = connect_review(runtime / "review.sqlite")
    counts = review_summary(review, city, events)
    review.close()
    methods = Counter(event["geocode_method"] for event in events)
    audit = dict(
        city=city, source=CITY_SETTINGS[city]["source"], epsg=CITY_SETTINGS[city]["epsg"],
        coverage=coverage, located=sum(bool(event["coordinates"]) for event in events),
        geocode_methods=dict(sorted(methods.items())), review_counts=counts,
        poi_count=len(pois["features"]), poi_geometry_notes=poi_notes,
        publication_ready=False,
        publication_block="city map requires complete source, per-article review and owner approval",
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
    source.close()
    return audit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", choices=CITY_SETTINGS, required=True)
    args = parser.parse_args()
    print(json.dumps(stage(args.city), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
