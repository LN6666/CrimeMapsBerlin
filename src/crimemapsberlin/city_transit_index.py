"""Add complete OSM route-relation geometry to a checked municipal index.

The caller selects a source mode and line. No police narrative is interpreted.
Every path member must exist and be operational in the verified source PBF.
Stops and platforms remain distinct source objects, never route path members.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import osmium
from shapely.geometry import LineString, mapping, shape
from shapely.ops import unary_union

from .city_geometry_index import (
    TAG_KEYS,
    _clip,
    _digest,
    _names,
    normalized_name,
    validate_geometry_index,
    write_geometry_index,
)
from .poi_cities import boundary_for_city, load_verified_source

MODES = {"subway", "tram", "train", "bus", "trolleybus", "ferry"}
PATH_ROLES = {"", "forward", "backward"}
INACTIVE = {"construction", "proposed", "disused", "abandoned", "razed"}


def _path_members(relation: dict) -> list[dict]:
    result = []
    for member in relation["members"]:
        role = member["role"]
        if role.startswith(("stop", "platform")):
            continue
        if member["type"] != "w" or role not in PATH_ROLES:
            raise ValueError(f"unsupported route path member: {member}")
        result.append(member)
    if not result:
        raise ValueError("route relation has no path ways")
    return result


def _operational_path(tags: dict, mode: str) -> bool:
    if any(tags.get(key) in INACTIVE for key in ("railway", "highway")):
        return False
    lifecycle = {
        "construction:railway", "construction:highway", "disused:railway",
        "disused:highway", "abandoned:railway", "abandoned:highway",
        "proposed:railway", "proposed:highway",
    }
    if any(tags.get(key) not in {None, "", "no", "false", "0"} for key in lifecycle):
        return False
    if mode == "subway":
        return tags.get("railway") in {"subway", "light_rail"}
    if mode == "tram":
        return tags.get("railway") in {"tram", "light_rail"}
    if mode == "train":
        return tags.get("railway") in {"rail", "light_rail", "narrow_gauge"}
    if mode in {"bus", "trolleybus"}:
        return bool(tags.get("highway"))
    return tags.get("route") == "ferry"


def route_object(relation: dict, ways: dict[int, dict], border) -> dict | None:
    """Derive one relation; missing/inactive members reject the whole route."""
    tags = relation["tags"]
    mode, line = tags.get("route"), tags.get("ref")
    if tags.get("type") != "route" or mode not in MODES or not line:
        raise ValueError("route needs a supported source mode and exact ref")
    members = _path_members(relation)
    member_ids = sorted({member["ref"] for member in members})
    missing = [ident for ident in member_ids if ident not in ways]
    if missing:
        raise ValueError(f"route path ways absent from source: {missing}")
    inactive = [ident for ident in member_ids if not _operational_path(ways[ident]["tags"], mode)]
    if inactive:
        raise ValueError(f"route has inactive or incompatible path ways: {inactive}")
    geometries = [shape(ways[ident]["geometry"]) for ident in member_ids]
    if any(g.geom_type != "LineString" or g.is_empty or not g.is_valid for g in geometries):
        raise ValueError("route has invalid member geometry")
    clipped = _clip(unary_union(geometries), border, "line")
    if clipped is None or clipped.is_empty:
        return None
    names = sorted({*_names(tags), line}, key=lambda n: (normalized_name(n), n))
    ident = f"osm/relation/{relation['id']}"
    return {
        "id": ident,
        "source_url": f"https://www.openstreetmap.org/relation/{relation['id']}",
        "roles": ["named_object", "transit_route"],
        "names": names,
        "tags": {key: tags[key] for key in sorted(TAG_KEYS & tags.keys())},
        "dimension": "line",
        "geometry": mapping(clipped),
        "transit_source_proof": {
            "schema_version": 1,
            "complete": True,
            "relation_id": relation["id"],
            "member_way_ids": member_ids,
            "member_way_count": len(member_ids),
            "member_sequence": [member["ref"] for member in members],
            "member_source_digest": _digest({str(i): ways[i] for i in member_ids}),
            "clipped_to_municipality": True,
        },
    }


class RouteScanner(osmium.SimpleHandler):
    def __init__(self, mode: str, line: str):
        super().__init__()
        self.mode, self.line = mode, line
        self.relations: list[dict] = []

    def relation(self, relation):
        tags = dict(relation.tags)
        if tags.get("type") == "route" and tags.get("route") == self.mode and tags.get("ref") == self.line:
            self.relations.append({
                "id": relation.id,
                "tags": tags,
                "members": [{"type": m.type, "ref": m.ref, "role": m.role} for m in relation.members],
            })


class MemberScanner(osmium.SimpleHandler):
    def __init__(self, selected: set[int]):
        super().__init__()
        self.selected = selected
        self.ways: dict[int, dict] = {}

    def way(self, way):
        if way.id not in self.selected:
            return
        try:
            coordinates = [(node.lon, node.lat) for node in way.nodes]
        except osmium.InvalidLocationError as exc:
            raise ValueError(f"route member {way.id} has missing nodes") from exc
        if len(coordinates) < 2:
            raise ValueError(f"route member {way.id} has too few nodes")
        self.ways[way.id] = {"tags": dict(way.tags), "geometry": mapping(LineString(coordinates))}


def enrich_index(*, city: str, mode: str, line: str, project_root: Path,
                 runtime_root: Path, index_path: Path, output: Path, proof_path: Path) -> dict:
    pbf, source = load_verified_source(city, root=runtime_root, project_root=project_root)
    boundary, border = boundary_for_city(city, pbf, source, root=runtime_root)
    current = json.loads(index_path.read_text(encoding="utf-8"))
    validation = validate_geometry_index(current, city=city, border=border,
                                         boundary_metadata=boundary, source_metadata=source)
    if not validation["passed"]:
        raise ValueError("invalid input geometry index: " + "; ".join(validation["errors"]))
    scanner = RouteScanner(mode, line)
    scanner.apply_file(str(pbf))
    if not scanner.relations:
        raise ValueError(f"no source route relations for {mode}/{line}")
    selected = {m["ref"] for r in scanner.relations for m in _path_members(r)}
    members = MemberScanner(selected)
    members.apply_file(str(pbf), locations=True)
    additions = []
    for relation in scanner.relations:
        row = route_object(relation, members.ways, border)
        if row is not None:
            additions.append(row)
    if not additions:
        raise ValueError("source routes have no municipal geometry")
    by_id = {row["id"]: row for row in current["objects"]}
    for row in additions:
        by_id[row["id"]] = row
    candidate = output.with_suffix(output.suffix + ".candidate")
    result = write_geometry_index(city=city, objects=list(by_id.values()), border=border,
                                 boundary_metadata=boundary, source_metadata=source,
                                 output=candidate, rejected=current.get("rejected"))
    readback = json.loads(candidate.read_text(encoding="utf-8"))
    check = validate_geometry_index(readback, city=city, border=border,
                                    boundary_metadata=boundary, source_metadata=source)
    if not check["passed"]:
        raise ValueError("enriched index readback failed: " + "; ".join(check["errors"]))
    proof = {
        "schema_version": 1, "city": city, "mode": mode, "line": line,
        "source_pbf_sha256": source["sha256"], "source_pbf_timestamp": source["pbf_timestamp"],
        "previous_index_sha256": current["index_sha256"],
        "index_sha256": result["index_sha256"],
        "route_relations": scanner.relations,
        "objects": additions,
        "path_way_count": len(selected),
        "readback_validation": check,
        "semantic_matching_performed": False, "publication_ready": False,
    }
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    candidate.replace(output)
    return {key: value for key, value in proof.items() if key not in {"route_relations", "objects"}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", required=True)
    parser.add_argument("--mode", required=True, choices=sorted(MODES))
    parser.add_argument("--line", required=True)
    parser.add_argument("--geometry-index", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--proof", required=True, type=Path)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--runtime-root", type=Path, default=Path(".runtime/safety/poi-cities"))
    args = parser.parse_args()
    print(json.dumps(enrich_index(city=args.city, mode=args.mode, line=args.line,
                                  project_root=args.project_root, runtime_root=args.runtime_root,
                                  index_path=args.geometry_index, output=args.out,
                                  proof_path=args.proof), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
