"""Independent read-back validation for local city POI products."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from shapely.geometry import Point, shape
from shapely.ops import transform

from .payload import compact
from .poi_cities import (
    LOCAL_STATUS,
    POI_CITY_SPECS,
    SOURCE_LICENSE,
    geometry_covered_by,
    load_verified_source,
    read_pbf_timestamp,
)
from .spatial import POI_RADIUS_M, metric_transforms
from .tiles import DX, DY

_OSM_ID = re.compile(r"^osm/(node|way|relation)/(\d+)$")


class PoiValidationError(ValueError):
    def __init__(self, validation: dict):
        self.validation = validation
        super().__init__("; ".join(validation["errors"][:10]))


def _expected_tiles(features: list[dict]) -> dict[str, list[str]]:
    expected: dict[str, list[str]] = defaultdict(list)
    for feature in features:
        properties = feature["properties"]
        xmin, ymin, xmax, ymax = shape(feature["geometry"]).bounds
        for x in range(math.floor(xmin / DX), math.floor(xmax / DX) + 1):
            for y in range(math.floor(ymin / DY), math.floor(ymax / DY) + 1):
                expected[f"{properties['kind']}/{x}_{y}"].append(properties["id"])
    return {key: value for key, value in sorted(expected.items())}


def validate_city_product(
    city: str,
    *,
    root: Path,
    project_root: Path,
    catalog_path: Path,
    timestamp_reader: Callable[[Path], str | None] = read_pbf_timestamp,
) -> dict:
    spec = POI_CITY_SPECS[city]
    city_root = root / "cities" / city
    required = {
        name: city_root / filename
        for name, filename in {
            "report": "report.json",
            "contract": "poi-contract.json",
            "boundary": "boundary.geojson",
            "index": "poi-index.json",
            "search": "search.json",
        }.items()
    }
    missing = [name for name, path in required.items() if not path.is_file()]
    if missing:
        validation = {
            "city": city,
            "checked_at": datetime.now(UTC).isoformat(),
            "passed": False,
            "errors": [f"missing product files: {', '.join(missing)}"],
            "publication_ready": False,
        }
        city_root.mkdir(parents=True, exist_ok=True)
        (city_root / "validation.json").write_text(json.dumps(validation, indent=2) + "\n")
        raise PoiValidationError(validation)

    report = json.loads(required["report"].read_text())
    contract = json.loads(required["contract"].read_text())
    boundary_metadata = json.loads(required["boundary"].read_text())
    border = shape(boundary_metadata["geometry"])
    index = json.loads(required["index"].read_text())
    features = index.get("features", [])
    search_rows = json.loads(required["search"].read_text())
    catalog = json.loads(catalog_path.read_text())["poi_types"]
    pbf, source_metadata = load_verified_source(city, root=root, project_root=project_root)
    errors: list[str] = []

    pbf_timestamp = timestamp_reader(pbf)
    if not pbf_timestamp or pbf_timestamp != source_metadata["pbf_timestamp"]:
        errors.append("PBF snapshot timestamp differs from source manifest")
    if source_metadata["license"] != SOURCE_LICENSE:
        errors.append("source licence missing")
    if report.get("status") != LOCAL_STATUS or report.get("publication_ready") is not False:
        errors.append("report does not retain the unpublished local-only status")
    if contract.get("status") != LOCAL_STATUS or contract.get("publication_ready", False) is not False:
        errors.append("POI contract does not retain the unpublished local-only status")
    if contract.get("tile_size") != [DX, DY]:
        errors.append("unexpected browser tile size")
    if contract.get("city") != city or contract.get("epsg") != spec.epsg:
        errors.append("POI contract differs from city registry")
    if contract.get("source_pbf_sha256") != source_metadata["sha256"]:
        errors.append("POI contract differs from checked source")
    if boundary_metadata.get("source_pbf_sha256") != source_metadata["sha256"]:
        errors.append("boundary differs from checked source")
    if contract.get("boundary_source_id") != boundary_metadata.get("id"):
        errors.append("POI contract differs from selected boundary")
    if contract.get("catalog_sha256") != hashlib.sha256(catalog_path.read_bytes()).hexdigest():
        errors.append("POI category catalog changed after build")
    if index.get("type") != "FeatureCollection":
        errors.append("POI index is not a FeatureCollection")

    ids = [feature.get("properties", {}).get("id") for feature in features]
    id_set = set(ids)
    if None in id_set or len(ids) != len(id_set):
        errors.append("POI index has missing or duplicate IDs")
    categories = Counter()
    geometry_modes = Counter()
    station_modes = Counter()
    radius_checked = 0
    to_metric, _ = metric_transforms(spec.epsg)
    canonical_public = {}
    for feature in features:
        properties = feature.get("properties", {})
        poi_id = properties.get("id", "")
        match = _OSM_ID.match(poi_id)
        if not match:
            errors.append(f"invalid stable OSM ID: {poi_id}")
            continue
        if properties.get("source_url") != f"https://www.openstreetmap.org/{match.group(1)}/{match.group(2)}":
            errors.append(f"source URL differs from stable OSM ID: {poi_id}")
        kind = properties.get("kind")
        categories[kind] += 1
        mode = properties.get("geometry_mode")
        geometry_modes[mode] += 1
        if kind == "station":
            station_modes[mode] += 1
        if kind not in catalog:
            errors.append(f"POI category lacks a catalog color: {poi_id}")
        aliases = properties.get("aliases")
        if not isinstance(aliases, list) or aliases != sorted(set(aliases)):
            errors.append(f"aliases are not a sorted unique list: {poi_id}")
        if properties.get("geometry_source_id") != poi_id:
            errors.append(f"geometry source ID differs from POI ID: {poi_id}")
        try:
            display = shape(feature["geometry"])
            actual = shape(feature["location_geometry"])
        except (KeyError, ValueError, TypeError):
            errors.append(f"missing or invalid POI geometry: {poi_id}")
            continue
        if display.is_empty or actual.is_empty or not display.is_valid or not actual.is_valid:
            errors.append(f"empty or invalid POI geometry: {poi_id}")
        if not geometry_covered_by(border, display) or not geometry_covered_by(border, actual):
            errors.append(f"POI geometry escaped selected city boundary: {poi_id}")
        center = Point(properties.get("center", []))
        if center.is_empty or not border.covers(center):
            errors.append(f"POI center escaped selected city boundary: {poi_id}")
        if kind == "station":
            if actual.geom_type == "Point":
                if mode != "footprint_missing" or display.geom_type != "Point" or not display.equals(actual):
                    errors.append(f"station point rule failed: {poi_id}")
            elif mode != "osm_footprint" or display.geom_type not in {"Polygon", "MultiPolygon"}:
                errors.append(f"station footprint rule failed: {poi_id}")
            elif not display.equals(actual):
                errors.append(f"station display footprint differs from source geometry: {poi_id}")
        if mode == "50m_circle" and not properties.get("boundary_clipped"):
            metric_center = transform(to_metric, center)
            metric_display = transform(to_metric, display)
            if metric_display.geom_type != "Polygon":
                errors.append(f"50 m display is not a polygon: {poi_id}")
            else:
                radius_checked += 1
                if any(
                    abs(math.hypot(x - metric_center.x, y - metric_center.y) - POI_RADIUS_M) > 0.01
                    for x, y in metric_display.exterior.coords
                ):
                    errors.append(f"50 m radius differs: {poi_id}")
        canonical_public[poi_id] = compact(feature)

    expected_search = [
        {
            "id": feature["properties"]["id"],
            "name": feature["properties"]["name"],
            "aliases": feature["properties"]["aliases"],
            "kind": feature["properties"]["kind"],
            "center": compact(feature["properties"]["center"]),
        }
        for feature in features
        if feature["properties"]["name"] != feature["properties"]["kind"]
    ]
    if search_rows != expected_search:
        errors.append("search index differs from POI index")

    expected_tiles = _expected_tiles([canonical_public[poi_id] for poi_id in ids if poi_id in canonical_public])
    contract_tiles = contract.get("tile_index", {}).get("pois", [])
    if contract_tiles != sorted(expected_tiles):
        errors.append("tile contract differs from geometry bounds")
    actual_tile_paths = {
        f"{path.parent.name}/{path.stem}" for path in (city_root / "pois").glob("*/*.json")
    }
    if actual_tile_paths != set(expected_tiles):
        errors.append("tile files differ from POI contract")
    seen_ids = set()
    tile_feature_rows = 0
    for key, expected_ids in expected_tiles.items():
        kind, coordinate = key.split("/", 1)
        path = city_root / "pois" / kind / f"{coordinate}.json"
        if not path.is_file():
            continue
        tile = json.loads(path.read_text())
        rows = tile.get("features", []) if tile.get("type") == "FeatureCollection" else []
        row_ids = [row.get("properties", {}).get("id") for row in rows]
        if row_ids != expected_ids:
            errors.append(f"tile membership or ordering differs: {key}")
        for row in rows:
            poi_id = row.get("properties", {}).get("id")
            tile_feature_rows += 1
            if "location_geometry" in row or row != canonical_public.get(poi_id):
                errors.append(f"tile feature differs from display-only index: {key}/{poi_id}")
            if row.get("properties", {}).get("kind") != kind:
                errors.append(f"tile category differs: {key}/{poi_id}")
            seen_ids.add(poi_id)
    if seen_ids != id_set:
        errors.append(f"tile union differs from POI index: missing={len(id_set - seen_ids)}")

    sorted_categories = dict(sorted(categories.items()))
    sorted_modes = dict(sorted(geometry_modes.items()))
    sorted_station_modes = dict(sorted(station_modes.items()))
    if report.get("poi_count") != len(features) or contract.get("poi_count") != len(features):
        errors.append("reported POI count differs from index")
    if report.get("categories") != sorted_categories:
        errors.append("reported category counts differ from index")
    if report.get("geometry_modes") != sorted_modes:
        errors.append("reported geometry modes differ from index")
    if report.get("station_geometry_modes") != sorted_station_modes:
        errors.append("reported station modes differ from index")
    if report.get("tile_count") != len(expected_tiles) or report.get("search_count") != len(expected_search):
        errors.append("reported tile or search count differs from files")
    if report.get("category_colors") != {key: catalog[key] for key in sorted(categories)}:
        errors.append("reported category colors differ from catalog")

    validation = {
        "city": city,
        "checked_at": datetime.now(UTC).isoformat(),
        "passed": not errors,
        "errors": errors,
        "poi_count": len(features),
        "categories": sorted_categories,
        "geometry_modes": sorted_modes,
        "station_geometry_modes": sorted_station_modes,
        "boundary_clipped": sum(bool(feature["properties"].get("boundary_clipped")) for feature in features),
        "boundary_source_id": boundary_metadata.get("id"),
        "pbf_timestamp": pbf_timestamp,
        "source_url": source_metadata["url"],
        "source_sha256": source_metadata["sha256"],
        "source_license": source_metadata["license"],
        "epsg": spec.epsg,
        "tile_count": len(expected_tiles),
        "tile_feature_rows": tile_feature_rows,
        "radius_checked": radius_checked,
        "publication_ready": False,
    }
    (city_root / "validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n"
    )
    if errors:
        raise PoiValidationError(validation)
    return validation
