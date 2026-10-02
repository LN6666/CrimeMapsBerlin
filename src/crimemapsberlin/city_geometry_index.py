"""Build a local, source-bound OSM geometry index for LLM-reviewed scenes.

The index contains named OSM objects, roads and addresses inside one verified
municipal boundary.  It does not match a police narrative to an OSM object and
does not choose a display geometry.  Those semantic choices remain explicit
LLM review decisions; this module only supplies checked source geometry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import osmium
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPolygon,
    Point,
    Polygon,
    mapping,
    shape,
)
from shapely.prepared import prep

from .poi_cities import (
    POI_CITY_SPECS,
    boundary_for_city,
    geometry_covered_by,
    load_verified_source,
)

SCHEMA_VERSION = 1
PIPELINE_VERSION = 3
SUPPORTED_PIPELINE_VERSIONS = {1, 2, 3, 4, 5, 6, 7}
NAME_KEYS = ("name", "official_name", "short_name", "alt_name", "loc_name", "old_name")
TAG_KEYS = {
    *NAME_KEYS,
    "ref",
    "area",
    "level",
    "tram",
    "subway",
    "bus",
    "train",
    "highway",
    "place",
    "boundary",
    "admin_level",
    "amenity",
    "shop",
    "tourism",
    "leisure",
    "landuse",
    "natural",
    "railway",
    "public_transport",
    "type",
    "route",
    "from",
    "to",
    "operator",
    "network",
    "building",
    "addr:street",
    "addr:housenumber",
    "wikidata",
    "wikipedia",
}
_SPACE = re.compile(r"\s+")
OPERATIONAL_HIGHWAYS = {
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified",
    "residential", "living_street", "service", "pedestrian", "track", "footway",
    "path", "cycleway", "steps", "bridleway",
}


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def normalized_name(value: str) -> str:
    """Return a deterministic lookup key without deciding name equivalence."""
    return _SPACE.sub(" ", unicodedata.normalize("NFKC", value).strip()).casefold()


def _names(tags: dict[str, str]) -> list[str]:
    names = []
    keys = (*NAME_KEYS, "ref") if tags.get("highway") else NAME_KEYS
    for key in keys:
        for raw in tags.get(key, "").split(";"):
            value = _SPACE.sub(" ", raw.strip())
            if value:
                names.append(value)
    street = _SPACE.sub(" ", tags.get("addr:street", "").strip())
    number = _SPACE.sub(" ", tags.get("addr:housenumber", "").strip())
    if street and number:
        names.append(f"{street} {number}")
    return sorted(set(names), key=lambda value: (normalized_name(value), value))


def _roles(tags: dict[str, str], names: list[str]) -> list[str]:
    roles = []
    if tags.get("highway") and names:
        roles.append("road")
    if tags.get("addr:street") and tags.get("addr:housenumber"):
        roles.append("address")
    if tags.get("boundary") == "administrative" and names:
        roles.append("administrative_boundary")
    if names:
        roles.append("named_object")
    return roles


def _parts(geometry, dimension: str):
    if dimension == "point":
        return geometry if isinstance(geometry, Point) else None
    if dimension == "line":
        if isinstance(geometry, (LineString, MultiLineString)):
            return geometry
        if isinstance(geometry, GeometryCollection):
            lines = [
                part
                for part in geometry.geoms
                if isinstance(part, (LineString, MultiLineString)) and not part.is_empty
            ]
            if not lines:
                return None
            flattened = []
            for line in lines:
                flattened.extend(line.geoms if isinstance(line, MultiLineString) else [line])
            return MultiLineString(flattened) if len(flattened) > 1 else flattened[0]
        return None
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    if isinstance(geometry, GeometryCollection):
        polygons = [
            part
            for part in geometry.geoms
            if isinstance(part, (Polygon, MultiPolygon)) and not part.is_empty
        ]
        flattened = []
        for polygon in polygons:
            flattened.extend(polygon.geoms if isinstance(polygon, MultiPolygon) else [polygon])
        if not flattened:
            return None
        return MultiPolygon(flattened) if len(flattened) > 1 else flattened[0]
    return None


def _clip(geometry, border, dimension: str):
    if geometry.is_empty or not geometry.is_valid:
        return None
    if dimension == "point":
        return geometry if border.covers(geometry) else None
    return _parts(geometry.intersection(border), dimension)


def _object(
    *, ident: str, tags: dict[str, str], geometry, dimension: str
) -> dict | None:
    names = _names(tags)
    roles = _roles(tags, names)
    if not roles:
        return None
    return {
        "id": ident,
        "source_url": f"https://www.openstreetmap.org/{ident.removeprefix('osm/')}",
        "roles": roles,
        "names": names,
        "tags": {key: tags[key] for key in sorted(TAG_KEYS & tags.keys())},
        "dimension": dimension,
        "geometry": mapping(geometry),
    }


def native_unnamed_way_object(*, source_way: dict, source_metadata: dict, border) -> dict | None:
    """Retain a verified unnamed operational way, never inventing a name.

    This is an opt-in pipeline-4 object. Its complete native node sequence and
    raw tags remain in the proof; default named-index generation is unchanged.
    Source acquisition must read these values from the hash-verified PBF.
    """
    if set(source_way) != {"id", "tags", "node_ids", "geometry"}:
        raise ValueError("native unnamed way needs exact source fields")
    ident, tags, node_ids = source_way["id"], source_way["tags"], source_way["node_ids"]
    if type(ident) is not int or ident <= 0 or not isinstance(tags, dict):
        raise ValueError("invalid native way ID or tags")
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in tags.items()):
        raise ValueError("native way tags must be raw strings")
    if _names(tags) or tags.get("highway") not in OPERATIONAL_HIGHWAYS:
        raise ValueError("native unnamed way must be an unnamed operational highway")
    if tags.get("area") == "yes" or tags.get("public_transport") in {"platform", "stop_position"}:
        raise ValueError("platforms and highway areas are not unnamed road lines")
    if any(tags.get(f"{prefix}:{kind}") not in {None, "", "no", "false", "0"}
           for prefix in ("construction", "proposed", "disused", "abandoned", "razed")
           for kind in ("highway", "railway")):
        raise ValueError("inactive native ways cannot become unnamed roads")
    geometry = shape(source_way["geometry"])
    if (geometry.geom_type != "LineString" or geometry.is_empty or not geometry.is_valid
            or not isinstance(node_ids, list) or len(node_ids) != len(geometry.coords)
            or any(type(i) is not int or i <= 0 for i in node_ids)):
        raise ValueError("native way needs a valid line and its complete node sequence")
    clipped = _clip(geometry, border, "line")
    if clipped is None or clipped.is_empty:
        return None
    return {
        "id": f"osm/way/{ident}",
        "source_url": f"https://www.openstreetmap.org/way/{ident}",
        "roles": ["road"], "names": [],
        # Keep grade/direction tags as well as the usual indexed fields.
        "tags": {k: tags[k] for k in sorted((TAG_KEYS | {"layer", "bridge", "tunnel", "oneway"}) & tags.keys())},
        "dimension": "line", "geometry": mapping(clipped),
        "native_unnamed_way_source_proof": {
            "schema_version": 1, "source_pbf_sha256": source_metadata["sha256"],
            "source_way_sha256": _digest(source_way), "source_way": source_way,
            "clipped_to_municipality": True,
        },
    }


def _valid_native_unnamed_way(row: dict, *, pipeline_version: int, source_metadata: dict, border) -> bool:
    if pipeline_version not in {4, 5, 6, 7}:
        return False
    proof = row.get("native_unnamed_way_source_proof")
    if not isinstance(proof, dict) or set(proof) != {
        "schema_version", "source_pbf_sha256", "source_way_sha256", "source_way", "clipped_to_municipality"
    }:
        return False
    if (proof["schema_version"] != 1 or proof["clipped_to_municipality"] is not True
            or proof["source_pbf_sha256"] != source_metadata["sha256"]
            or proof["source_way_sha256"] != _digest(proof["source_way"])):
        return False
    try:
        expected = native_unnamed_way_object(source_way=proof["source_way"], source_metadata=source_metadata, border=border)
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
    return expected is not None and _digest({k: row.get(k) for k in expected}) == _digest(expected)


def native_facility_reference_object(*, source_object: dict, source_cache_sha256: str,
                                    source_metadata: dict, border) -> dict:
    """Opt-in facilities retain raw ref/tags, never invented names.

    Acquisition provides the original PBF object and a bound local cache. The
    separate scene decision establishes which facility is a source reference.
    These objects cannot become roads, platforms or exact event/count points.
    """
    required = {"id", "tags", "geometry"}
    optional = {"version", "timestamp", "node_ids"}
    if (not isinstance(source_object, dict) or not required <= source_object.keys()
            or source_object.keys() - required - optional):
        raise ValueError("native facility needs original source fields")
    ident, tags = source_object["id"], source_object["tags"]
    if (not isinstance(ident, str) or not re.fullmatch(r"osm/(node|way)/[1-9][0-9]*", ident)
            or not isinstance(tags, dict)
            or not all(isinstance(k, str) and isinstance(v, str) for k, v in tags.items())
            or _names(tags)):
        raise ValueError("native unnamed facility identity or tags are invalid")
    if (not isinstance(source_cache_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", source_cache_sha256)
            or not re.fullmatch(r"[0-9a-f]{64}", source_metadata.get("sha256", ""))):
        raise ValueError("native facility needs bound cache and PBF digests")
    geometry = shape(source_object["geometry"])
    if geometry.is_empty or not geometry.is_valid or not border.covers(geometry):
        raise ValueError("native facility is invalid or outside the municipality")
    if tags.get("barrier") == "gate" and tags.get("access") == "private" and tags.get("ref", "").strip():
        kind, expected_type, expected_id = "private_gate", "Point", "osm/node/"
    elif tags.get("aeroway") == "parking_position" and tags.get("ref", "").strip():
        kind, expected_type, expected_id = "aircraft_stand", "LineString", "osm/way/"
    elif tags.get("railway") == "level_crossing" and tags.get("crossing:barrier") == "double_half":
        kind, expected_type, expected_id = "barrier_level_crossing", "Point", "osm/node/"
    elif tags.get("building") == "train_station":
        kind, expected_type, expected_id = "train_station_building", "LineString", "osm/way/"
    else:
        raise ValueError("native facility has no supported original physical identity")
    if geometry.geom_type != expected_type or not ident.startswith(expected_id):
        raise ValueError("native facility type differs from its original object")
    if expected_type == "LineString":
        nodes = source_object.get("node_ids")
        if (not isinstance(nodes, list) or len(nodes) != len(geometry.coords)
                or any(type(node) is not int or node <= 0 for node in nodes)):
            raise ValueError("native linear facility needs its complete original node sequence")
        if kind == "train_station_building":
            if len(nodes) < 4 or nodes[0] != nodes[-1] or geometry.coords[0] != geometry.coords[-1]:
                raise ValueError("native station building needs its original closed node ring")
            # A closed tagged building way supplies its exact footprint; no
            # buffer, clipping, name, centre or underground floor is inferred.
            geometry = Polygon(geometry.coords)
            if geometry.is_empty or not geometry.is_valid or not border.covers(geometry):
                raise ValueError("native station building footprint is invalid or outside the municipality")
    elif "node_ids" in source_object:
        raise ValueError("a native facility point cannot carry invented way nodes")
    return {
        "id": ident, "source_url": f"https://www.openstreetmap.org/{ident.removeprefix('osm/')}",
        "roles": ["facility_reference"], "names": [], "tags": dict(sorted(tags.items())),
        "dimension": "area" if kind == "train_station_building" else "point" if expected_type == "Point" else "line",
        "geometry": mapping(geometry), "native_facility_kind": kind,
        "native_facility_source_proof": {
            "schema_version": 1, "source_pbf_sha256": source_metadata["sha256"],
            "source_cache_sha256": source_cache_sha256,
            "source_object_sha256": _digest(source_object), "source_object": source_object,
            "original_geometry_clipped": False,
        },
    }


def _valid_native_facility(row: dict, *, pipeline_version: int, source_metadata: dict, border) -> bool:
    proof = row.get("native_facility_source_proof")
    if pipeline_version not in {6, 7} or not isinstance(proof, dict) or set(proof) != {
        "schema_version", "source_pbf_sha256", "source_cache_sha256", "source_object_sha256",
        "source_object", "original_geometry_clipped",
    }:
        return False
    if row.get("native_facility_kind") == "train_station_building" and pipeline_version != 7:
        return False
    if (proof["schema_version"] != 1 or proof["original_geometry_clipped"] is not False
            or proof["source_pbf_sha256"] != source_metadata["sha256"]
            or proof["source_object_sha256"] != _digest(proof["source_object"])):
        return False
    try:
        expected = native_facility_reference_object(source_object=proof["source_object"],
            source_cache_sha256=proof["source_cache_sha256"], source_metadata=source_metadata, border=border)
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
    return _digest({k: row.get(k) for k in expected}) == _digest(expected)


def native_unnamed_water_area_object(*, source_area: dict, source_metadata: dict, border) -> dict | None:
    """Opt in a source water surface without inventing a name or event extent.

    Acquisition must retain the original closed node rings and relation members
    from a hash-verified PBF. The deterministic city overlay is separate from
    those original rings. Names are matched only by explicit semantic review.
    """
    if set(source_area) != {"id", "tags", "geometry", "rings", "relation", "version", "timestamp"}:
        raise ValueError("native water area needs exact source fields")
    ident, tags = source_area["id"], source_area["tags"]
    if (not isinstance(ident, str) or re.fullmatch(r"osm/(way|relation)/[1-9][0-9]*", ident) is None
            or not isinstance(tags, dict)
            or not all(isinstance(k, str) and isinstance(v, str) for k,v in tags.items())
            or _names(tags) or tags.get("natural") != "water"
            or tags.get("water") not in {"river", "basin", "harbour", "lake", "pond", "reservoir", "canal", "lock"}
            or tags.get("highway") or tags.get("building")
            or type(source_area["version"]) is not int or source_area["version"] <= 0
            or not isinstance(source_area["timestamp"], str) or not source_area["timestamp"]):
        raise ValueError("native unnamed water surface needs original ID, raw tags and source version")
    rings = source_area["rings"]
    if not isinstance(rings, list) or not rings:
        raise ValueError("native water area needs original node rings")
    observed_nodes = {}
    def checked_ring(node_ids, coordinates):
        if (not isinstance(node_ids, list) or not isinstance(coordinates, list)
                or len(node_ids) < 4 or len(node_ids) != len(coordinates)
                or node_ids[0] != node_ids[-1]
                or any(type(n) is not int or n <= 0 for n in node_ids)):
            raise ValueError("native water ring needs a closed original node sequence")
        for n,xy in zip(node_ids,coordinates,strict=True):
            if (not isinstance(xy, (list,tuple)) or len(xy) != 2
                    or any(type(v) not in {int,float} or not math.isfinite(v) for v in xy)
                    or not (-180 <= xy[0] <= 180 and -90 <= xy[1] <= 90)):
                raise ValueError("native water ring needs original finite WGS84 coordinates")
            if n in observed_nodes and observed_nodes[n] != tuple(xy):
                raise ValueError("a native water node cannot have different coordinates")
            observed_nodes[n] = tuple(xy)
        if tuple(coordinates[0]) != tuple(coordinates[-1]):
            raise ValueError("native water ring coordinates must close")
        return coordinates
    polygons=[]
    for part in rings:
        if (not isinstance(part,dict) or set(part) != {"outer_node_ids", "outer_coordinates", "inner_rings"}
                or not isinstance(part["inner_rings"],list)):
            raise ValueError("native water area needs exact outer/inner ring fields")
        holes=[]
        for inner in part["inner_rings"]:
            if not isinstance(inner,dict) or set(inner) != {"node_ids","coordinates"}:
                raise ValueError("native water hole needs exact source fields")
            holes.append(checked_ring(inner["node_ids"],inner["coordinates"]))
        polygons.append(Polygon(checked_ring(part["outer_node_ids"],part["outer_coordinates"]),holes))
    original = shape(source_area["geometry"])
    assembled = MultiPolygon(polygons)
    if (original.geom_type not in {"Polygon","MultiPolygon"} or original.is_empty
            or not original.is_valid or not assembled.is_valid or not original.equals(assembled)):
        raise ValueError("native water geometry must preserve all original rings and holes")
    relation=source_area["relation"]
    if ident.startswith("osm/way/"):
        if relation is not None or len(rings) != 1 or rings[0]["inner_rings"]:
            raise ValueError("a native water way cannot acquire relation members or holes")
    elif (not isinstance(relation,dict) or set(relation) != {"id","tags","members","version","timestamp"}
            or relation["id"] != int(ident.rsplit("/",1)[-1]) or relation["tags"] != tags
            or tags.get("type") != "multipolygon" or not isinstance(relation["members"],list)
            or not relation["members"] or relation["version"] != source_area["version"]
            or relation["timestamp"] != source_area["timestamp"]):
        raise ValueError("native water relation needs original identity, tags and members")
    if relation is not None:
        for member in relation["members"]:
            if (not isinstance(member,dict) or set(member) != {"type","ref","role"}
                    or member["type"] != "w" or type(member["ref"]) is not int or member["ref"] <= 0
                    or member["role"] not in {"outer","inner",""}):
                raise ValueError("native water relation members must retain outer/inner way roles")
    clipped = _clip(original,border,"polygon")
    if clipped is None or clipped.is_empty:
        return None
    return {"id":ident,"source_url":f"https://www.openstreetmap.org/{ident.removeprefix('osm/')}",
            "roles":["water_area"],"names":[],"tags":dict(sorted(tags.items())),
            "dimension":"polygon","geometry":mapping(clipped),
            "native_unnamed_water_area_source_proof":{"schema_version":1,
                "source_pbf_sha256":source_metadata["sha256"],"source_area_sha256":_digest(source_area),
                "source_area":source_area,"clipped_to_municipality":True}}


def _valid_native_unnamed_water_area(row: dict, *, pipeline_version: int, source_metadata: dict, border) -> bool:
    proof=row.get("native_unnamed_water_area_source_proof")
    if pipeline_version not in {5, 6, 7} or not isinstance(proof,dict) or set(proof) != {
        "schema_version","source_pbf_sha256","source_area_sha256","source_area","clipped_to_municipality"}:
        return False
    if (proof["schema_version"] != 1 or proof["clipped_to_municipality"] is not True
            or proof["source_pbf_sha256"] != source_metadata["sha256"]
            or proof["source_area_sha256"] != _digest(proof["source_area"])):
        return False
    try:
        expected=native_unnamed_water_area_object(source_area=proof["source_area"],source_metadata=source_metadata,border=border)
    except (KeyError,TypeError,ValueError,AttributeError):
        return False
    return expected is not None and _digest({k:row.get(k) for k in expected}) == _digest(expected)


def native_road_vertex_object(*, source_node: dict, source_way: dict,
                              source_metadata: dict, border) -> dict:
    """Opt in an actual road vertex as an endpoint, without naming an event."""
    if set(source_node) != {"id", "tags", "coordinates"} or set(source_way) != {"id", "tags", "node_ids", "geometry"}:
        raise ValueError("native road vertex needs exact source node and way fields")
    ident, tags = source_node["id"], source_node["tags"]
    if (type(ident) is not int or ident <= 0 or not isinstance(tags, dict)
            or not all(isinstance(k, str) and isinstance(v, str) for k, v in tags.items())):
        raise ValueError("native road vertex needs raw node ID/tags")
    way_tags, node_ids = source_way["tags"], source_way["node_ids"]
    if (type(source_way["id"]) is not int or source_way["id"] <= 0
            or not isinstance(way_tags, dict) or way_tags.get("highway") not in OPERATIONAL_HIGHWAYS
            or not all(isinstance(k, str) and isinstance(v, str) for k,v in way_tags.items())
            or way_tags.get("area") == "yes"
            or any(way_tags.get(f"{prefix}:{kind}") not in {None, "", "no", "false", "0"}
                   for prefix in ("construction", "proposed", "disused", "abandoned", "razed")
                   for kind in ("highway", "railway"))):
        raise ValueError("native vertex parent must be an operational source road")
    parent = shape(source_way["geometry"])
    if not isinstance(source_node["coordinates"], (list, tuple)) or len(source_node["coordinates"]) != 2:
        raise ValueError("native road vertex needs original two-dimensional coordinates")
    point = Point(source_node["coordinates"])
    if (parent.geom_type != "LineString" or parent.is_empty or not parent.is_valid
            or not isinstance(node_ids, list) or len(node_ids) != len(parent.coords)
            or any(type(n) is not int or n <= 0 for n in node_ids)
            or ident not in node_ids or not point.is_valid or not border.covers(point)
            or any(tuple(parent.coords[n]) != tuple(point.coords[0])
                   for n, node_id in enumerate(node_ids) if node_id == ident)):
        raise ValueError("road endpoint must be the actual source node at its original way vertex")
    return {"id": f"osm/node/{ident}", "source_url": f"https://www.openstreetmap.org/node/{ident}",
            "roles": ["road"], "names": [], "tags": tags, "dimension": "point", "geometry": mapping(point),
            "native_road_vertex_source_proof": {"schema_version": 1,
                "source_pbf_sha256": source_metadata["sha256"],
                "source_node": source_node, "source_node_sha256": _digest(source_node),
                "source_way": source_way, "source_way_sha256": _digest(source_way),
                "usage": "native_road_endpoint_only"}}


def _valid_native_road_vertex(row: dict, *, pipeline_version: int, source_metadata: dict, border) -> bool:
    proof = row.get("native_road_vertex_source_proof")
    if pipeline_version not in {4, 5, 6, 7} or not isinstance(proof, dict) or set(proof) != {
        "schema_version", "source_pbf_sha256", "source_node", "source_node_sha256",
        "source_way", "source_way_sha256", "usage"
    }:
        return False
    if (proof["schema_version"] != 1 or proof["usage"] != "native_road_endpoint_only"
            or proof["source_pbf_sha256"] != source_metadata["sha256"]
            or proof["source_node_sha256"] != _digest(proof["source_node"])
            or proof["source_way_sha256"] != _digest(proof["source_way"])):
        return False
    try:
        expected = native_road_vertex_object(source_node=proof["source_node"], source_way=proof["source_way"],
                                            source_metadata=source_metadata, border=border)
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
    return _digest({k: row.get(k) for k in expected}) == _digest(expected)


class GeometryScanner(osmium.SimpleHandler):
    """Collect source objects without linking them to reviewed police text."""

    def __init__(self, border):
        super().__init__()
        self.border = border
        self.prepared = prep(border)
        self.bounds = border.bounds
        self.factory = osmium.geom.GeoJSONFactory()
        self.objects: list[dict] = []
        self.rejected: Counter = Counter()

    def node(self, node):
        if not node.location.valid():
            return
        tags = dict(node.tags)
        names = _names(tags)
        if not names and not (
            tags.get("addr:street") and tags.get("addr:housenumber")
        ):
            return
        point = Point(node.location.lon, node.location.lat)
        xmin, ymin, xmax, ymax = self.bounds
        if not (
            xmin <= point.x <= xmax
            and ymin <= point.y <= ymax
            and self.prepared.covers(point)
        ):
            self.rejected["outside_city"] += 1
            return
        row = _object(
            ident=f"osm/node/{node.id}", tags=tags, geometry=point, dimension="point"
        )
        if row:
            self.objects.append(row)

    def way(self, way):
        tags = dict(way.tags)
        names = _names(tags)
        if not names and not (
            tags.get("addr:street") and tags.get("addr:housenumber")
        ):
            return
        try:
            coordinates = [(node.lon, node.lat) for node in way.nodes]
        except osmium.InvalidLocationError:
            self.rejected["way_missing_node"] += 1
            return
        if len(coordinates) < 2:
            self.rejected["way_too_short"] += 1
            return
        is_polygon = (
            tags.get("area") != "no"
            and (not tags.get("highway") or tags.get("area") == "yes")
            and len(coordinates) >= 4
            and coordinates[0] == coordinates[-1]
        )
        geometry = Polygon(coordinates) if is_polygon else LineString(coordinates)
        dimension = "polygon" if is_polygon else "line"
        clipped = _clip(geometry, self.border, dimension)
        if clipped is None or clipped.is_empty or not clipped.is_valid:
            self.rejected["invalid_or_outside_city"] += 1
            return
        row = _object(
            ident=f"osm/way/{way.id}", tags=tags, geometry=clipped, dimension=dimension
        )
        if row:
            self.objects.append(row)

    def area(self, area):
        if area.from_way():
            return
        tags = dict(area.tags)
        if not _names(tags):
            return
        try:
            geometry = shape(json.loads(self.factory.create_multipolygon(area)))
        except (RuntimeError, ValueError):
            self.rejected["relation_without_geometry"] += 1
            return
        clipped = _clip(geometry, self.border, "polygon")
        if clipped is None or clipped.is_empty or not clipped.is_valid:
            self.rejected["invalid_or_outside_city"] += 1
            return
        row = _object(
            ident=f"osm/relation/{area.orig_id()}",
            tags=tags,
            geometry=clipped,
            dimension="polygon",
        )
        if row:
            self.objects.append(row)


def write_geometry_index(
    *,
    city: str,
    objects: list[dict],
    border,
    boundary_metadata: dict,
    source_metadata: dict,
    output: Path,
    rejected: dict | None = None,
    pipeline_version: int = PIPELINE_VERSION,
) -> dict:
    """Validate and write an ignored local index from source OSM objects."""
    if city not in POI_CITY_SPECS:
        raise ValueError(f"Unsupported city: {city}")
    if pipeline_version not in SUPPORTED_PIPELINE_VERSIONS:
        raise ValueError("unsupported geometry pipeline version")
    retained = []
    seen = set()
    name_index: dict[str, list[str]] = defaultdict(list)
    for raw in sorted(objects, key=lambda row: row["id"]):
        ident = raw["id"]
        if ident in seen:
            raise ValueError(f"Duplicate OSM object ID: {ident}")
        seen.add(ident)
        geometry = shape(raw["geometry"])
        if geometry.is_empty or not geometry.is_valid or not geometry_covered_by(border, geometry):
            raise ValueError(f"OSM geometry escaped the city boundary: {ident}")
        row = {
            **raw,
            "roles": sorted(set(raw["roles"])),
            "names": sorted(
                set(raw["names"]), key=lambda value: (normalized_name(value), value)
            ),
            "geometry": mapping(geometry),
        }
        row["geometry_sha256"] = _digest(row["geometry"])
        if ((not row["names"] or "native_unnamed_way_source_proof" in row or "native_road_vertex_source_proof" in row or "native_unnamed_water_area_source_proof" in row or "native_facility_source_proof" in row)
                and not _valid_native_unnamed_way(row, pipeline_version=pipeline_version,
                                                 source_metadata=source_metadata, border=border)
                and not _valid_native_road_vertex(row, pipeline_version=pipeline_version,
                                                source_metadata=source_metadata, border=border)
                and not _valid_native_unnamed_water_area(row,pipeline_version=pipeline_version,
                                                       source_metadata=source_metadata,border=border)
                and not _valid_native_facility(row,pipeline_version=pipeline_version,
                                               source_metadata=source_metadata,border=border)):
            raise ValueError(f"invalid native unnamed way proof: {ident}")
        retained.append(row)
        for name in row["names"]:
            name_index[normalized_name(name)].append(ident)

    canonical_name_index = {
        name: sorted(set(ids)) for name, ids in sorted(name_index.items())
    }
    role_counts = Counter(role for row in retained for role in row["roles"])
    geometry_counts = Counter(shape(row["geometry"]).geom_type for row in retained)
    boundary_core = {
        "id": boundary_metadata["id"],
        "source_pbf_sha256": boundary_metadata["source_pbf_sha256"],
        "geometry": boundary_metadata["geometry"],
    }
    core = {
        "schema_version": SCHEMA_VERSION,
        "pipeline_version": pipeline_version,
        "city": city,
        "source_pbf_sha256": source_metadata["sha256"],
        "source_pbf_timestamp": source_metadata["pbf_timestamp"],
        "boundary_source_id": boundary_metadata["id"],
        "boundary_sha256": _digest(boundary_core),
        "objects": retained,
        "name_index": canonical_name_index,
    }
    result = {
        **core,
        "index_sha256": _digest(core),
        "object_count": len(retained),
        "name_count": len(canonical_name_index),
        "role_counts": dict(sorted(role_counts.items())),
        "geometry_counts": dict(sorted(geometry_counts.items())),
        "rejected": dict(sorted((rejected or {}).items())),
        "semantic_matching_performed": False,
        "publication_ready": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    temporary.replace(output)
    return result


def validate_geometry_index(
    payload: dict, *, city: str, border, boundary_metadata: dict, source_metadata: dict
) -> dict:
    """Read back the index and verify source, names, hashes and containment."""
    errors = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema version differs")
    if payload.get("pipeline_version") not in SUPPORTED_PIPELINE_VERSIONS:
        errors.append("pipeline version is unsupported")
    if payload.get("city") != city:
        errors.append("city differs")
    if payload.get("source_pbf_sha256") != source_metadata["sha256"]:
        errors.append("source PBF digest differs")
    if payload.get("source_pbf_timestamp") != source_metadata["pbf_timestamp"]:
        errors.append("source PBF timestamp differs")
    if payload.get("boundary_source_id") != boundary_metadata["id"]:
        errors.append("boundary source differs")
    boundary_core = {
        "id": boundary_metadata["id"],
        "source_pbf_sha256": boundary_metadata["source_pbf_sha256"],
        "geometry": boundary_metadata["geometry"],
    }
    if payload.get("boundary_sha256") != _digest(boundary_core):
        errors.append("boundary digest differs")
    if payload.get("publication_ready") is not False:
        errors.append("index must remain unpublished")
    if payload.get("semantic_matching_performed") is not False:
        errors.append("index claims a semantic match")

    objects = payload.get("objects")
    if not isinstance(objects, list):
        errors.append("objects are missing")
        objects = []
    rebuilt_names: dict[str, list[str]] = defaultdict(list)
    role_counts: Counter = Counter()
    geometry_counts: Counter = Counter()
    ids = []
    for row in objects:
        ident = row.get("id")
        ids.append(ident)
        try:
            geometry = shape(row["geometry"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"invalid geometry: {ident}")
            continue
        if geometry.is_empty or not geometry.is_valid or not geometry_covered_by(border, geometry):
            errors.append(f"geometry outside boundary: {ident}")
        geometry_counts[geometry.geom_type] += 1
        if row.get("geometry_sha256") != _digest(row["geometry"]):
            errors.append(f"geometry digest differs: {ident}")
        if "native_crossing_way_source_proof" in row:
            from .city_rail_crossing_reference import valid_crossing_way
            if not valid_crossing_way(row, source_pbf_sha256=source_metadata["sha256"]):
                errors.append(f"native crossing way proof differs: {ident}")
        names = row.get("names")
        if (
            not isinstance(names, list)
            or names
            != sorted(set(names), key=lambda value: (normalized_name(value), value))
        ):
            errors.append(f"names missing: {ident}")
            continue
        if ((not names or "native_unnamed_way_source_proof" in row or "native_road_vertex_source_proof" in row or "native_unnamed_water_area_source_proof" in row or "native_facility_source_proof" in row)
                and not _valid_native_unnamed_way(row, pipeline_version=payload.get("pipeline_version"),
                                                 source_metadata=source_metadata, border=border)
                and not _valid_native_road_vertex(row, pipeline_version=payload.get("pipeline_version"),
                                                source_metadata=source_metadata, border=border)
                and not _valid_native_unnamed_water_area(row,pipeline_version=payload.get("pipeline_version"),
                                                       source_metadata=source_metadata,border=border)
                and not _valid_native_facility(row,pipeline_version=payload.get("pipeline_version"),
                                               source_metadata=source_metadata,border=border)):
            errors.append(f"native unnamed way proof missing or invalid: {ident}")
        roles = row.get("roles")
        if not isinstance(roles, list) or not roles or roles != sorted(set(roles)):
            errors.append(f"roles missing or unsorted: {ident}")
        else:
            role_counts.update(roles)
        for name in names:
            rebuilt_names[normalized_name(name)].append(ident)
    if len(ids) != len(set(ids)) or None in ids:
        errors.append("object IDs are missing or duplicated")
    expected_names = {
        name: sorted(set(values)) for name, values in sorted(rebuilt_names.items())
    }
    if payload.get("name_index") != expected_names:
        errors.append("name index differs from objects")
    core = {
        key: payload.get(key)
        for key in (
            "schema_version",
            "pipeline_version",
            "city",
            "source_pbf_sha256",
            "source_pbf_timestamp",
            "boundary_source_id",
            "boundary_sha256",
            "objects",
            "name_index",
        )
    }
    if payload.get("index_sha256") != _digest(core):
        errors.append("index digest differs")
    if payload.get("object_count") != len(objects):
        errors.append("object count differs")
    if payload.get("name_count") != len(expected_names):
        errors.append("name count differs")
    if payload.get("role_counts") != dict(sorted(role_counts.items())):
        errors.append("role counts differ")
    if payload.get("geometry_counts") != dict(sorted(geometry_counts.items())):
        errors.append("geometry counts differ")
    return {"passed": not errors, "errors": errors}


def build_city_geometry_index(
    city: str, *, project_root: Path, runtime_root: Path, output: Path
) -> dict:
    pbf, source_metadata = load_verified_source(
        city, root=runtime_root, project_root=project_root
    )
    boundary_metadata, border = boundary_for_city(
        city, pbf, source_metadata, root=runtime_root
    )
    scanner = GeometryScanner(border)
    scanner.apply_file(str(pbf), locations=True)
    result = write_geometry_index(
        city=city,
        objects=scanner.objects,
        border=border,
        boundary_metadata=boundary_metadata,
        source_metadata=source_metadata,
        output=output,
        rejected=dict(scanner.rejected),
    )
    readback = json.loads(output.read_text(encoding="utf-8"))
    validation = validate_geometry_index(
        readback,
        city=city,
        border=border,
        boundary_metadata=boundary_metadata,
        source_metadata=source_metadata,
    )
    if not validation["passed"]:
        raise ValueError("; ".join(validation["errors"][:10]))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", choices=sorted(POI_CITY_SPECS), required=True)
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument(
        "--runtime-root",
        type=Path,
        default=Path(".runtime/safety/poi-cities"),
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = build_city_geometry_index(
        args.city,
        project_root=args.project_root.resolve(),
        runtime_root=args.runtime_root.resolve(),
        output=args.out.resolve(),
    )
    print(
        json.dumps(
            {key: value for key, value in result.items() if key not in {"objects", "name_index"}},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
