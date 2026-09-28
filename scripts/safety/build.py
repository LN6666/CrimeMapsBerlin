"""Publish an atomic, versioned static map snapshot from the official SQLite archive."""

import argparse
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import MultiLineString, mapping

from crimemapsberlin.city_candidates import stage as stage_city_candidates
from crimemapsberlin.city_contract import CITY_SPECS, paths_for
from crimemapsberlin.collector import connect
from crimemapsberlin.geocode import Gazetteer, events_from_db
from crimemapsberlin.multiple_scenes import scene_decision_index
from crimemapsberlin.payload import compact
from crimemapsberlin.quality import location_changes, publication_problems
from crimemapsberlin.review import (
    connect as connect_review, owner_approved, review_packet, review_summary, reviewed_tags,
)
from crimemapsberlin.spatial import build_months, count_location, metric_transforms, pois_from_osm
from crimemapsberlin.tiles import DX, DY, tiles

ROOT = Path(__file__).resolve().parents[2]
CITY_SETTINGS = {
    city: dict(name=spec.name, epsg=spec.epsg, source=spec.source,
               attribution=spec.attribution)
    for city, spec in CITY_SPECS.items()
}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(compact(value), ensure_ascii=False, separators=(",", ":")))


def canonical_events(raw_events):
    """Use one rounded, validated event value for review, spatial work and JSON."""
    events = [compact(event) for event in raw_events]
    for event in events:
        count_location(event)
    return events


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--city", choices=CITY_SETTINGS, default="berlin")
    p.add_argument("--db")
    args = p.parse_args()
    city = args.city
    settings = CITY_SETTINGS[city]
    spec = CITY_SPECS[city]
    if city not in {"berlin", "hamburg"} or not spec.publication_enabled:
        # These source schemas have only local candidate contracts. Keeping an
        # explicit city allowlist prevents a future flag change from routing
        # them through Berlin's collector schema and bypassing city selection.
        if args.db:
            raise SystemExit("Candidate preparation blocked: --db override is not supported for staged cities")
        if not spec.candidate_enabled:
            raise SystemExit("Publication blocked: Munich source remains unverified; robots.txt disallows crawling")
        try:
            stage_city_candidates(city, root=ROOT)
        except (FileNotFoundError, ValueError) as exc:
            raise SystemExit(f"Candidate preparation blocked: {exc}") from exc
        raise SystemExit(f"Publication blocked: {city} has local review candidates only")
    city_paths = paths_for(city, ROOT)
    raw, runtime, out = city_paths.raw, city_paths.runtime, city_paths.public
    db = connect(args.db or runtime / "police.sqlite")
    to_metric, to_wgs = metric_transforms(settings["epsg"])
    print("Building POIs and local gazetteer…", flush=True)
    pois, notes = pois_from_osm(
        json.loads((raw / f"{city}-pois.json").read_text()),
        to_metric=to_metric, to_wgs=to_wgs,
    )
    required = [raw / "localities.json", raw / "addresses.json"]
    if not all(p.exists() for p in required):
        raise SystemExit("Re-run scripts/safety/extract_pbf.py to build locality and address indexes")
    gazetteer = Gazetteer(
        json.loads((raw / "streets.json").read_text()),
        places=pois,
        localities=json.loads(required[0].read_text()),
        addresses=json.loads(required[1].read_text()),
        to_metric=to_metric, to_wgs=to_wgs,
    )
    db.execute("BEGIN")  # consistent read snapshot while the collector keeps writing
    # Reviews, metric calculations and public JSON must see the same rounded values.
    scene_decision_path = runtime / "scene-decisions.json"
    scene_decisions = (
        scene_decision_index(json.loads(scene_decision_path.read_text()), city=city)
        if scene_decision_path.is_file() else {}
    )
    try:
        events = canonical_events(events_from_db(
            db, gazetteer, scene_decisions=scene_decisions,
        ))
    except ValueError as exc:
        raise SystemExit(f"Publication blocked: {exc}") from exc
    if not events:
        raise SystemExit("No successfully fetched official reports; previous publication retained")
    old_manifest_path = out / "manifest.json"
    old_manifest = json.loads(old_manifest_path.read_text()) if old_manifest_path.exists() else None
    prior_events = []
    if old_manifest:
        for month in old_manifest["months"]:
            month_path = out / old_manifest["generation"] / "months" / f"{month}.json"
            if not month_path.exists():
                raise SystemExit(f"Previous publication is missing {month_path}; refusing replacement")
            prior_events.extend(json.loads(month_path.read_text())["events"])
    changed_locations = location_changes(prior_events, events)
    # The initial review backlog should not allocate hundreds of MB of tiles.
    # Keep this candidate file local; it contains derived fields but no article bodies.
    candidate_events = events
    review_candidates_path = runtime / "review-candidates.json"
    write(review_candidates_path, dict(
        city=city, events=candidate_events, changed_locations=changed_locations,
    ))
    review_db = connect_review(runtime / "review.sqlite")
    review_counts = review_summary(review_db, city, candidate_events)
    approved = owner_approved(review_db, city, candidate_events, changed_locations)
    scene_report_ids = {
        event["id"] for event in candidate_events
        if event.get("scene_review_required") or "scene_locations" in event
    }
    missing_scene_decisions = sorted(scene_report_ids - set(scene_decisions))
    if (
        review_counts["pending"] or review_counts["uncertain"]
        or review_counts["needs_correction"] or not approved or missing_scene_decisions
    ):
        review_db.close()
        reason = (
            "LLM scene review incomplete" if missing_scene_decisions
            else "article review incomplete" if review_counts["supported"] != len(candidate_events)
            else "owner inspection and approval pending"
        )
        write(
            runtime / "publication-block.json",
            dict(
                reason=reason, review_counts=review_counts, owner_approved=approved,
                missing_scene_decision_ids=missing_scene_decisions,
            ),
        )
        raise SystemExit("Publication blocked: " + reason + ": " + str(review_counts))
    review_digest = review_packet(review_db, city, candidate_events)["decision_digest"]
    signature = hashlib.sha256(
        json.dumps(events, sort_keys=True).encode() + (raw / f"{city}-pois.source.json").read_bytes()
    ).hexdigest()[:16]
    if (
        old_manifest
        and old_manifest["generation"].startswith(signature + "-")
        and old_manifest.get("metadata", {}).get("review_digest") == review_digest
    ):
        review_db.close()
        (runtime / "publication-block.json").unlink(missing_ok=True)
        print("Candidate and approved reviews match the published generation; no new publication")
        return
    # Include unclassified reports explicitly; never silently call them all crimes.
    months = build_months(events, pois, to_metric=to_metric, to_wgs=to_wgs)
    now = datetime.now(timezone.utc).isoformat()
    generation = f"{signature}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    staging = out / ".building"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    print("Partitioning spatial tiles…", flush=True)
    tile_index = {}
    roads = json.loads((raw / "roads.json").read_text())
    for i, f in enumerate(roads["features"]):
        f["properties"]["id"] = f"road/{i}"
    partitions = tiles(roads["features"])
    tile_index["roads"] = sorted(partitions)
    for key, part in partitions.items():
        write(staging / f"roads/{key}.json", part)
    tile_index["pois"] = []
    for kind in sorted({f["properties"]["kind"] for f in pois["features"]}):
        partitions = tiles([f for f in pois["features"] if f["properties"]["kind"] == kind])
        for key, part in partitions.items():
            tile_index["pois"].append(f"{kind}/{key}")
            write(staging / f"pois/{kind}/{key}.json", part)
    major = []
    for road_class in ("motorway", "trunk", "primary", "secondary"):
        lines = [
            f["geometry"]["coordinates"]
            for f in roads["features"]
            if f["properties"].get("class") == road_class
        ]
        if lines:
            geometry = MultiLineString(lines).simplify(0.0001)
            major.append(
                dict(
                    type="Feature",
                    geometry=mapping(geometry),
                    properties={"id": road_class, "class": road_class},
                )
            )
    write(staging / "roads-overview.json", dict(type="FeatureCollection", features=major))
    write(
        staging / "search.json",
        [
            dict(
                id=f["properties"]["id"],
                name=f["properties"]["name"],
                kind=f["properties"]["kind"],
                center=f["properties"]["center"],
            )
            for f in pois["features"]
            if f["properties"]["name"] != f["properties"]["kind"]
        ],
    )
    coverage = dict(
        discovered=db.execute("SELECT count(*) FROM reports").fetchone()[0],
        fetched=len(events),
        failed=db.execute("SELECT count(*) FROM reports WHERE error IS NOT NULL").fetchone()[0],
        pending=db.execute("SELECT count(*) FROM reports WHERE body IS NULL").fetchone()[0],
    )
    run = db.execute(
        "SELECT summary FROM runs WHERE finished IS NOT NULL ORDER BY started DESC LIMIT 1"
    ).fetchone()
    manifest = dict(
        schema_version=2,
        city=settings["name"],
        retrieved_at=now,
        generation=generation,
        coverage=coverage,
        last_completed_sync=json.loads(run[0]) if run else None,
        months={m: dict(count=len(v["event_ids"])) for m, v in months.items()},
        categories=sorted({e["category"] for e in events}),
        tile_index=tile_index,
        tile_size=[DX, DY],
        catalog=json.loads((ROOT / "data/safety/europe_sources.json").read_text()),
        zones=json.loads((ROOT / "data/safety/berlin_kbo.json").read_text())
        if city == "berlin" else dict(places=[], features=[], geometry_status="not_applicable"),
        metadata=dict(
            poi_count=len(pois["features"]),
            poi_geometry_notes=notes,
            source=settings["source"],
            time_basis="publication_month",
            hex_crs=f"EPSG:{settings['epsg']}",
            hex_edge_m=[1100, 275],
            zoom_threshold=13,
            attribution=settings["attribution"],
        ),
    )
    review = [
        dict(
            id=e["id"],
            source_url=e["source_url"],
            method=e["geocode_method"],
            candidates=e["geocode_candidates"],
            evidence=e["geocode_evidence"],
            selection=e.get("location_selection"),
            excluded_context=e.get("excluded_location_context", []),
            other_scene_candidates=e.get("other_scene_candidates", []),
        )
        for e in events
        if not e["coordinates"]
    ]
    write(runtime / "review-queue.json", review)
    audit = dict(
        **coverage,
        mapped=len(events) - len(review),
        unlocated=len(review),
        road_ranges=sum(
            bool(e.get("candidate_road_geometry"))
            or any(bool(scene.get("candidate_road_geometry")) for scene in e.get("scene_locations", []))
            for e in events
        ),
        geocode_methods=dict(Counter(e["geocode_method"] for e in events)),
        poi_count=len(pois["features"]),
        generation=generation,
        months=manifest["months"],
        poi_types=dict(Counter(f["properties"]["kind"] for f in pois["features"])),
    )
    audit["review_counts"] = review_counts
    old_audit_path = runtime / "build-audit.json"
    old_audit = json.loads(old_audit_path.read_text()) if old_audit_path.exists() else None
    problems = publication_problems(
        manifest, audit, old_manifest, old_audit, changed_locations,
        review_counts,
        approved,
    )
    if problems:
        review_db.close()
        write(
            runtime / "publication-block.json",
            dict(
                generation=generation,
                checked_at=now,
                problems=problems,
                changed_locations=changed_locations,
                candidate_audit=audit,
            ),
        )
        shutil.rmtree(staging)
        raise SystemExit("Publication blocked: " + "; ".join(problems))
    tag_map = {
        event["id"]: reviewed_tags(review_db, city, event) for event in candidate_events
    }
    review_db.close()
    for month, content in months.items():
        write(
            staging / f"months/{month}.json",
            dict(**content, events=[
                dict(**compact(event), reviewed_tags=tag_map[event["id"]])
                for event in events if event["month"] == month
            ]),
        )
    manifest["metadata"]["review_status"] = "SOURCE_REVIEWED_AND_OWNER_APPROVED"
    manifest["metadata"]["review_digest"] = review_digest
    write(old_audit_path, audit)
    # Manifest is replaced last; concurrent readers retain an internally consistent generation.
    staging.rename(out / generation)
    write(out / "manifest.tmp", manifest)
    (out / "manifest.tmp").replace(out / "manifest.json")
    (runtime / "publication-block.json").unlink(missing_ok=True)
    print(
        json.dumps(
            dict(
                **coverage,
                mapped=len(events) - len(review),
                poi_count=len(pois["features"]),
                generation=generation,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
