"""Publish an atomic, versioned static map snapshot from the official SQLite archive."""

import argparse
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import MultiLineString, mapping

from crimemapsberlin.collector import connect
from crimemapsberlin.geocode import Gazetteer, events_from_db
from crimemapsberlin.spatial import build_months, pois_from_osm
from crimemapsberlin.tiles import DX, DY, tiles

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "web/public/safety"
RAW = ROOT / "data/raw/safety"


def compact(value):
    # Public display coordinates need sub-metre precision, not 16 decimal places.
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, (list, tuple)):
        return [compact(v) for v in value]
    if isinstance(value, dict):
        return {k: compact(v) for k, v in value.items() if k != "location_geometry"}
    return value


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(compact(value), ensure_ascii=False, separators=(",", ":")))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=str(ROOT / ".runtime/safety/police.sqlite"))
    args = p.parse_args()
    db = connect(args.db)
    print("Building POIs and local gazetteer…", flush=True)
    pois, notes = pois_from_osm(json.loads((RAW / "berlin-pois.json").read_text()))
    required = [RAW / "localities.json", RAW / "addresses.json"]
    if not all(p.exists() for p in required):
        raise SystemExit("Re-run scripts/safety/extract_pbf.py to build locality and address indexes")
    gazetteer = Gazetteer(
        json.loads((RAW / "streets.json").read_text()),
        places=pois,
        localities=json.loads(required[0].read_text()),
        addresses=json.loads(required[1].read_text()),
    )
    db.execute("BEGIN")  # consistent read snapshot while the collector keeps writing
    events = events_from_db(db, gazetteer)
    if not events:
        raise SystemExit("No successfully fetched official reports; previous publication retained")
    # Include unclassified reports explicitly; never silently call them all crimes.
    months = build_months(events, pois)
    now = datetime.now(timezone.utc).isoformat()
    signature = hashlib.sha256(
        json.dumps(events, sort_keys=True).encode() + (RAW / "berlin-pois.source.json").read_bytes()
    ).hexdigest()[:16]
    generation = f"{signature}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    staging = OUT / ".building"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    for month, content in months.items():
        write(
            staging / f"months/{month}.json",
            dict(**content, events=[e for e in events if e["month"] == month]),
        )
    print("Partitioning spatial tiles…", flush=True)
    tile_index = {}
    roads = json.loads((RAW / "roads.json").read_text())
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
        city="Berlin",
        retrieved_at=now,
        generation=generation,
        coverage=coverage,
        last_completed_sync=json.loads(run[0]) if run else None,
        months={m: dict(count=len(v["event_ids"])) for m, v in months.items()},
        categories=sorted({e["category"] for e in events}),
        tile_index=tile_index,
        tile_size=[DX, DY],
        catalog=json.loads((ROOT / "data/safety/europe_sources.json").read_text()),
        zones=json.loads((ROOT / "data/safety/berlin_kbo.json").read_text()),
        metadata=dict(
            poi_count=len(pois["features"]),
            poi_geometry_notes=notes,
            source="Polizei Berlin official archive",
            time_basis="publication_month",
            hex_crs="EPSG:25833",
            hex_edge_m=[1100, 275],
            zoom_threshold=13,
            attribution="© OpenStreetMap contributors / Geofabrik (ODbL); Polizei Berlin",
        ),
    )
    review = [
        dict(
            id=e["id"],
            source_url=e["source_url"],
            method=e["geocode_method"],
            candidates=e["geocode_candidates"],
            evidence=e["geocode_evidence"],
        )
        for e in events
        if not e["coordinates"]
    ]
    write(ROOT / ".runtime/safety/review-queue.json", review)
    write(
        ROOT / ".runtime/safety/build-audit.json",
        dict(
            **coverage,
            mapped=len(events) - len(review),
            unlocated=len(review),
            geocode_methods=dict(Counter(e["geocode_method"] for e in events)),
            poi_count=len(pois["features"]),
            generation=generation,
            months=manifest["months"],
            poi_types=dict(Counter(f["properties"]["kind"] for f in pois["features"])),
        ),
    )
    # Manifest is replaced last; concurrent readers retain an internally consistent generation.
    staging.rename(OUT / generation)
    write(OUT / "manifest.tmp", manifest)
    (OUT / "manifest.tmp").replace(OUT / "manifest.json")
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
