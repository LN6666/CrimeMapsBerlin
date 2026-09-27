"""Road range display must not turn unresolved announcements into point observations."""

import pytest
from shapely.geometry import LineString, Point, Polygon, mapping, shape
from shapely.ops import transform

from crimemapsberlin.geocode import Gazetteer
from crimemapsberlin.spatial import TO_METRIC, TO_WGS, build_months

X, Y = TO_METRIC(13.4, 52.5)


def road(name, coordinates):
    geometry = transform(TO_WGS, LineString([(X + x, Y + y) for x, y in coordinates]))
    return dict(name=name, geometry=mapping(geometry))


def as_event(location, ident="report/1"):
    return dict(
        location,
        id=ident,
        month="2026-09",
        category="Raub",
        poi_mentions=["bar"],
        source_url="https://example.org/report",
        mention_basis="keyword",
    )


def test_long_road_range_preserves_endpoints_and_stays_out_of_hexes_and_poi_links():
    gaz = Gazetteer([road("Teststraße", [(0, 0), (2000, 3), (4100, 0)])])
    location = gaz.locate("In der Teststraße ereignete sich ein Raub.")
    assert location["geocode_method"] == "long_or_ambiguous_street_review"
    assert location["coordinates"] is None and location["location_precision"] == "unknown"
    geometry = transform(TO_METRIC, shape(location["candidate_road_geometry"]))
    assert geometry.geom_type == "LineString"
    assert geometry.distance(Point(X, Y)) < 0.001
    assert geometry.distance(Point(X + 4100, Y)) < 0.001
    assert len(geometry.coords) == 2  # Five-metre display tolerance removes a tiny bend.
    poi = dict(
        type="Feature",
        geometry=mapping(transform(TO_WGS, Point(X + 2000, Y).buffer(50))),
        properties=dict(id="bar/1", kind="bar", geometry_mode="50m_circle"),
    )
    month = build_months([as_event(location)], dict(features=[poi]))["2026-09"]
    assert month["event_ids"] == ["report/1"]
    assert month["hex"]["overview"]["features"] == []
    assert month["hex"]["detail"]["features"] == []
    assert month["links"] == []


def test_disconnected_road_preserves_both_parts_without_connecting_gap():
    gaz = Gazetteer(
        [
            road("Teststraße", [(0, 0), (100, 0)]),
            road("Teststraße", [(1000, 0), (1100, 0)]),
        ]
    )
    location = gaz.locate("In der Teststraße wurde eine Person angegriffen.")
    assert location["geocode_method"] == "disconnected_street_review"
    assert location["coordinates"] is None
    geometry = transform(TO_METRIC, shape(location["candidate_road_geometry"]))
    assert geometry.geom_type == "MultiLineString" and len(geometry.geoms) == 2
    assert geometry.length == pytest.approx(200, abs=0.001)
    assert geometry.distance(Point(X + 550, Y)) > 449


def test_display_range_uses_selected_locality_and_excludes_distant_homonym():
    boundary = transform(
        TO_WGS,
        Polygon([(X - 100, Y - 100), (X + 4200, Y - 100), (X + 4200, Y + 100), (X - 100, Y + 100)]),
    )
    gaz = Gazetteer(
        [
            road("Teststraße", [(0, 0), (4000, 0)]),
            road("Teststraße", [(10000, 0), (11000, 0)]),
        ],
        localities=[dict(id="district/1", name="Mitte", admin_level="9", geometry=mapping(boundary))],
    )
    location = gaz.locate("In der Teststraße kam es zu einem Raub.", district="Mitte")
    geometry = transform(TO_METRIC, shape(location["candidate_road_geometry"]))
    assert location["location_scope"] == "Mitte"
    assert geometry.bounds[2] < X + 4200
    assert geometry.length == pytest.approx(4000, abs=0.001)


def test_actual_scene_road_range_excludes_escape_road():
    gaz = Gazetteer(
        [road("Teststraße", [(0, 0), (4100, 0)]), road("Anderstraße", [(0, 1000), (100, 1000)])]
    )
    location = gaz.locate(
        "In der Teststraße ereignete sich ein Raub. Anschließend flüchtete er in die Anderstraße."
    )
    assert location["geocode_candidates"] == ["teststrasse"]
    geometry = transform(TO_METRIC, shape(location["candidate_road_geometry"]))
    assert geometry.bounds[3] < Y + 1


@pytest.mark.parametrize(
    "narrative,title",
    [
        ("Teststraße und Anderstraße", "Raub"),
        ("Hinweise nimmt die Polizei in der Teststraße entgegen.", "Raub"),
        ("In der Teststraße wurden Fahrzeuge gezählt.", "Bilanz einer Aktionswoche"),
        ("In der Herrmannstraße kam es zu einem Raub.", "Raub"),
    ],
)
def test_name_only_contact_statistics_and_spelling_do_not_gain_road_ranges(narrative, title):
    gaz = Gazetteer(
        [
            road("Teststraße", [(0, 0), (4100, 0)]),
            road("Anderstraße", [(0, 1000), (4100, 1000)]),
            road("Hermannstraße", [(0, 2000), (4100, 2000)]),
        ]
    )
    result = gaz.locate(narrative, title=title)
    assert result["coordinates"] is None
    assert "candidate_road_geometry" not in result


def test_already_resolved_street_does_not_gain_uncertain_road_range():
    result = Gazetteer([road("Teststraße", [(0, 0), (100, 0)])]).locate(
        "In der Teststraße kam es zu einem Raub."
    )
    assert result["coordinates"] and result["geocode_method"] == "street_representative"
    assert "candidate_road_geometry" not in result
