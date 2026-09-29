import math
from copy import deepcopy

import pytest
from shapely.geometry import Point, shape
from shapely.ops import transform

from crimemapsberlin.geocode import Gazetteer
from crimemapsberlin.spatial import (
    TO_METRIC,
    associate,
    build_months,
    cell_for,
    count_location,
    hexagons,
    metric_transforms,
    pois_from_osm,
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
    assert (
        hexagons([event(), dict(event("district"), id="2")], 275)["features"][0][
            "properties"
        ]["count"]
        == 1
    )
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


def scene_event():
    primary = dict(
        label="Primary junction", role="incident", location_precision="street",
        geocode_method="osm_explicit_junction", coordinates=[13.4, 52.5],
        primary_for_count=True, evidence_quote="Incident at the primary junction",
    )
    secondary = dict(
        label="Arrest place", role="arrest", location_precision="point",
        geocode_method="source_named_point", coordinates=[13.42, 52.52],
        primary_for_count=False, poi_mentions=["bar"],
    )
    return dict(
        event("street"), location_label=primary["label"],
        geocode_method="multiple_official_scenes", month="2026-09",
        scene_locations=[primary, secondary],
    )


def test_scene_hex_uses_only_primary_and_month_retains_one_announcement():
    report = scene_event()
    assert count_location(report)["coordinates"] == [13.4, 52.5]
    for size in (275, 1100):
        features = hexagons([report], size)["features"]
        assert len(features) == 1
        assert features[0]["properties"]["event_ids"] == [report["id"]]
        assert features[0]["properties"]["count"] == 1
        assert shape(features[0]["geometry"]).covers(Point(13.4, 52.5))
    month = build_months([report], {"features": []})["2026-09"]
    assert month["event_ids"] == [report["id"]]
    assert month["links"] == []


def test_secondary_points_and_road_ranges_display_without_hex_or_poi_links():
    report = scene_event()
    report["scene_locations"][0]["primary_for_count"] = False
    report["coordinates"] = None
    report["location_precision"] = "unknown"
    report["scene_locations"].append(dict(
        label="Road range", role="incident", location_precision="unknown",
        geocode_method="road_review", primary_for_count=False,
        candidate_road_geometry={"type": "LineString", "coordinates": [[13.4, 52.5], [13.41, 52.5]]},
    ))
    assert count_location(report) is None
    month = build_months([report], {"features": []})["2026-09"]
    assert month["event_ids"] == [report["id"]]
    assert month["hex"]["overview"]["features"] == []
    assert month["hex"]["detail"]["features"] == []
    assert month["links"] == []


def test_scene_poi_links_need_primary_scene_specific_evidence():
    pois, _ = pois_from_osm({"elements": [
        dict(type="node", id=1, lon=13.4, lat=52.5, tags={"amenity": "bar"}),
        dict(type="node", id=2, lon=13.42, lat=52.52, tags={"amenity": "bar"}),
    ]})
    report = scene_event()
    assert associate([report], pois) == []  # Whole-article mention is insufficient.
    report["scene_locations"][0]["poi_mentions"] = ["bar"]
    quote = report["scene_locations"][0].pop("evidence_quote")
    assert associate([report], pois) == []
    report["scene_locations"][0]["evidence_quote"] = quote
    links = associate([report], pois)
    assert [link["poi_id"] for link in links] == ["osm/node/1"]
    assert links[0]["mention_basis"] == "scene_specific_source_match"


def test_named_place_link_uses_only_primary_scene_object_id():
    pois, _ = pois_from_osm({"elements": [
        dict(type="node", id=1, lon=13.4, lat=52.5, tags={"amenity": "bar"}),
        dict(type="node", id=2, lon=13.42, lat=52.52, tags={"amenity": "bar"}),
    ]})
    report = scene_event()
    report["location_precision"] = "place"
    report["scene_locations"][0]["location_precision"] = "place"
    report["scene_locations"][0]["location_object_ids"] = ["osm/node/1"]
    report["scene_locations"][1]["location_object_ids"] = ["osm/node/2"]
    assert [(link["poi_id"], link["status"]) for link in associate([report], pois)] == [
        ("osm/node/1", "named_place_candidate"),
    ]


def test_reviewed_context_only_mode_suppresses_implicit_named_place_link():
    pois, _ = pois_from_osm({"elements": [
        dict(type="node", id=1, lon=13.4, lat=52.5, tags={"amenity": "bar"}),
    ]})
    report = scene_event()
    report["location_precision"] = "place"
    report["scene_locations"][0]["location_precision"] = "place"
    report["scene_locations"][0]["location_object_ids"] = ["osm/node/1"]

    assert associate([report], pois, include_legacy_links=False) == []


@pytest.mark.parametrize("change", [
    lambda report: report["scene_locations"][1].update(primary_for_count=True),
    lambda report: report["scene_locations"][0].update(location_precision="district"),
    lambda report: report["scene_locations"][0].update(coordinates=[float("nan"), 52.5]),
    lambda report: report.update(coordinates=[13.41, 52.5]),
    lambda report: report.update(location_label="Unrelated place"),
    lambda report: report.update(candidate_road_geometry={"type": "LineString", "coordinates": []}),
    lambda report: report["scene_locations"][0].update(
        geometry={"type": "Point", "coordinates": [13.41, 52.5]}),
])
def test_scene_count_fails_closed_on_invalid_primary_or_duplicate_road(change):
    report = deepcopy(scene_event())
    change(report)
    with pytest.raises(ValueError):
        count_location(report)


def test_unmarked_scene_cannot_inherit_top_level_point_and_point_geometry_can_identify_primary():
    report = scene_event()
    report["scene_locations"][0]["primary_for_count"] = False
    with pytest.raises(ValueError, match="Top-level point without count scene"):
        count_location(report)
    report["scene_locations"][0]["primary_for_count"] = True
    point = report["scene_locations"][0].pop("coordinates")
    report["scene_locations"][0]["geometry"] = {"type": "Point", "coordinates": point}
    assert count_location(report)["coordinates"] == point


def test_legacy_report_without_scene_array_keeps_existing_counting():
    assert count_location(event()) == event()
    assert count_location(event("district")) is None
    with pytest.raises(ValueError, match="Duplicate announcement ID"):
        hexagons([event(), event()], 275)


def test_reviewed_scene_context_deepens_all_same_type_pois_along_geometry_only():
    pois, _ = pois_from_osm({"elements": [
        dict(type="node", id=1, lon=13.4005, lat=52.5, tags={"amenity": "bar"}),
        dict(type="node", id=2, lon=13.4015, lat=52.5, tags={"amenity": "pub"}),
        dict(type="node", id=3, lon=13.42, lat=52.52, tags={"amenity": "bar"}),
        dict(type="node", id=4, lon=13.401, lat=52.5005, tags={"railway": "station"}),
        dict(type="node", id=5, lon=13.401, lat=52.5, tags={"amenity": "cafe"}),
    ]})
    report = {
        **event("unknown"), "coordinates": None, "location_label": "",
        "scene_locations": [{
            "scene_id": "1:street", "label": "Teststraße", "role": "incident",
            "location_precision": "street", "geocode_method": "reviewed_road",
            "geometry": {
                "type": "LineString",
                "coordinates": [[13.4, 52.5], [13.402, 52.5]],
            },
            "primary_for_count": False,
            "poi_contexts": [
                {
                    "kind": "bar", "scope": "along_geometry", "radius_m": 0,
                    "evidence_quote": "The report names bars along Teststraße.",
                },
                {
                    "kind": "station", "scope": "near_geometry", "radius_m": 75,
                    "evidence_quote": "The report places the event near the station.",
                },
            ],
        }],
    }
    links = associate([report], pois)
    assert {(link["poi_id"], link["status"]) for link in links} == {
        ("osm/node/1", "context_along_geometry"),
        ("osm/node/2", "context_along_geometry"),
        ("osm/node/4", "context_near_geometry"),
    }
    assert all(link["mention_basis"] == "source_reviewed_context_only" for link in links)
    assert count_location(report) is None
