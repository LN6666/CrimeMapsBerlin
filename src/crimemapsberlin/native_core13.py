"""Census core13 native background eligibility using checked PBF and boundaries.

One extraction invocation serves all selected cities in a region. Osmium scans
the PBF twice internally when assembling native multipolygons. No police record,
scene geometry, source association, count point or source review is touched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from pathlib import Path

import osmium
from shapely.geometry import LineString, Point, Polygon, mapping, shape
from shapely.ops import transform
from shapely.prepared import prep

from crimemapsberlin.poi_cities import POI_CITY_SPECS, clip_features, geometry_covered_by
from crimemapsberlin.poi_context import native_type_tags
from crimemapsberlin.spatial import metric_transforms

try:
    from .poi_scope import VERSION, core_kind, digest
except ImportError:
    from poi_scope import VERSION, core_kind, digest

FILTER_KEYS = ["amenity", "shop", "tourism", "leisure", "railway", "building",
               "aeroway", "highway", "public_transport"]


def file_sha(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


class RegionCore(osmium.SimpleHandler):
    """Literal type selection followed only by original native geometry."""

    def __init__(self, policy: dict, borders: dict):
        super().__init__()
        self.policy = policy
        self.borders = borders
        self.prepared = {city: prep(border) for city, border in borders.items()}
        self.features = {city: {} for city in borders}
        self.gaps = {city: [] for city in borders}
        self.region_relations_without_area = set()
        self.region_objects_without_geometry = {}
        self.factory = osmium.geom.GeoJSONFactory()

    def capture(self, ident: str, tags: dict, geometry):
        kind = core_kind(tags, self.policy)
        if kind is None:
            return
        if geometry.is_empty or not geometry.is_valid:
            for city, border in self.borders.items():
                if not geometry.is_empty and geometry.intersects(border):
                    self.gaps[city].append({"native_id": ident, "kind": kind,
                                            "reason": "invalid_original_native_geometry"})
            return
        for city, border in self.borders.items():
            if geometry.geom_type == "Point":
                inside = self.prepared[city].covers(geometry)
            else:
                inside = geometry.intersects(border)
            if inside:
                if ident in self.features[city]:
                    raise ValueError("Duplicate original native geometry identity")
                self.features[city][ident] = {"id": ident, "kind": kind, "tags": tags,
                                             "native_geometry": mapping(geometry)}

    def node(self, node):
        tags = dict(node.tags)
        if core_kind(tags, self.policy) is not None:
            if node.location.valid():
                self.capture(f"osm/node/{node.id}", tags, Point(node.location.lon, node.location.lat))
            else:
                self.region_objects_without_geometry[f"osm/node/{node.id}"] = "original_node_location_unavailable"

    def way(self, way):
        tags = dict(way.tags)
        if core_kind(tags, self.policy) is None:
            return
        try:
            coordinates = [(node.lon, node.lat) for node in way.nodes]
        except osmium.InvalidLocationError:
            self.region_objects_without_geometry[f"osm/way/{way.id}"] = "original_way_node_locations_unavailable"
            return  # No invented point/line when source node locations are absent.
        if len(coordinates) < 2:
            self.region_objects_without_geometry[f"osm/way/{way.id}"] = "original_way_has_no_supported_geometry"
            return
        geometry = Polygon(coordinates) if len(coordinates) >= 4 and coordinates[0] == coordinates[-1] else LineString(coordinates)
        self.capture(f"osm/way/{way.id}", tags, geometry)

    def relation(self, relation):
        tags = dict(relation.tags)
        if core_kind(tags, self.policy) is not None:
            self.region_relations_without_area.add(f"osm/relation/{relation.id}")

    def area(self, area):
        if area.from_way():
            return  # Closed ways are kept under their original way IDs.
        tags = dict(area.tags)
        if core_kind(tags, self.policy) is None:
            return
        ident = f"osm/relation/{area.orig_id()}"
        try:
            geometry = shape(json.loads(self.factory.create_multipolygon(area)))
        except (RuntimeError, ValueError):
            return
        self.region_relations_without_area.discard(ident)
        self.capture(ident, tags, geometry)


def native_display_features(city: str, objects: dict, border) -> tuple[list[dict], dict]:
    to_metric, to_wgs = metric_transforms(POI_CITY_SPECS[city].epsg)
    rows = []
    for ident, obj in sorted(objects.items()):
        geometry = shape(obj["native_geometry"])
        tags, kind = obj["tags"], obj["kind"]
        center = geometry if geometry.geom_type == "Point" else geometry.representative_point()
        if geometry.geom_type in {"LineString", "MultiLineString"}:
            display, mode = geometry, "native_line_reference"
        elif geometry.geom_type != "Point" and kind in {"station", "airport", "park", "parking", "marketplace", "shop", "attraction"}:
            display, mode = geometry, "osm_footprint"
        elif kind in {"station", "airport"}:
            display, mode = geometry, "footprint_missing"
        else:
            display = transform(to_wgs, transform(to_metric, center).buffer(50, quad_segs=8))
            mode = "50m_circle"
        # A native area can intersect the city while its representative is far
        # outside it. Keep that real area instead of losing legal geometry to an
        # empty display circle; its event location remains wholly unclaimed.
        if not display.intersects(border) and geometry.intersects(border):
            display, mode = geometry, "osm_footprint"
        obj_type, obj_id = ident.split("/")[1:]
        rows.append({"type": "Feature", "geometry": mapping(display),
                     "location_geometry": obj["native_geometry"], "properties": {
                         "id": ident, "kind": kind, "name": tags.get("name", kind),
                         "aliases": [alias for key in ["alt_name", "official_name", "short_name", "loc_name"]
                                     for alias in tags.get(key, "").split(";") if alias],
                         "geometry_mode": mode, "center": [center.x, center.y],
                         "source_url": f"https://www.openstreetmap.org/{obj_type}/{obj_id}",
                         "opening_hours": tags.get("opening_hours"), "wikidata": tags.get("wikidata"),
                         "osm_type_tags": native_type_tags(tags),
                         "original_native_geometry_sha256": digest(obj["native_geometry"]),
                         "scope_category": kind, "neutral_background_only": True,
                         "does_not_locate_or_count_event": True}})
    rows, clipping = clip_features({"type": "FeatureCollection", "features": rows}, border)
    for row in rows:
        if not geometry_covered_by(border, shape(row["geometry"])) or not geometry_covered_by(border, shape(row["location_geometry"])):
            raise ValueError("New neutral native geometry escaped its checked city boundary")
    return rows, clipping


def extract_region(*, region: str, cities: list[str], project_root: Path, out: Path, policy: dict) -> dict:
    code_sha = file_sha(Path(__file__))
    runtime = project_root / ".runtime/safety/poi-cities"
    source_file = runtime / "extracts" / f"{region}.osm.source.json"
    if not source_file.is_file():
        source_file = runtime / "extracts" / f"{region}.source.json"
    source = json.loads(source_file.read_text())
    pbf = project_root / source["external_local_path"] if source.get("external_local_path") else runtime / "extracts" / f"{region}.osm.pbf"
    borders, boundary_proofs = {}, {}
    for city in cities:
        path = runtime / "cities" / city / "boundary.geojson"
        raw = path.read_bytes()
        boundary = json.loads(raw)
        if boundary.get("source_pbf_sha256") not in {None, source["sha256"]}:
            raise ValueError("Checked native city boundary belongs to another PBF")
        borders[city] = shape(boundary["geometry"])
        if borders[city].is_empty or not borders[city].is_valid:
            raise ValueError("Native city boundary is invalid")
        boundary_proofs[city] = {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(),
                                "native_id": boundary["id"]}
    target = out / region
    if (target / "receipt.json").is_file():
        old = json.loads((target / "receipt.json").read_text())
        if (old["policy_sha256"] == digest(policy) and old["extractor_sha256"] == code_sha
                and old["source_pbf_sha256"] == source["sha256"] and old["boundary_proofs"] == boundary_proofs):
            return old
        raise ValueError("Existing coverage output changed inputs; preserve it and use a fresh out directory")
    if pbf.stat().st_size != source["size_bytes"] or file_sha(pbf) != source["sha256"]:
        raise ValueError("Local PBF differs from checked input; no download is performed")
    before = pbf.stat()
    scanner = RegionCore(policy, borders)
    started = time.monotonic()
    scanner.apply_file(str(pbf), locations=True, idx="sparse_mem_array", filters=[osmium.filter.KeyFilter(*FILTER_KEYS)])
    after = pbf.stat()
    if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
        raise ValueError("Native source changed during eligibility census")
    target.mkdir(parents=True, exist_ok=True)
    city_results = {}
    for city in cities:
        features, clipping = native_display_features(city, scanner.features[city], borders[city])
        path = target / f"{city}-core13-native.json"
        payload = {"type": "FeatureCollection", "features": features}
        path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        city_results[city] = {"unique_native_object_count": len(features),
                              "literal_category_counts": dict(sorted(Counter(f["properties"]["kind"] for f in features).items())),
                              "native_geometry_gaps": scanner.gaps[city], "clipping": clipping,
                              "core13_native_path": str(path.resolve()), "core13_native_sha256": file_sha(path),
                              "supported_native_eligibility_census_complete": True,
                              "real_world_facility_completeness_claimed": False}
    receipt = {"policy_version": VERSION, "policy_sha256": digest(policy), "extractor_sha256": code_sha,
               "region": region, "source_pbf_path": str(pbf.resolve()), "source_pbf_sha256": source["sha256"],
               "source_metadata_path": str(source_file.resolve()), "source_metadata_sha256": file_sha(source_file),
               "source_timestamp": source.get("pbf_timestamp"), "boundary_proofs": boundary_proofs,
               "cities": city_results, "elapsed_seconds": time.monotonic() - started,
               "extraction_invocations_for_region": 1, "osmium_native_read_passes": 2,
               "region_eligible_relations_without_native_area": sorted(scanner.region_relations_without_area),
               "region_eligible_objects_without_native_geometry": scanner.region_objects_without_geometry,
               "unsupported_relations_not_assigned_to_city_by_name_or_bbox": True,
               "police_semantics_geometry_links_counts_modified": False, "source_downloaded": False,
               "publication_ready": False}
    (target / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--regions", nargs="+")
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text())
    regions = sorted({POI_CITY_SPECS[city].region for city in policy["cities"]})
    for region in args.regions or regions:
        cities = [city for city in policy["cities"] if POI_CITY_SPECS[city].region == region]
        print(json.dumps({"region": region, "phase": "native_core13_eligibility", "cities": cities}), flush=True)
        receipt = extract_region(region=region, cities=cities, project_root=args.project_root,
                                 out=args.out, policy=policy)
        print(json.dumps({"region": region, "phase": "complete", "seconds": receipt["elapsed_seconds"],
                          "cities": {c: v["unique_native_object_count"] for c, v in receipt["cities"].items()}}), flush=True)


if __name__ == "__main__":
    main()
