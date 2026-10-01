"""Revalidate explicitly reviewed Presseportal references without inferring scenes.

This optional boundary keeps the primary article identity intact. A caller supplies
its existing strict scene validator; each quotation is first checked inside its
declared individual article, never across concatenated article boundaries. All
files remain local. Neither an auxiliary review nor this check grants publication.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from urllib.robotparser import RobotFileParser

from .hamburg import ArticleParser

PUBLISHERS = {"6337": "Polizei Hamburg", "50510": "Polizei Duisburg"}
OFFICIAL_URL = re.compile(r"https://www\.presseportal\.de/blaulicht/pm/(6337|50510)/(\d+)")
BINDING_KEYS = {"manifest_file", "manifest_sha256", "source_ids", "evidence_sources"}
MANIFEST_KEYS = {
    "schema_version", "city", "primary_sources", "primary_decisions",
    "reference_reviews", "comparisons", "captures",
}


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _keys(value: object, keys: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label}: unexpected or missing fields")
    return value


def _require(condition: bool, label: str) -> None:
    if not condition:
        raise ValueError(label)


def _text(value: object) -> str:
    _require(isinstance(value, str) and bool(value.strip()), "Missing evidence text")
    return " ".join(value.split())


def _file(spec: object) -> bytes:
    spec = _keys(spec, {"file", "sha256"}, "file binding")
    path = Path(spec["file"])
    _require(path.is_absolute() and path.is_file(), f"Bound file unavailable: {path}")
    raw = path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == spec["sha256"], f"Stale bound file: {path}")
    return raw


def _json(spec: object) -> object:
    return json.loads(_file(spec))


def _index(rows: object, key: str) -> dict:
    _require(isinstance(rows, list) and bool(rows), "Empty source reference rows")
    result = {}
    for row in rows:
        _require(isinstance(row, dict) and isinstance(row.get(key), str), "Invalid reference row")
        _require(row[key] not in result, "Duplicate source reference ID")
        result[row[key]] = row
    return result


def evidence_leaves(value: object, path: str = "") -> dict[str, str]:
    """Enumerate quoted fields only; no classification or provenance selection."""
    leaves = {}
    if isinstance(value, dict):
        for key, item in value.items():
            pointer = path + "/" + key.replace("~", "~0").replace("/", "~1")
            if key == "evidence_quote":
                leaves[pointer] = _text(item)
            elif key == "evidence_quotes":
                _require(isinstance(item, list) and bool(item), "Empty quotation list")
                for i, quote in enumerate(item):
                    leaves[f"{pointer}/{i}"] = _text(quote)
            else:
                leaves.update(evidence_leaves(item, pointer))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            leaves.update(evidence_leaves(item, f"{path}/{i}"))
    return leaves


def _capture(ident: str, spec: object) -> dict:
    spec = _keys(spec, {"capture", "html", "body", "robots"}, "capture binding")
    raw = _json(spec["capture"])
    html = _file(spec["html"])
    body = _file(spec["body"]).decode("utf-8")
    robots = _file(spec["robots"]).decode("utf-8")
    match = OFFICIAL_URL.fullmatch(raw["source_url"])
    _require(bool(match) and match[2] == ident == raw["source_id"], "Unofficial reference identity")
    _require(raw["http_status"] == 200 and raw["response_url"] == raw["source_url"],
             "Reference response is not its verified official article")
    _require(raw.get("redirect_location") is None, "Reference capture contains a redirect")
    _require(raw["robots_allowed"] is True and raw["publisher_verified"] is True,
             "Unverified capture permissions or publisher")
    permission = RobotFileParser("https://www.presseportal.de/robots.txt")
    permission.parse(robots.splitlines())
    _require(permission.can_fetch("CrimeMapsBerlin", raw["source_url"]), "Robots disallows reference")
    parser = ArticleParser()
    parser.feed(html.decode("utf-8"))
    parsed = " ".join(parser.parts)
    publisher = PUBLISHERS[match[1]]
    _require(parser.customer.strip() == raw["expected_publisher"] == raw["observed_publisher"]
             == publisher, "Reference publisher mismatch")
    # Capture-side text files can have one serialization newline, not altered body bytes.
    _require(body in (raw["body"], raw["body"] + "\n") and parsed == raw["body"],
             "Captured HTML and extracted body differ")
    _require(len(parsed) >= 30 and hashlib.sha256(html).hexdigest() == raw["html_sha256"],
             "Invalid source HTML binding")
    _require(hashlib.sha256(parsed.encode()).hexdigest() == raw["source_sha256"],
             "Invalid source body binding")
    return raw


def _auxiliary_review(row: dict, capture: dict, ident: str) -> dict:
    _keys(row, {"decision", "decision_sha256"}, "reference review")
    d = row["decision"]
    _require(_digest(d) == row["decision_sha256"], "Stale reference review hash")
    _require(d["schema_version"] == 1 and d["city"] == "hamburg" and d["source_id"] == ident,
             "Reference review identity mismatch")
    for key in ("source_url", "source_sha256", "html_sha256"):
        _require(d[key] == capture[key], f"Reference review {key} mismatch")
    _require(d["publisher"] == capture["observed_publisher"], "Reviewed publisher mismatch")
    for key in ("full_body_read", "all_distinct_source_stages_reviewed",
                "all_formal_locations_reviewed", "source_scene_review_complete"):
        _require(d[key] is True, f"Incomplete reference review: {key}")
    for key in ("primary_2026_archive_record", "primary_map_announcement", "program_semantic_inference",
                "owner_approved", "publication_ready"):
        _require(d[key] is False, f"Reference may not claim primary coverage or approval: {key}")
    body = _text(capture["body"])
    for quote in evidence_leaves(d).values():
        _require(quote in body, "Reference review quotation missing from individual body")
    stages = _index(d["stages"], "stage_id")
    locations = _index(d["formal_locations"], "location_id") if d["formal_locations"] else {}
    linked = set()
    for key, stage in stages.items():
        _require(key.startswith(ident + ":reference-stage:"), "Foreign reference stage")
        _require(stage["independent_crime_count"] is None, "Reference stage fabricates crime count")
        _keys(stage["event_time"], {"date", "display", "precision", "evidence_quote"}, "reference time")
        _require(len(stage["formal_location_ids"]) == len(set(stage["formal_location_ids"])),
                 "Duplicate reference stage location")
        _require(set(stage["formal_location_ids"]) <= locations.keys(), "Dangling reference location")
        linked.update(stage["formal_location_ids"])
    _require(linked == locations.keys(), "Unreviewed reference location membership")
    for key, loc in locations.items():
        _require(key.startswith(ident + ":reference-location:") and loc["coordinates"] is None,
                 "Reference location invents coordinates or identity")
        _require(bool(_text(loc["poi_judgment"])) and bool(_text(loc["transit_judgment"])),
                 "Missing reference POI/transit judgment")
    return d


def validate_source_referenced_decision(
    value: dict, *, source: dict, city: str, source_id: str,
    primary_validator: Callable[[dict, dict, str, str], dict],
) -> dict:
    """Check current source, closed official reference graph and per-quote origin.

    The callback is the unchanged strict single-source validator. Only after every
    quotation has been validated in one declared body does it receive combined
    text. Review and city-scope quotations must still belong to the primary body.
    """
    _require(city == "hamburg", "Article reference adapter is only enabled for Hamburg")
    binding = _keys(value.get("source_reference_binding"), BINDING_KEYS, "source reference binding")
    manifest = _keys(_json({"file": binding["manifest_file"], "sha256": binding["manifest_sha256"]}),
                     MANIFEST_KEYS, "source reference manifest")
    _require(manifest["schema_version"] == 1 and manifest["city"] == city, "Wrong reference manifest")
    primary = _index(_json(manifest["primary_sources"]), "id")
    bases = _index(_json(manifest["primary_decisions"]), "source_id")
    captures = {sid: _capture(sid, spec) for sid, spec in manifest["captures"].items()}
    payload = _json(manifest["reference_reviews"])
    reviews = _index([r["decision"] for r in payload["reviews"]], "source_id")
    _require(set(reviews) == set(captures), "Review/capture source sets differ")
    review_hashes = {}
    for row in payload["reviews"]:
        sid = row["decision"]["source_id"]
        _auxiliary_review(row, captures[sid], sid)
        review_hashes[sid] = row["decision_sha256"]
    _require(source_id in primary and source_id in bases and source_id not in captures,
             "Missing primary binding or reference impersonates primary")
    for key in ("id", "url", "sha256", "body"):
        _require(source[key] == primary[source_id][key], f"Current primary {key} changed")
    _require(hashlib.sha256(source["body"].encode()).hexdigest() == source["sha256"],
             "Current primary body hash mismatch")
    for sid, base in bases.items():
        _require(sid in primary and _digest(base["decision"]) == base["decision_sha256"],
                 "Invalid original primary review")
        primary_validator(base["decision"], primary[sid], city, sid)
    pairs = _json(manifest["comparisons"])["comparisons"]
    graph = {}
    seen = set()
    for pair in pairs:
        parent, target = pair["parent_source_id"], pair["target_source_id"]
        _require((parent, target) not in seen and parent != target and target in captures,
                 "Duplicate, self or missing reference edge")
        seen.add((parent, target))
        if parent in primary:
            parent_source, parent_hash = primary[parent], bases[parent]["decision_sha256"]
            parent_stages = {s["incident_id"] for s in bases[parent]["decision"]["scene_inventory"]["incidents"]}
            parent_body, parent_sha = parent_source["body"], parent_source["sha256"]
        else:
            _require(parent in captures, "Missing comparison parent")
            parent_body, parent_sha = captures[parent]["body"], captures[parent]["source_sha256"]
            parent_hash = review_hashes[parent]
            parent_stages = {s["stage_id"] for s in reviews[parent]["stages"]}
        _require(pair["parent_source_sha256"] == parent_sha and pair["parent_review_sha256"] == parent_hash,
                 "Stale comparison parent")
        target_source = captures[target]
        _require(pair["target_source_url"] == target_source["source_url"]
                 and pair["target_source_sha256"] == target_source["source_sha256"]
                 and pair["target_review_sha256"] == review_hashes[target], "Stale comparison target")
        quote = pair["official_link_evidence_quote"]
        _require(quote == target_source["source_url"] and quote in _text(parent_body),
                 "Reference is not linked in the reviewed official parent body")
        _require(set(pair["parent_stage_ids"]) <= parent_stages
                 and set(pair["target_stage_ids"]) <= {s["stage_id"] for s in reviews[target]["stages"]},
                 "Dangling source comparison stage")
        _require(pair["automatic_occurrence_merge"] is False and pair["primary_count_increase"] == 0,
                 "Reference comparison cannot merge or add primary counts")
        graph.setdefault(parent, set()).add(target)
    selected = binding["source_ids"]
    _require(isinstance(selected, list) and bool(selected) and all(isinstance(s, str) for s in selected)
             and selected == sorted(set(selected)) and set(selected) <= captures.keys(),
             "Invalid selected reference IDs")
    reachable, frontier = set(), [source_id]
    while frontier:
        for sid in graph.get(frontier.pop(), set()):
            if sid not in reachable:
                reachable.add(sid)
                frontier.append(sid)
    _require(set(selected) == reachable, "Reference selection does not match the complete reviewed link graph")
    stripped = {k: v for k, v in value.items() if k != "source_reference_binding"}
    quotes = evidence_leaves(stripped)
    origins = binding["evidence_sources"]
    _require(isinstance(origins, dict) and set(origins) == quotes.keys(), "Missing or excess quotation origins")
    bodies = {source_id: _text(source["body"]), **{sid: _text(captures[sid]["body"]) for sid in selected}}
    for path, quote in quotes.items():
        origin = origins[path]
        _require(isinstance(origin, str) and origin in bodies and quote in bodies[origin],
                 f"Evidence is absent from its declared individual source: {path}")
        if path.startswith(("/review/", "/scope/")):
            _require(origin == source_id, "Primary review/scope evidence cannot borrow an auxiliary source")
    checked = primary_validator(stripped, {**source, "body": " \n ".join(bodies.values())}, city, source_id)
    _require(checked == stripped, "Referenced decision is not canonical")
    return {**checked, "source_reference_binding": binding}
