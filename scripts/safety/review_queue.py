"""Prepare local bounded LLM-review batches and record source-backed decisions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from crimemapsberlin.collector import connect as connect_source
from crimemapsberlin.review import (
    connect as connect_review,
    fingerprint,
    owner_approved,
    record_owner_approval,
    record_reviews,
    review_packet,
    review_status,
    review_summary,
)

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / ".runtime/safety"
SUPPORTED_CITIES = ("berlin", "hamburg")
SOURCE_FIRST_PROTOCOL = (
    "Read source_body before extracted. Independently identify the announcement type, "
    "minimum number of distinct incidents, and every physical location with its role. "
    "Only then compare extracted and reject omitted, merged, misclassified, or falsely "
    "located scenes. A missing scene_locations field is not evidence of a single scene."
)


def city_runtime(city: str) -> Path:
    return RUNTIME if city == "berlin" else RUNTIME / "cities" / city


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", choices=SUPPORTED_CITIES, default="berlin")
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--source-db", type=Path)
    parser.add_argument("--review-db", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    batch = commands.add_parser("batch")
    batch.add_argument("--limit", type=int, default=30)
    batch.add_argument("--out", type=Path)
    record = commands.add_parser("record")
    record.add_argument("--in", dest="input", type=Path, required=True)
    packet = commands.add_parser("packet")
    packet.add_argument("--out", type=Path)
    approve = commands.add_parser("approve")
    approve.add_argument("--in", dest="input", type=Path, required=True)
    commands.add_parser("status")
    args = parser.parse_args()
    runtime = city_runtime(args.city)
    args.candidates = args.candidates or runtime / "review-candidates.json"
    args.source_db = args.source_db or runtime / "police.sqlite"
    args.review_db = args.review_db or runtime / "review.sqlite"
    if args.command == "batch":
        args.out = args.out or runtime / "review-batch.json"
    elif args.command == "packet":
        args.out = args.out or runtime / "owner-review-packet.json"
    candidate = json.loads(args.candidates.read_text())
    city = candidate["city"]
    if city != args.city:
        raise SystemExit("Candidate city differs from selected city")
    events = candidate["events"]
    changed_locations = candidate.get("changed_locations", [])
    if len({event["id"] for event in events}) != len(events):
        raise SystemExit("Duplicate report IDs in review candidates")
    reviews = connect_review(args.review_db)
    source = connect_source(args.source_db)
    if args.command == "batch":
        if args.limit < 1:
            parser.error("batch limit must be positive")
        items = []
        for event in events:
            if review_status(reviews, city, event) != "pending":
                continue
            row = source.execute(
                "SELECT body,sha256 FROM reports WHERE id=?", (event["id"],)
            ).fetchone()
            if not row or row["sha256"] != event["source_sha256"]:
                raise SystemExit("Source changed; rebuild candidates before review")
            items.append(
                dict(
                    id=event["id"], source_url=event["source_url"],
                    source_sha256=event["source_sha256"],
                    extraction_sha256=fingerprint(event), source_body=row["body"],
                    extracted=event,
                )
            )
            if len(items) >= args.limit:
                break
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(
            dict(city=city, review_protocol=SOURCE_FIRST_PROTOCOL, items=items),
            ensure_ascii=False, indent=2,
        ))
        print(json.dumps(dict(city=city, batch=len(items), output=str(args.out))))
    elif args.command == "record":
        incoming = json.loads(args.input.read_text())
        if incoming.get("city") != city:
            raise SystemExit("Decision city differs from candidate city")
        ids = [str(decision["id"]) for decision in incoming["decisions"]]
        bodies = {}
        for row in source.execute(
            "SELECT id,body FROM reports WHERE body IS NOT NULL"
        ):
            if row["id"] in ids:
                bodies[row["id"]] = row["body"]
        count = record_reviews(reviews, city, events, bodies, incoming["decisions"])
        print(json.dumps(dict(recorded=count, remaining=review_summary(reviews, city, events))))
    elif args.command == "packet":
        result = review_packet(reviews, city, events, changed_locations)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(dict(city=city, count=result["count"],
                              decision_digest=result["decision_digest"], output=str(args.out))))
    elif args.command == "approve":
        approval = json.loads(args.input.read_text())
        digest = record_owner_approval(reviews, city, events, approval, changed_locations)
        print(json.dumps(dict(city=city, owner_approved=True, decision_digest=digest)))
    else:
        summary = review_summary(reviews, city, events)
        result = dict(city=city, total=len(events), **summary)
        if summary["supported"] == len(events):
            result["decision_digest"] = review_packet(
                reviews, city, events, changed_locations,
            )["decision_digest"]
            result["owner_approved"] = owner_approved(
                reviews, city, events, changed_locations,
            )
        else:
            result["owner_approved"] = False
        print(json.dumps(result))
    reviews.close()
    source.close()


if __name__ == "__main__":
    main()
