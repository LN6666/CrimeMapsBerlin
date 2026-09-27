"""Synthetic scope and same-name context regressions; no source narratives or city data."""

import pytest
from shapely.geometry import LineString, Point, Polygon, mapping
from shapely.ops import transform

from crimemapsberlin.geocode import Gazetteer
from crimemapsberlin.location_text import normalize
from crimemapsberlin.spatial import TO_METRIC, TO_WGS

X, Y = TO_METRIC(13.4, 52.5)


def road(name, dx=0):
    geometry = transform(TO_WGS, LineString([(X + dx, Y), (X + dx + 100, Y)]))
    return {"name": name, "geometry": mapping(geometry)}


def locality(ident, name, level, left, right):
    geometry = transform(
        TO_WGS,
        Polygon([(X + left, Y - 200), (X + right, Y - 200), (X + right, Y + 200), (X + left, Y + 200)]),
    )
    return {"id": ident, "name": name, "admin_level": level, "geometry": mapping(geometry)}


def place(name, kind, ident, dx):
    metric = Point(X + dx, Y)
    if kind == "park":
        metric = metric.buffer(80)
    geometry = mapping(transform(TO_WGS, metric))
    return {
        "type": "Feature",
        "geometry": geometry,
        "location_geometry": geometry,
        "properties": {
            "id": ident,
            "name": name,
            "kind": kind,
            "aliases": [],
            "geometry_mode": "osm_footprint" if kind == "park" else "osm_point",
        },
    }


def metric_point(result):
    assert result["coordinates"] is not None
    return transform(TO_METRIC, Point(result["coordinates"]))


def test_same_named_district_intro_does_not_clip_to_ortsteil():
    gaz = Gazetteer(
        [road("Teststraße", dx=1000)],
        localities=[
            locality("district-mitte", "Mitte", "9", -100, 2000),
            locality("neighbourhood-mitte", "Mitte", "10", -100, 200),
        ],
    )
    result = gaz.locate("In Mitte wurde in der Teststraße ein Fenster beschädigt.", district="Mitte")
    assert result["location_precision"] == "street"
    assert result["geocode_method"] == "street_representative"
    assert result["location_scope"] == "Mitte"
    assert metric_point(result).distance(Point(X + 1050, Y)) < 1


def test_explicit_ortsteil_still_resolves_same_named_district_homonyms():
    gaz = Gazetteer(
        [road("Teststraße"), road("Teststraße", dx=1000)],
        localities=[
            locality("district-mitte", "Mitte", "9", -100, 2000),
            locality("neighbourhood-mitte", "Mitte", "10", -100, 200),
        ],
    )
    result = gaz.locate("Im Ortsteil Mitte wurde in der Teststraße ein Fenster beschädigt.", district="Mitte")
    assert result["location_precision"] == "street"
    assert result["location_scope"] == "Mitte"
    assert result["location_extent_m"] == 100
    assert metric_point(result).distance(Point(X + 50, Y)) < 1


@pytest.mark.parametrize("intro", ["In Nebenviertel", "Im Ortsteil Nebenviertel"])
def test_out_of_heading_neighbourhood_does_not_widen_district(intro):
    gaz = Gazetteer(
        [road("Teststraße", dx=5000)],
        localities=[
            locality("district-mitte", "Mitte", "9", -100, 200),
            locality("outside-neighbourhood", "Nebenviertel", "10", 4900, 5200),
        ],
    )
    result = gaz.locate(f"{intro} wurde in der Teststraße ein Fenster beschädigt.", district="Mitte")
    assert result["coordinates"] is None
    assert result["geocode_method"] == "locality_conflict_review"
    assert result["location_scope"] == "Mitte"


@pytest.mark.parametrize("kind", ["park", "station"])
def test_named_place_outside_heading_stays_in_review(kind):
    named_place = place("Testort", kind, "osm/node/outside", dx=5000)
    gaz = Gazetteer(
        [],
        places={"features": [named_place]},
        localities=[locality("district-mitte", "Mitte", "9", -100, 200)],
    )
    prefix = "Im Park" if kind == "park" else "Am Bahnhof"
    result = gaz.locate(f"{prefix} Testort wurde ein Mann geschlagen.", district="Mitte")
    assert result["coordinates"] is None
    assert result["geocode_method"] == "locality_conflict_review"
    assert result["location_scope"] == "Mitte"


@pytest.mark.parametrize(
    "name,description",
    [
        ("Innenhof", "In einem Innenhof an der Teststraße"),
        ("Marktplatz", "Auf einem Marktplatz an der Teststraße"),
        ("Uferweg", "Auf einem Uferweg an der Teststraße"),
        ("Auf der Höhe", "Auf der Höhe der Teststraße"),
    ],
)
def test_ordinary_noun_does_not_add_distant_street_candidate(name, description):
    gaz = Gazetteer([road("Teststraße"), road(name, dx=2000)])
    result = gaz.locate(f"{description} schlug ein Mann einen anderen Mann.")
    assert result["location_precision"] == "street"
    assert result["geocode_candidates"] == ["teststrasse"]
    assert metric_point(result).distance(Point(X + 50, Y)) < 1


@pytest.mark.parametrize("name", ["Innenhof", "Marktplatz", "Uferweg", "Auf der Höhe"])
@pytest.mark.parametrize("explicit_form", ["quoted", "named"])
def test_ordinary_word_is_allowed_when_explicitly_a_street_name(name, explicit_form):
    gaz = Gazetteer([road(name)])
    location = f"In der Straße „{name}“" if explicit_form == "quoted" else f"In der Straße namens {name}"
    result = gaz.locate(f"{location} schlug ein Mann einen anderen Mann.")
    assert result["location_precision"] == "street"
    assert result["geocode_candidates"] == [normalize(name)]
    assert metric_point(result).distance(Point(X + 50, Y)) < 1


def test_explicit_station_wins_same_span_distant_road():
    station = place("Teststraße", "station", "osm/node/station", dx=1500)
    gaz = Gazetteer([road("Teststraße")], places={"features": [station]})
    result = gaz.locate("Am U-Bahnhof Teststraße schlug ein Mann einen anderen Mann.")
    assert result["location_precision"] == "place"
    assert result["location_object_ids"] == ["osm/node/station"]
    assert [row["kind"] for row in result["geocode_evidence"]] == ["place"]
    assert metric_point(result).distance(Point(X + 1500, Y)) < 1


def test_road_scene_wins_same_name_distant_park():
    park = place("Testplatz", "park", "osm/way/park", dx=2000)
    gaz = Gazetteer([road("Testplatz")], places={"features": [park]})
    result = gaz.locate("Auf dem Testplatz schlug ein Mann einen anderen Mann.")
    assert result["location_precision"] == "street"
    assert result["location_object_ids"] == []
    assert [row["kind"] for row in result["geocode_evidence"]] == ["street"]
    assert metric_point(result).distance(Point(X + 50, Y)) < 1


@pytest.mark.parametrize("park_name", ["Testplatz", "„Testplatz“"])
def test_explicit_park_scene_wins_same_name_distant_road(park_name):
    park = place("Testplatz", "park", "osm/way/park", dx=2000)
    gaz = Gazetteer([road("Testplatz")], places={"features": [park]})
    result = gaz.locate(f"Im Park {park_name} schlug ein Mann einen anderen Mann.")
    assert result["location_precision"] == "place"
    assert result["location_object_ids"] == ["osm/way/park"]
    assert [row["kind"] for row in result["geocode_evidence"]] == ["place"]
    assert metric_point(result).distance(Point(X + 2000, Y)) < 1


def test_two_distant_same_named_parks_remain_ambiguous():
    parks = [
        place("Testpark", "park", "osm/way/park-a", dx=0),
        place("Testpark", "park", "osm/way/park-b", dx=2000),
    ]
    result = Gazetteer([], places={"features": parks}).locate(
        "Im Testpark schlug ein Mann einen anderen Mann."
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "ambiguous_place_review"
    assert result["location_object_ids"] == []
