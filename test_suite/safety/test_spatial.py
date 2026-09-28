import math

from shapely.geometry import Point, shape
from shapely.ops import transform

from crimemapsberlin.geocode import Gazetteer
from crimemapsberlin.spatial import (
    TO_METRIC, associate, cell_for, hexagons, metric_transforms, pois_from_osm,
)
from crimemapsberlin.tiles import tiles


def event(precision="point"):
    return dict(
        id="1",
        coordinates=[13.4, 52.5],
        location_precision=precision,
        poi_mentions=["bar"],
        source_url="https://example.org",
        mention_basis="keyword",
        category="Raub",
    )


def test_hex_metric_geometry_and_count():
    key, polygon = cell_for(13.4, 52.5, 275)
    assert polygon.covers(Point(13.4, 52.5))
    metric = transform(TO_METRIC, polygon)
    assert math.isclose(metric.area, 3 * math.sqrt(3) / 2 * 275**2, rel_tol=1e-7)
    assert hexagons([event(), event("district")], 275)["features"][0]["properties"]["count"] == 1
    assert key == cell_for(13.4, 52.5, 275)[0]


def test_hamburg_geometry_uses_its_own_metric_crs():
    to_metric, to_wgs = metric_transforms(25832)
    _, polygon = cell_for(10.0, 53.55, 275, to_metric=to_metric, to_wgs=to_wgs)
    assert polygon.covers(Point(10.0, 53.55))
    assert math.isclose(
        transform(to_metric, polygon).area,
        3 * math.sqrt(3) / 2 * 275**2,
        rel_tol=1e-7,
    )
    fc, _ = pois_from_osm(
        {"elements": [{"type": "node", "id": 1, "lon": 10.0, "lat": 53.55,
                       "tags": {"amenity": "bar"}}]},
        to_metric=to_metric, to_wgs=to_wgs,
    )
    circle = transform(to_metric, shape(fc["features"][0]["geometry"]))
    assert math.isclose(circle.bounds[2] - to_metric(10.0, 53.55)[0], 50, abs_tol=0.01)


def test_circles_station_geometry_and_type_matching():
    payload = {
        "elements": [
            dict(type="node", id=i, lon=13.4, lat=52.5, tags=tags)
            for i, tags in enumerate([{"amenity": "bar"}, {"amenity": "nightclub"}, {"railway": "station"}])
        ]
    }
    fc, _ = pois_from_osm(payload)
    assert (
        abs(
            transform(TO_METRIC, shape(fc["features"][0]["geometry"])).bounds[2]
            - transform(TO_METRIC, Point(13.4, 52.5)).x
            - 50
        )
        < 0.01
    )
    assert fc["features"][2]["properties"]["geometry_mode"] == "footprint_missing"
    assert len(associate([event()], fc)) == 1
    assert associate([event("street")], fc)[0]["status"] == "approximate_candidate"
    assert associate([event("district")], fc) == []


def test_geocoder_abstains_for_unrelated_streets():
    gaz = Gazetteer(
        [
            dict(
                name="Teststraße",
                geometry=dict(type="LineString", coordinates=[[13.4, 52.5], [13.401, 52.5]]),
            ),
            dict(
                name="Anderstraße",
                geometry=dict(type="LineString", coordinates=[[13.42, 52.5], [13.421, 52.5]]),
            ),
        ]
    )
    assert gaz.locate("In der Teststraße geschah etwas")["location_precision"] == "street"
    assert gaz.locate("Teststraße und Anderstraße")["coordinates"] is None
    assert gaz.locate("Nur Bezirk Mitte")["coordinates"] is None


def test_spatial_partition_includes_boundary_neighbors():
    f = dict(
        type="Feature",
        properties={"id": "p"},
        geometry=dict(type="LineString", coordinates=[[13.399, 52.499], [13.401, 52.501]]),
    )
    parts = tiles([f])
    assert len(parts) == 4
    assert all(v["features"] == [f] for v in parts.values())
