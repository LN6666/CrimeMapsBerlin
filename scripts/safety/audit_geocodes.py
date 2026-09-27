"""Compare a frozen previous event snapshot with current rules on the same reports.

Outputs stay local: public code must not contain cached police narratives.
"""

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

from shapely.geometry import Point
from shapely.ops import transform

from crimemapsberlin.geocode import Gazetteer, events_from_db
from crimemapsberlin.spatial import TO_METRIC, pois_from_osm

ROOT = Path(__file__).resolve().parents[2]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--before", default=str(ROOT / ".runtime/safety/geocode-before.json"))
    p.add_argument("--db", default=str(ROOT / ".runtime/safety/police.sqlite"))
    p.add_argument("--output", default=str(ROOT / ".runtime/safety/geocode-comparison.json"))
    args = p.parse_args()
    raw = ROOT / "data/raw/safety"
    db = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("BEGIN")
    pois, _ = pois_from_osm(json.loads((raw / "berlin-pois.json").read_text()))
    gazetteer = Gazetteer(
        json.loads((raw / "streets.json").read_text()),
        places=pois,
        localities=json.loads((raw / "localities.json").read_text()),
        addresses=json.loads((raw / "addresses.json").read_text()),
    )
    after = events_from_db(db, gazetteer)
    before = {e["id"]: e for e in json.loads(Path(args.before).read_text())}
    changed_source = [
        e["id"] for e in after if e["id"] in before and e["source_sha256"] != before[e["id"]]["source_sha256"]
    ]
    if changed_source:
        raise SystemExit(f"Source changed since baseline; comparison refused: {changed_source}")
    paired = [e for e in after if e["id"] in before]
    transitions = []
    for e in paired:
        old = before[e["id"]]
        moved = None
        if old["coordinates"] and e["coordinates"]:
            a, b = (transform(TO_METRIC, Point(r["coordinates"])) for r in (old, e))
            moved = round(a.distance(b))
        if old["geocode_method"] != e["geocode_method"] or old["coordinates"] != e["coordinates"]:
            transitions.append(
                dict(
                    id=e["id"],
                    title=e["title"],
                    source_url=e["source_url"],
                    before_method=old["geocode_method"],
                    after_method=e["geocode_method"],
                    before_coordinates=old["coordinates"],
                    after_coordinates=e["coordinates"],
                    displacement_m=moved,
                    candidates=e["geocode_candidates"],
                    evidence=e["geocode_evidence"],
                    scope=e.get("location_scope"),
                )
            )
    result = dict(
        paired_reports=len(paired),
        new_reports_excluded=len(after) - len(paired),
        old_reports_missing=len(before) - len(paired),
        before_mapped=sum(bool(e["coordinates"]) for e in before.values()),
        after_mapped=sum(bool(e["coordinates"]) for e in paired),
        newly_mapped=sum(not before[e["id"]]["coordinates"] and bool(e["coordinates"]) for e in paired),
        no_longer_mapped=sum(bool(before[e["id"]]["coordinates"]) and not e["coordinates"] for e in paired),
        moved_over_275m=sum(
            t["displacement_m"] is not None and t["displacement_m"] > 275 for t in transitions
        ),
        methods=dict(Counter(e["geocode_method"] for e in paired)),
        before_unmatched_transitions=dict(
            Counter(e["geocode_method"] for e in paired if before[e["id"]]["geocode_method"] == "unmatched")
        ),
        mapped_is_not_accuracy=True,
        transitions=transitions,
    )
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    Path(args.output).with_name("geocode-after.json").write_text(json.dumps(after, ensure_ascii=False))
    print(json.dumps({k: v for k, v in result.items() if k != "transitions"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
