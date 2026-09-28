import hashlib
import json
from pathlib import Path

import httpx
import pytest
from shapely.geometry import Point, box, mapping, shape
from shapely.ops import transform

from crimemapsberlin.poi_cities import (
    POI_CITY_SPECS,
    REGION_SPECS,
    RegionSpec,
    download_region,
    file_digests,
    select_boundary,
    selected_cities,
    verify_source_manifest,
    write_city_product,
)
from crimemapsberlin.poi_validation import PoiValidationError, validate_city_product
from crimemapsberlin.spatial import metric_transforms

PROJECT = Path(__file__).resolve().parents[2]
CATALOG = PROJECT / "data/safety/europe_sources.json"


def source_fixture(root, payload=b"synthetic checked source"):
    pbf = root / "extracts/berlin.osm.pbf"
    pbf.parent.mkdir(parents=True)
    pbf.write_bytes(payload)
    md5, sha256 = file_digests(pbf)
    metadata = {
        "region": "berlin",
        "url": "https://download.geofabrik.de/europe/germany/berlin-test.osm.pbf",
        "source_page": "https://download.geofabrik.de/europe/germany/berlin.html",
        "retrieved_at": "2026-09-29T00:00:00+00:00",
        "file_last_modified": "Tue, 29 Sep 2026 00:00:00 GMT",
        "pbf_timestamp": "2026-09-28T20:21:22Z",
        "size_bytes": pbf.stat().st_size,
        "published_md5": md5,
        "sha256": sha256,
        "license": "ODbL-1.0",
        "attribution": "© OpenStreetMap contributors / Geofabrik",
    }
    manifest = pbf.with_suffix(".source.json")
    manifest.write_text(json.dumps(metadata))
    return pbf, manifest, metadata


def test_registry_has_selected_fourteen_cities_and_twelve_bounded_extracts():
    assert selected_cities("all") == (
        "berlin",
        "hamburg",
        "munich",
        "cologne",
        "frankfurt",
        "dusseldorf",
        "stuttgart",
        "leipzig",
        "dortmund",
        "bremen",
        "essen",
        "dresden",
        "hannover",
        "nuremberg",
    )
    assert {spec.region for spec in POI_CITY_SPECS.values()} == set(REGION_SPECS)
    assert POI_CITY_SPECS["berlin"].epsg == 25833
    assert POI_CITY_SPECS["hamburg"].epsg == 25832


def test_resumable_download_records_both_hashes_and_reuses_checked_input(tmp_path):
    payload = b"a complete synthetic Geofabrik input"
    expected_md5 = hashlib.md5(payload).hexdigest()
    region = RegionSpec("test-region", "https://download.test/region.osm.pbf", "https://download.test/")
    part = tmp_path / "extracts/test-region.osm.pbf.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(payload[:10])
    part.with_suffix(part.suffix + ".json").write_text(
        json.dumps({"url": region.pbf_url, "published_md5": expected_md5}, sort_keys=True)
    )
    ranges = []

    def handler(request):
        if request.url.path.endswith(".md5"):
            return httpx.Response(200, text=f"{expected_md5}  region.osm.pbf\n")
        ranges.append(request.headers.get("range"))
        return httpx.Response(
            206,
            content=payload[10:],
            headers={
                "content-range": f"bytes 10-{len(payload) - 1}/{len(payload)}",
                "last-modified": "Tue, 29 Sep 2026 00:00:00 GMT",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        pbf, metadata = download_region(
            region,
            root=tmp_path,
            project_root=tmp_path,
            client=client,
            timestamp_reader=lambda _: "2026-09-28T20:21:22Z",
        )
    assert pbf.read_bytes() == payload
    assert ranges == ["bytes=10-"]
    assert metadata["published_md5"] == expected_md5
    assert metadata["sha256"] == hashlib.sha256(payload).hexdigest()

    def unexpected_request(_request):
        raise AssertionError("a valid local checkpoint must not make another request")

    with httpx.Client(transport=httpx.MockTransport(unexpected_request)) as client:
        reused, reused_metadata = download_region(
            region,
            root=tmp_path,
            project_root=tmp_path,
            client=client,
        )
    assert reused == pbf
    assert reused_metadata == metadata

    pbf.write_bytes(payload + b"tampered")
    with pytest.raises(ValueError, match="size differs"):
        verify_source_manifest(pbf, pbf.with_suffix(".source.json"))


def test_boundary_selection_fails_closed_on_absence_or_ambiguity():
    spec = POI_CITY_SPECS["berlin"]
    plausible = {
        "id": "osm/relation/1",
        "name": "Berlin",
        "admin_level": "4",
        "area_km2": 890,
        "within_expected_area": True,
        "geometry": mapping(box(13.0, 52.0, 14.0, 53.0)),
    }
    rejected = dict(plausible, id="osm/relation/2", area_km2=200, within_expected_area=False)
    assert select_boundary(spec, [rejected, plausible])["id"] == "osm/relation/1"
    with pytest.raises(ValueError, match="got 0"):
        select_boundary(spec, [rejected])
    with pytest.raises(ValueError, match="got 2"):
        select_boundary(spec, [plausible, dict(plausible, id="osm/relation/3")])


def test_build_and_independent_readback_preserve_geometry_contract(tmp_path):
    _pbf, _manifest, source = source_fixture(tmp_path)
    border = box(13.39, 52.49, 13.41, 52.51)
    boundary = {
        "id": "osm/relation/62422",
        "name": "Berlin",
        "admin_level": "4",
        "area_km2": 890.0,
        "within_expected_area": True,
        "geometry": mapping(border),
        "source_tags": {"wikidata": "Q64"},
        "source_pbf_sha256": source["sha256"],
    }
    elements = [
        {
            "type": "node",
            "id": 1,
            "lon": 13.4,
            "lat": 52.5,
            "tags": {"amenity": "bar", "name": "Synthetic Bar", "alt_name": "Bar One;Bar Eins"},
        },
        {
            "type": "node",
            "id": 2,
            "lon": 13.402,
            "lat": 52.502,
            "tags": {"railway": "station", "name": "Point Station"},
        },
        {
            "type": "way",
            "id": 3,
            "tags": {"railway": "station", "name": "Area Station"},
            "geometry": [
                {"lon": 13.404, "lat": 52.504},
                {"lon": 13.405, "lat": 52.504},
                {"lon": 13.405, "lat": 52.505},
                {"lon": 13.404, "lat": 52.505},
                {"lon": 13.404, "lat": 52.504},
            ],
        },
        {
            "type": "node",
            "id": 4,
            "lon": 13.4045,
            "lat": 52.5045,
            "tags": {"railway": "station", "name": "Area Station"},
        },
        {
            "type": "way",
            "id": 5,
            "tags": {"leisure": "park", "name": "Boundary Park"},
            "geometry": [
                {"lon": 13.409, "lat": 52.499},
                {"lon": 13.411, "lat": 52.499},
                {"lon": 13.411, "lat": 52.501},
                {"lon": 13.409, "lat": 52.501},
                {"lon": 13.409, "lat": 52.499},
            ],
        },
    ]
    city_root = tmp_path / "cities/berlin"
    report = write_city_product(
        "berlin",
        output=city_root,
        elements=elements,
        border=border,
        boundary_metadata=boundary,
        source_metadata=source,
        catalog_path=CATALOG,
    )
    assert report["poi_count"] == 4
    assert report["station_geometry_modes"] == {"footprint_missing": 1, "osm_footprint": 1}
    assert report["clipping"] == {"boundary_clipped": 1}
    assert report["publication_ready"] is False

    validation = validate_city_product(
        "berlin",
        root=tmp_path,
        project_root=tmp_path,
        catalog_path=CATALOG,
        timestamp_reader=lambda _: source["pbf_timestamp"],
    )
    assert validation["passed"] is True
    assert validation["radius_checked"] == 1
    index = json.loads((city_root / "poi-index.json").read_text())["features"]
    by_id = {feature["properties"]["id"]: feature for feature in index}
    assert "osm/node/4" not in by_id
    assert by_id["osm/node/2"]["properties"]["geometry_mode"] == "footprint_missing"
    assert by_id["osm/way/3"]["properties"]["geometry_mode"] == "osm_footprint"
    assert by_id["osm/way/5"]["properties"]["boundary_clipped"] is True
    to_metric, _ = metric_transforms(25833)
    circle = transform(to_metric, shape(by_id["osm/node/1"]["geometry"]))
    center = transform(to_metric, Point(13.4, 52.5))
    assert abs(circle.bounds[2] - center.x - 50) < 0.01

    tile_path = next((city_root / "pois").glob("*/*.json"))
    tile = json.loads(tile_path.read_text())
    tile["features"][0]["location_geometry"] = tile["features"][0]["geometry"]
    tile_path.write_text(json.dumps(tile))
    with pytest.raises(PoiValidationError, match="display-only"):
        validate_city_product(
            "berlin",
            root=tmp_path,
            project_root=tmp_path,
            catalog_path=CATALOG,
            timestamp_reader=lambda _: source["pbf_timestamp"],
        )
