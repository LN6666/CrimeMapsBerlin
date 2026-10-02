"""Validate individually reviewed supporting captures; never merge source bodies.

The reviewer supplies quotation origins and visible descriptions. Scalar dates,
coordinates, classifications and approval remain with the existing source gates.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.robotparser import RobotFileParser


def _text(value):
    return " ".join(value.split())


def _file(spec):
    if not isinstance(spec, dict) or set(spec) != {"file", "sha256"}:
        raise ValueError("Supporting material needs an exact file/hash binding")
    path = Path(spec["file"])
    if not path.is_absolute():
        raise ValueError("Supporting material path must be absolute")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != spec["sha256"]:
        raise ValueError("Supporting material file changed")
    return raw


class _Content(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)

    def handle_data(self, value):
        if not self.skip and value.strip():
            self.parts.append(value.strip())


def _bundle(binding, source):
    if not isinstance(binding, dict) or set(binding) != {
        "review", "packet_manifest", "presentation", "evidence_sources"
    }:
        raise ValueError("Supporting material binding is incomplete")
    review = json.loads(_file(binding["review"]))
    packet = json.loads(_file(binding["packet_manifest"]))
    root = Path(binding["packet_manifest"]["file"]).parent
    if (review.get("schema_version") != 1 or review.get("city") != "hamburg"
            or packet.get("schema_version") != 1 or packet.get("city") != "hamburg"
            or review.get("generated_coordinates") is not False
            or review.get("owner_approved") is not False
            or review.get("publication_ready") is not False
            or not review.get("reviewer") or not review.get("reviewed_at")):
        raise ValueError("Supporting material review lacks its city/reviewer boundaries")
    for name, expected in packet["files"].items():
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Unsafe supporting packet path")
        _file({"file": str(root / path), "sha256": expected})
    review_name = Path(binding["review"]["file"]).relative_to(root).as_posix()
    if packet["files"].get(review_name) != binding["review"]["sha256"]:
        raise ValueError("Supporting review is outside its captured packet")
    cases = [r for r in review["source_cases"] if r["source_id"] == source["id"]]
    if len(cases) != 1 or cases[0]["primary_body_sha256"] != source["sha256"]:
        raise ValueError("Supporting material has a stale or foreign primary source")
    case = cases[0]
    primary = json.loads(_file({"file": case["primary"]["path"],
                                "sha256": case["primary"]["sha256"]}))
    if (primary["source_id"] != source["id"] or primary["source_url"] != source["url"]
            or primary["source_body"] != source["body"]
            or hashlib.sha256(source["body"].encode()).hexdigest() != source["sha256"]):
        raise ValueError("Supporting material primary body differs")
    captures = {}
    for ref in review["capture_manifests"]:
        payload = json.loads(_file({"file": ref["path"], "sha256": ref["sha256"]}))
        for capture in payload["records"]:
            if capture.get("result") in {"captured", "captured_binary"}:
                if capture["name"] in captures:
                    raise ValueError("Ambiguous supporting capture")
                captures[capture["name"]] = capture
    for name in case["references"]:
        capture = captures[name]
        final = capture["hops"][-1]
        if final["status"] != 200 or final["url"] != capture["response_url"]:
            raise ValueError("Supporting material has an unsuccessful final response")
        for hop in capture["hops"]:
            robots = hop["robots"]
            raw = _file({"file": robots["file"], "sha256": robots["sha256"]})
            parser = RobotFileParser()
            if robots["status"] == 200:
                parser.parse(raw.decode().splitlines())
            elif robots["status"] == 404:
                parser.parse([])
            else:
                raise ValueError("Supporting material permissions are unverified")
            if hop.get("robots_allowed") is not True or not parser.can_fetch(
                "CrimeMapsBerlin/0.1", hop["url"]
            ):
                raise ValueError("Supporting material robots denies acquisition")
        _file({"file": final["file"], "sha256": final["sha256"]})
    presentation = json.loads(_file(binding["presentation"]))
    selected = presentation["sources"][source["id"]]
    if (presentation.get("schema_version") != 1 or presentation.get("city") != "hamburg"
            or selected["source_sha256"] != source["sha256"]):
        raise ValueError("Supporting display belongs to a stale or foreign source")
    return case, captures, selected


def visible_materials(binding, *, source):
    """Return only authored links to versions verified in this source's packet."""
    case, captures, presentation = _bundle(binding, source)
    rows = []
    for item in presentation["materials"]:
        if (set(item) != {"reference", "label", "note"}
                or item["reference"] not in case["references"]
                or not all(isinstance(item[k], str) and item[k].strip() for k in item)):
            raise ValueError("Supporting display has unreviewed material or text")
        capture = captures[item["reference"]]
        rows.append({"source_url": capture["response_url"],
                     "source_sha256": capture["hops"][-1]["sha256"],
                     "label": item["label"], "note": item["note"]})
    return rows


def validate_supporting_decision(value, *, source, city, source_id, primary_validator):
    """Recheck each appended quote inside its own captured HTML document."""
    if city != "hamburg" or source_id != source["id"]:
        raise ValueError("Supporting decision belongs to a different city/source")
    binding = value["source_supporting_material_binding"]
    case, captures, _ = _bundle(binding, source)
    visible_materials(binding, source=source)
    origins = binding["evidence_sources"]
    if not isinstance(origins, dict):
        raise ValueError("Supporting decision needs explicit quotation origins")
    primary = copy.deepcopy(value)
    primary.pop("source_supporting_material_binding")
    grouped = {}
    for path, name in origins.items():
        if (not re.fullmatch(r"/scene_inventory/(incidents|formal_locations)/\d+/evidence_quotes/\d+", path)
                or name not in case["references"]):
            raise ValueError("Supporting quote has an unreviewed origin/path")
        capture = captures[name]
        if capture["result"] != "captured":
            raise ValueError("Supporting quote requires individually captured HTML text")
        final = capture["hops"][-1]
        content = _Content()
        content.feed(_file({"file": final["file"], "sha256": final["sha256"]}).decode())
        text = _text(" ".join(content.parts))
        parts = path.strip("/").split("/")
        try:
            container = primary[parts[0]][parts[1]][int(parts[2])][parts[3]]
            index = int(parts[4])
            quote = container[index]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Supporting quote points to missing evidence") from exc
        if not isinstance(quote, str) or len(quote) < 15 or quote != _text(quote) or quote not in text:
            raise ValueError("Supporting quote is absent from its individual document")
        grouped.setdefault(path.rsplit("/", 1)[0], (container, []))[1].append(index)
    for container, indices in grouped.values():
        if sorted(indices) != list(range(min(indices), len(container))):
            raise ValueError("Supporting quotes must follow retained primary evidence")
        for index in sorted(indices, reverse=True):
            del container[index]
        if not container:
            raise ValueError("Supporting phase must retain a primary announcement anchor")
    if primary_validator(primary, source, city, source_id) != primary:
        raise ValueError("Supporting primary decision is not canonical")
    return copy.deepcopy(value)
