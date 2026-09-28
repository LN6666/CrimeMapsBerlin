"""Local-only OSM POI inputs and products for the selected German cities.

The module deliberately stops before map publication.  It downloads checked
Geofabrik extracts into ignored runtime storage, selects one plausible OSM
municipal boundary, and builds a browser transport contract that can later be
used by an independently approved city publication.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import osmium
from shapely.geometry import GeometryCollection, MultiPolygon, Point, Polygon, mapping, shape
from shapely.ops import transform, unary_union
from shapely.prepared import prep

from .payload import compact
from .spatial import classify_poi, metric_transforms, pois_from_osm
from .tiles import DX, DY, tiles

PIPELINE_VERSION = 2
SOURCE_LICENSE = "ODbL-1.0"
SOURCE_ATTRIBUTION = "© OpenStreetMap contributors / Geofabrik"
LOCAL_STATUS = "local_poi_only_unpublished"
DEFAULT_RUNTIME_RELATIVE = Path(".runtime/safety/poi-cities")
_MD5_RE = re.compile(r"^([0-9a-fA-F]{32})(?:\s|$)")


@dataclass(frozen=True)
class RegionSpec:
    slug: str
    pbf_url: str
    source_page: str


@dataclass(frozen=True)
class PoiCitySpec:
    slug: str
    name: str
    region: str
    epsg: int
    min_area_km2: float
    max_area_km2: float


_GEOFABRIK = "https://download.geofabrik.de/europe/germany"
REGION_SPECS = {
    "berlin": RegionSpec("berlin", f"{_GEOFABRIK}/berlin-latest.osm.pbf", f"{_GEOFABRIK}/berlin.html"),
    "hamburg": RegionSpec(
        "hamburg", f"{_GEOFABRIK}/hamburg-latest.osm.pbf", f"{_GEOFABRIK}/hamburg.html"
    ),
    "oberbayern": RegionSpec(
        "oberbayern",
        f"{_GEOFABRIK}/bayern/oberbayern-latest.osm.pbf",
        f"{_GEOFABRIK}/bayern/oberbayern.html",
    ),
    "koeln-regbez": RegionSpec(
        "koeln-regbez",
        f"{_GEOFABRIK}/nordrhein-westfalen/koeln-regbez-latest.osm.pbf",
        f"{_GEOFABRIK}/nordrhein-westfalen/koeln-regbez.html",
    ),
    "hessen": RegionSpec("hessen", f"{_GEOFABRIK}/hessen-latest.osm.pbf", f"{_GEOFABRIK}/hessen.html"),
    "duesseldorf-regbez": RegionSpec(
        "duesseldorf-regbez",
        f"{_GEOFABRIK}/nordrhein-westfalen/duesseldorf-regbez-latest.osm.pbf",
        f"{_GEOFABRIK}/nordrhein-westfalen/duesseldorf-regbez.html",
    ),
    "stuttgart-regbez": RegionSpec(
        "stuttgart-regbez",
        f"{_GEOFABRIK}/baden-wuerttemberg/stuttgart-regbez-latest.osm.pbf",
        f"{_GEOFABRIK}/baden-wuerttemberg/stuttgart-regbez.html",
    ),
    "sachsen": RegionSpec(
        "sachsen", f"{_GEOFABRIK}/sachsen-latest.osm.pbf", f"{_GEOFABRIK}/sachsen.html"
    ),
    "arnsberg-regbez": RegionSpec(
        "arnsberg-regbez",
        f"{_GEOFABRIK}/nordrhein-westfalen/arnsberg-regbez-latest.osm.pbf",
        f"{_GEOFABRIK}/nordrhein-westfalen/arnsberg-regbez.html",
    ),
    "bremen": RegionSpec("bremen", f"{_GEOFABRIK}/bremen-latest.osm.pbf", f"{_GEOFABRIK}/bremen.html"),
    "niedersachsen": RegionSpec(
        "niedersachsen",
        f"{_GEOFABRIK}/niedersachsen-latest.osm.pbf",
        f"{_GEOFABRIK}/niedersachsen.html",
    ),
    "mittelfranken": RegionSpec(
        "mittelfranken",
        f"{_GEOFABRIK}/bayern/mittelfranken-latest.osm.pbf",
        f"{_GEOFABRIK}/bayern/mittelfranken.html",
    ),
}

POI_CITY_SPECS = {
    spec.slug: spec
    for spec in (
        PoiCitySpec("berlin", "Berlin", "berlin", 25833, 800, 1000),
        PoiCitySpec("hamburg", "Hamburg", "hamburg", 25832, 900, 1100),
        PoiCitySpec("munich", "München", "oberbayern", 25832, 260, 360),
        PoiCitySpec("cologne", "Köln", "koeln-regbez", 25832, 350, 470),
        PoiCitySpec("frankfurt", "Frankfurt am Main", "hessen", 25832, 210, 300),
        PoiCitySpec("dusseldorf", "Düsseldorf", "duesseldorf-regbez", 25832, 180, 260),
        PoiCitySpec("stuttgart", "Stuttgart", "stuttgart-regbez", 25832, 175, 245),
        PoiCitySpec("leipzig", "Leipzig", "sachsen", 25833, 250, 350),
        PoiCitySpec("dortmund", "Dortmund", "arnsberg-regbez", 25832, 240, 325),
        PoiCitySpec("bremen", "Bremen", "bremen", 25832, 280, 360),
        PoiCitySpec("essen", "Essen", "duesseldorf-regbez", 25832, 180, 250),
        PoiCitySpec("dresden", "Dresden", "sachsen", 25833, 270, 380),
        PoiCitySpec("hannover", "Hannover", "niedersachsen", 25832, 170, 240),
        PoiCitySpec("nuremberg", "Nürnberg", "mittelfranken", 25832, 160, 225),
    )
}


def selected_cities(city: str) -> tuple[str, ...]:
    if city == "all":
        return tuple(POI_CITY_SPECS)
    if city not in POI_CITY_SPECS:
        raise ValueError(f"Unsupported POI city: {city}")
    return (city,)


def runtime_root(project_root: Path) -> Path:
    return project_root / DEFAULT_RUNTIME_RELATIVE


def file_digests(path: Path) -> tuple[str, str]:
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            md5.update(block)
            sha256.update(block)
    return md5.hexdigest(), sha256.hexdigest()


def read_pbf_timestamp(path: Path) -> str | None:
    reader = osmium.io.Reader(str(path))
    try:
        return reader.header().get("osmosis_replication_timestamp") or reader.header().get("timestamp")
    finally:
        reader.close()


def _parse_published_md5(body: str) -> str:
    match = _MD5_RE.match(body.strip())
    if not match:
        raise ValueError("Invalid Geofabrik MD5 response")
    return match.group(1).lower()


def _manifest_path(pbf: Path) -> Path:
    return pbf.with_suffix(".source.json")


def _resolve_manifest_input(
    region: str, *, root: Path, project_root: Path
) -> tuple[Path, Path] | None:
    pbf = root / "extracts" / f"{region}.osm.pbf"
    manifest = _manifest_path(pbf)
    if pbf.is_file() and manifest.is_file():
        return pbf, manifest

    # The first local audit reused previously checked Berlin/Hamburg inputs.
    # Its manifest records that path so the tracked pipeline can validate the
    # existing evidence without copying another large source file.
    external_manifest = root / "extracts" / f"{region}.source.json"
    if not external_manifest.is_file():
        return None
    metadata = json.loads(external_manifest.read_text())
    relative = metadata.get("external_local_path")
    if not relative:
        return None
    external_pbf = project_root / relative
    if not external_pbf.is_file():
        raise FileNotFoundError(f"Missing external checked PBF recorded by {external_manifest}")
    return external_pbf, external_manifest


def verify_source_manifest(pbf: Path, manifest: Path) -> dict:
    metadata = json.loads(manifest.read_text())
    required = {
        "url",
        "source_page",
        "pbf_timestamp",
        "size_bytes",
        "published_md5",
        "sha256",
        "license",
        "attribution",
    }
    missing = sorted(required - metadata.keys())
    if missing:
        raise ValueError(f"Incomplete OSM source manifest {manifest}: {', '.join(missing)}")
    if metadata["license"] != SOURCE_LICENSE or metadata["attribution"] != SOURCE_ATTRIBUTION:
        raise ValueError(f"Unexpected OSM licence or attribution in {manifest}")
    if pbf.stat().st_size != metadata["size_bytes"]:
        raise ValueError(f"OSM source size differs from manifest: {pbf}")
    actual_md5, actual_sha256 = file_digests(pbf)
    if actual_md5 != metadata["published_md5"]:
        raise ValueError(f"OSM source differs from published MD5: {pbf}")
    if actual_sha256 != metadata["sha256"]:
        raise ValueError(f"OSM source differs from recorded SHA-256: {pbf}")
    return metadata


def load_verified_source(city: str, *, root: Path, project_root: Path) -> tuple[Path, dict]:
    spec = POI_CITY_SPECS[city]
    resolved = _resolve_manifest_input(spec.region, root=root, project_root=project_root)
    if resolved is None:
        raise FileNotFoundError(
            f"Missing checked Geofabrik input for {city}; run scripts/safety/build_pois.py fetch --city {city}"
        )
    pbf, manifest = resolved
    metadata = verify_source_manifest(pbf, manifest)
    if metadata.get("region") not in {None, spec.region}:
        raise ValueError(f"OSM source region differs from city contract: {city}")
    return pbf, metadata


def _download_once(client: httpx.Client, url: str, part: Path, expected_md5: str) -> str | None:
    part_metadata = part.with_suffix(part.suffix + ".json")
    expected_part = {"url": url, "published_md5": expected_md5}
    if part.exists():
        previous = json.loads(part_metadata.read_text()) if part_metadata.is_file() else None
        if previous != expected_part:
            part.unlink()
            part_metadata.unlink(missing_ok=True)
    if not part.exists():
        part.parent.mkdir(parents=True, exist_ok=True)
        part_metadata.write_text(json.dumps(expected_part, sort_keys=True))

    offset = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    with client.stream("GET", url, headers=headers) as response:
        if response.status_code in {429, 500, 502, 503, 504}:
            raise httpx.HTTPStatusError("retryable Geofabrik response", request=response.request, response=response)
        response.raise_for_status()
        if offset and response.status_code != 206:
            offset = 0
        if offset:
            content_range = response.headers.get("content-range", "")
            if not content_range.startswith(f"bytes {offset}-"):
                raise ValueError(f"Download resume range mismatch: {content_range}")
        with part.open("ab" if offset else "wb") as target:
            for block in response.iter_bytes(chunk_size=2 * 1024 * 1024):
                target.write(block)
        return response.headers.get("last-modified")


def download_region(
    region: RegionSpec,
    *,
    root: Path,
    project_root: Path,
    client: httpx.Client,
    refresh: bool = False,
    attempts: int = 3,
    retry_delay: Callable[[int], None] = lambda attempt: time.sleep(5 * attempt),
    timestamp_reader: Callable[[Path], str | None] = read_pbf_timestamp,
) -> tuple[Path, dict]:
    existing = _resolve_manifest_input(region.slug, root=root, project_root=project_root)
    if existing is not None and not refresh:
        pbf, manifest = existing
        return pbf, verify_source_manifest(pbf, manifest)

    checksum = client.get(region.pbf_url + ".md5")
    checksum.raise_for_status()
    expected_md5 = _parse_published_md5(checksum.text)
    if existing is not None:
        pbf, manifest = existing
        try:
            metadata = verify_source_manifest(pbf, manifest)
        except (OSError, ValueError, json.JSONDecodeError):
            metadata = None
        if metadata and metadata["published_md5"] == expected_md5:
            return pbf, metadata

    destination = root / "extracts" / f"{region.slug}.osm.pbf"
    part = destination.with_suffix(destination.suffix + ".part")
    last_modified = None
    for attempt in range(1, attempts + 1):
        try:
            last_modified = _download_once(client, region.pbf_url, part, expected_md5)
            break
        except (httpx.HTTPError, httpx.StreamError):
            if attempt == attempts:
                raise
            retry_delay(attempt)

    actual_md5, sha256 = file_digests(part)
    if actual_md5 != expected_md5:
        part.unlink(missing_ok=True)
        part.with_suffix(part.suffix + ".json").unlink(missing_ok=True)
        raise ValueError(f"{region.slug}: downloaded PBF differs from published MD5")
    destination.parent.mkdir(parents=True, exist_ok=True)
    part.replace(destination)
    part.with_suffix(part.suffix + ".json").unlink(missing_ok=True)
    timestamp = timestamp_reader(destination)
    if not timestamp:
        destination.unlink(missing_ok=True)
        raise ValueError(f"{region.slug}: PBF snapshot timestamp missing")
    metadata = {
        "region": region.slug,
        "url": region.pbf_url,
        "source_page": region.source_page,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "file_last_modified": last_modified,
        "pbf_timestamp": timestamp,
        "size_bytes": destination.stat().st_size,
        "published_md5": expected_md5,
        "sha256": sha256,
        "license": SOURCE_LICENSE,
        "attribution": SOURCE_ATTRIBUTION,
    }
    manifest = _manifest_path(destination)
    manifest.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    return destination, metadata


def fetch_city_sources(
    cities: Iterable[str],
    *,
    root: Path,
    project_root: Path,
    refresh: bool = False,
    pause_seconds: float = 2,
) -> dict[str, dict]:
    regions = list(dict.fromkeys(POI_CITY_SPECS[city].region for city in cities))
    results = {}
    timeout = httpx.Timeout(90, connect=20)
    headers = {"User-Agent": "CrimeMapsBerlin-POI/1.0 (Geofabrik public extracts)"}
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        for index, region_slug in enumerate(regions):
            _, results[region_slug] = download_region(
                REGION_SPECS[region_slug],
                root=root,
                project_root=project_root,
                client=client,
                refresh=refresh,
            )
            if pause_seconds and index + 1 < len(regions):
                time.sleep(pause_seconds)
    return results


class BoundaryScanner(osmium.SimpleHandler):
    def __init__(self, spec: PoiCitySpec):
        super().__init__()
        self.spec = spec
        self.factory = osmium.geom.GeoJSONFactory()
        self.candidates: list[dict] = []
        self.to_metric, _ = metric_transforms(spec.epsg)

    def area(self, area):
        tags = dict(area.tags)
        if area.from_way() or tags.get("boundary") != "administrative" or tags.get("name") != self.spec.name:
            return
        if tags.get("admin_level") not in {"4", "6", "8"}:
            return
        try:
            geometry = shape(json.loads(self.factory.create_multipolygon(area)))
        except (RuntimeError, ValueError):
            return
        if geometry.is_empty or not geometry.is_valid:
            return
        area_km2 = transform(self.to_metric, geometry).area / 1_000_000
        self.candidates.append(
            {
                "id": f"osm/relation/{area.orig_id()}",
                "name": self.spec.name,
                "admin_level": tags["admin_level"],
                "area_km2": round(area_km2, 3),
                "within_expected_area": self.spec.min_area_km2 <= area_km2 <= self.spec.max_area_km2,
                "geometry": mapping(geometry),
                "source_tags": {
                    key: tags[key]
                    for key in ("wikidata", "de:amtlicher_gemeindeschluessel")
                    if key in tags
                },
            }
        )


def select_boundary(spec: PoiCitySpec, candidates: Iterable[dict]) -> dict:
    plausible = [candidate for candidate in candidates if candidate.get("within_expected_area")]
    if len(plausible) != 1:
        raise ValueError(
            f"{spec.slug}: expected one plausible OSM administrative relation; got {len(plausible)}"
        )
    selected = plausible[0]
    geometry = shape(selected["geometry"])
    if selected.get("name") != spec.name or geometry.is_empty or not geometry.is_valid:
        raise ValueError(f"{spec.slug}: invalid selected OSM administrative relation")
    return selected


def boundary_for_city(city: str, pbf: Path, source_metadata: dict, *, root: Path) -> tuple[dict, object]:
    spec = POI_CITY_SPECS[city]
    checkpoint = root / "checkpoints" / city / "boundary.geojson"
    if checkpoint.is_file():
        saved = json.loads(checkpoint.read_text())
        if saved.get("source_pbf_sha256") == source_metadata["sha256"]:
            return saved, shape(saved["geometry"])

    scanner = BoundaryScanner(spec)
    scanner.apply_file(str(pbf), locations=True)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    (checkpoint.parent / "boundary-candidates.json").write_text(
        json.dumps(
            [{key: value for key, value in row.items() if key != "geometry"} for row in scanner.candidates],
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    selected = dict(select_boundary(spec, scanner.candidates))
    selected["source_pbf_sha256"] = source_metadata["sha256"]
    checkpoint.write_text(json.dumps(selected, ensure_ascii=False, separators=(",", ":")))
    return selected, shape(selected["geometry"])


class Places(osmium.SimpleHandler):
    def __init__(self, border):
        super().__init__()
        self.border = border
        self.prepared = prep(border)
        self.bounds = border.bounds
        self.factory = osmium.geom.GeoJSONFactory()
        self.elements: list[dict] = []
        self.rejected: Counter = Counter()

    def _intersects(self, geometry) -> bool:
        if geometry.is_empty or not geometry.is_valid or not geometry.intersects(self.border):
            self.rejected["invalid_or_outside_city"] += 1
            return False
        return True

    def node(self, node):
        tags = dict(node.tags)
        if not classify_poi(tags) or not node.location.valid():
            return
        lon, lat = node.location.lon, node.location.lat
        xmin, ymin, xmax, ymax = self.bounds
        if not (xmin <= lon <= xmax and ymin <= lat <= ymax and self.prepared.covers(Point(lon, lat))):
            self.rejected["outside_city"] += 1
            return
        self.elements.append({"type": "node", "id": node.id, "lon": lon, "lat": lat, "tags": tags})

    def way(self, way):
        tags = dict(way.tags)
        if not classify_poi(tags):
            return
        try:
            coordinates = [(node.lon, node.lat) for node in way.nodes]
        except osmium.InvalidLocationError:
            self.rejected["way_missing_node"] += 1
            return
        if len(coordinates) < 4 or coordinates[0] != coordinates[-1]:
            self.rejected["way_without_footprint"] += 1
            return
        geometry = Polygon(coordinates)
        if not self._intersects(geometry):
            return
        self.elements.append(
            {
                "type": "way",
                "id": way.id,
                "tags": tags,
                "geometry": [{"lon": lon, "lat": lat} for lon, lat in coordinates],
            }
        )

    def area(self, area):
        if area.from_way():
            return
        tags = dict(area.tags)
        if not classify_poi(tags):
            return
        try:
            geometry = shape(json.loads(self.factory.create_multipolygon(area)))
        except (RuntimeError, ValueError):
            self.rejected["relation_without_footprint"] += 1
            return
        if not self._intersects(geometry):
            return
        self.elements.append(
            {
                "type": "relation",
                "id": area.orig_id(),
                "tags": tags,
                "geojson_geometry": mapping(geometry),
            }
        )


def _polygons_only(geometry):
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    if isinstance(geometry, GeometryCollection):
        polygons = [
            part
            for part in geometry.geoms
            if isinstance(part, (Polygon, MultiPolygon)) and not part.is_empty
        ]
        return unary_union(polygons) if polygons else None
    return None


def geometry_covered_by(border, geometry) -> bool:
    if border.covers(geometry):
        return True
    if geometry.geom_type == "Point":
        return border.distance(geometry) < 1e-10
    return geometry.difference(border).area <= max(1e-12, geometry.area * 1e-8)


def clip_features(pois: dict, border) -> tuple[list[dict], dict]:
    retained = []
    notes: Counter = Counter()
    for feature in pois["features"]:
        properties = feature["properties"]
        actual = shape(feature["location_geometry"])
        display = shape(feature["geometry"])
        actual_type = actual.geom_type
        actual_clipped = actual.intersection(border)
        display_clipped = display.intersection(border)
        if actual.geom_type != "Point":
            actual_clipped = _polygons_only(actual_clipped)
        if display.geom_type != "Point":
            display_clipped = _polygons_only(display_clipped)
        if (
            actual_clipped is None
            or display_clipped is None
            or actual_clipped.is_empty
            or display_clipped.is_empty
        ):
            notes["empty_after_clipping"] += 1
            continue
        properties["geometry_source_id"] = properties["id"]
        properties["geometry_source_type"] = actual_type
        properties["boundary_clipped"] = not actual.equals(actual_clipped) or not display.equals(display_clipped)
        if properties["boundary_clipped"]:
            notes["boundary_clipped"] += 1
        if not border.covers(Point(properties["center"])):
            center = actual_clipped.representative_point()
            properties["center"] = [center.x, center.y]
            notes["center_replaced_by_clipped_geometry"] += 1
        properties["aliases"] = sorted(
            {alias.strip() for alias in properties.get("aliases", []) if alias.strip()}
        )
        feature["location_geometry"] = mapping(actual_clipped)
        feature["geometry"] = mapping(display_clipped)
        retained.append(feature)
    retained.sort(key=lambda feature: feature["properties"]["id"])
    return retained, dict(notes)


def _write_json(path: Path, value, *, public: bool = False, pretty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if public:
        value = compact(value)
    separators = None if pretty else (",", ":")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2 if pretty else None, separators=separators))


def write_city_product(
    city: str,
    *,
    output: Path,
    elements: list[dict],
    border,
    boundary_metadata: dict,
    source_metadata: dict,
    catalog_path: Path,
    preselection_rejections: dict | None = None,
    dedup_rejections: dict | None = None,
) -> dict:
    spec = POI_CITY_SPECS[city]
    to_metric, to_wgs = metric_transforms(spec.epsg)
    pois, derived_dedup = pois_from_osm({"elements": elements}, to_metric=to_metric, to_wgs=to_wgs)
    features, clipping = clip_features(pois, border)
    dedup = dict(dedup_rejections or derived_dedup)
    palette = json.loads(catalog_path.read_text())["poi_types"]
    ids = [feature["properties"]["id"] for feature in features]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{city}: duplicate OSM object IDs")
    missing_colors = sorted({feature["properties"]["kind"] for feature in features} - palette.keys())
    if missing_colors:
        raise ValueError(f"{city}: missing POI category colors: {missing_colors}")
    escaped = [
        feature["properties"]["id"]
        for feature in features
        if not geometry_covered_by(border, shape(feature["geometry"]))
        or not geometry_covered_by(border, shape(feature["location_geometry"]))
    ]
    if escaped:
        raise ValueError(f"{city}: retained geometry escaped city boundary: {escaped[:5]}")

    output.mkdir(parents=True, exist_ok=True)
    _write_json(output / "poi-index.json", {"type": "FeatureCollection", "features": features})
    _write_json(output / "boundary.geojson", boundary_metadata)
    public_features = [compact(feature) for feature in features]
    tile_index = []
    for kind in sorted({feature["properties"]["kind"] for feature in features}):
        category_features = [
            feature for feature in public_features if feature["properties"]["kind"] == kind
        ]
        for key, content in sorted(tiles(category_features).items()):
            tile_index.append(f"{kind}/{key}")
            _write_json(output / "pois" / kind / f"{key}.json", content, public=True)
    search = [
        {
            "id": feature["properties"]["id"],
            "name": feature["properties"]["name"],
            "aliases": feature["properties"]["aliases"],
            "kind": feature["properties"]["kind"],
            "center": feature["properties"]["center"],
        }
        for feature in features
        if feature["properties"]["name"] != feature["properties"]["kind"]
    ]
    _write_json(output / "search.json", search, public=True)

    geometry_modes = Counter(feature["properties"]["geometry_mode"] for feature in features)
    categories = Counter(feature["properties"]["kind"] for feature in features)
    station_modes = Counter(
        feature["properties"]["geometry_mode"]
        for feature in features
        if feature["properties"]["kind"] == "station"
    )
    report = {
        "city": city,
        "name": spec.name,
        "built_at": datetime.now(UTC).isoformat(),
        "status": LOCAL_STATUS,
        "boundary": {key: value for key, value in boundary_metadata.items() if key != "geometry"},
        "source": source_metadata,
        "crs": {"geometry": "EPSG:4326", "metric": f"EPSG:{spec.epsg}"},
        "poi_count": len(features),
        "categories": dict(sorted(categories.items())),
        "geometry_modes": dict(sorted(geometry_modes.items())),
        "station_geometry_modes": dict(sorted(station_modes.items())),
        "preselection_rejections": dict(sorted((preselection_rejections or {}).items())),
        "dedup_rejections": dict(sorted(dedup.items())),
        "clipping": dict(sorted(clipping.items())),
        "tile_count": len(tile_index),
        "search_count": len(search),
        "category_colors": {key: palette[key] for key in sorted(categories)},
        "geometry_check": "all retained display and location geometry covered by OSM administrative relation",
        "station_check": "OSM area if tagged station area exists; otherwise point with footprint_missing",
        "publication_ready": False,
    }
    contract = {
        "schema_version": 2,
        "pipeline_version": PIPELINE_VERSION,
        "city": city,
        "status": LOCAL_STATUS,
        "tile_size": [DX, DY],
        "tile_index": {"pois": tile_index},
        "catalog_sha256": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
        "source_pbf_sha256": source_metadata["sha256"],
        "boundary_source_id": boundary_metadata["id"],
        "epsg": spec.epsg,
        "poi_count": len(features),
        "files": {
            "tiles": "pois/{category}/{x}_{y}.json",
            "search": "search.json",
            "index": "poi-index.json",
        },
        "monthly_events": "separate reviewed and owner-approved publication step",
        "publication_ready": False,
    }
    _write_json(output / "report.json", report, public=True)
    _write_json(output / "poi-contract.json", contract, public=True)
    return report


def _replace_city_output(staging: Path, target: Path) -> None:
    backup = target.parent / f".{target.name}.previous"
    shutil.rmtree(backup, ignore_errors=True)
    if target.exists():
        target.replace(backup)
    try:
        staging.replace(target)
    except Exception:
        if backup.exists() and not target.exists():
            backup.replace(target)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def build_city(city: str, *, root: Path, project_root: Path, catalog_path: Path) -> dict:
    pbf, source_metadata = load_verified_source(city, root=root, project_root=project_root)
    boundary_metadata, border = boundary_for_city(city, pbf, source_metadata, root=root)
    checkpoint = root / "checkpoints" / city / "poi-stage.json"
    stage = json.loads(checkpoint.read_text()) if checkpoint.is_file() else None
    checkpoint_key = (
        source_metadata["sha256"],
        boundary_metadata["id"],
        PIPELINE_VERSION,
    )
    if stage and (
        stage.get("source_pbf_sha256"),
        stage.get("boundary_source_id"),
        stage.get("pipeline_version"),
    ) == checkpoint_key:
        elements = stage["elements"]
        preselection_rejections = stage["preselection_rejections"]
    else:
        handler = Places(border)
        handler.apply_file(str(pbf), locations=True)
        elements = handler.elements
        preselection_rejections = dict(handler.rejected)
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        _write_json(
            checkpoint,
            {
                "pipeline_version": PIPELINE_VERSION,
                "source_pbf_sha256": source_metadata["sha256"],
                "boundary_source_id": boundary_metadata["id"],
                "elements": elements,
                "preselection_rejections": preselection_rejections,
            },
        )

    staging = root / ".building" / city
    shutil.rmtree(staging, ignore_errors=True)
    report = write_city_product(
        city,
        output=staging,
        elements=elements,
        border=border,
        boundary_metadata=boundary_metadata,
        source_metadata=source_metadata,
        catalog_path=catalog_path,
        preselection_rejections=preselection_rejections,
    )
    target = root / "cities" / city
    target.parent.mkdir(parents=True, exist_ok=True)
    _replace_city_output(staging, target)
    return report
