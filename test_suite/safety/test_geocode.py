"""Synthetic regressions for omissions and false geocodes; no copied police reports."""

import pytest
from shapely.geometry import LineString, Point, Polygon, mapping
from shapely.ops import transform

from crimemapsberlin.geocode import Gazetteer
from crimemapsberlin.spatial import TO_METRIC, TO_WGS, associate, hexagons

X, Y = TO_METRIC(13.4, 52.5)


def road(name, coords):
    return dict(
        name=name, geometry=mapping(transform(TO_WGS, LineString([(X + x, Y + y) for x, y in coords])))
    )


def place(name, kind="park", ident="osm/way/1", dx=0):
    geometry = transform(TO_WGS, Point(X + dx, Y).buffer(80))
    return dict(
        type="Feature",
        geometry=mapping(geometry),
        location_geometry=mapping(geometry),
        properties=dict(
            id=ident, name=name, kind=kind, aliases=[], center=[13.4, 52.5], geometry_mode="osm_footprint"
        ),
    )


@pytest.mark.parametrize(
    "name,text",
    [
        ("Karl-Marx-Straße", "In der Karl‑Marx‑Straße wurde ein Fenster beschädigt."),
        ("Karl-Marx-Straße", "An der Karl – Marx – Straße wurde ein Fenster beschädigt."),
        ("Stollberger Straße", "In der Stollberger Str. wurde ein Fenster beschädigt."),
        ("Spanische Allee", "Auf der Spanischen Allee ereignete sich ein Raub."),
        ("Märkische Allee", "In der Märkischen Allee ereignete sich ein Raub."),
        ("Askanierring", "In einem Hinterhof des Askanierrings ereignete sich ein Raub."),
    ],
)
def test_grammatical_and_typographic_variants(name, text):
    result = Gazetteer([road(name, [(0, 0), (100, 0)])]).locate(text)
    assert result["location_precision"] == "street" and result["coordinates"]


def test_full_narrative_and_contact_destination_roles():
    gaz = Gazetteer([road("Teststraße", [(0, 0), (100, 0)]), road("Keithstraße", [(1000, 0), (1100, 0)])])
    text = "Weitere Erkenntnisse werden geprüft. " * 35 + "In der Teststraße ereignete sich ein Raub."
    assert gaz.locate(text)["geocode_candidates"] == ["teststrasse"]
    assert (
        gaz.locate("Ein Raub wurde gemeldet. Hinweise nimmt die Polizei in der Keithstraße entgegen.")[
            "coordinates"
        ]
        is None
    )
    text = "In der Teststraße ereignete sich ein Raub. Anschließend wurde er in ein Krankenhaus in der Keithstraße gebracht."
    assert gaz.locate(text)["geocode_candidates"] == ["teststrasse"]


def test_neighbourhood_is_not_same_named_road():
    gaz = Gazetteer([road("Prenzlauer Berg", [(0, 0), (100, 0)]), road("Teststraße", [(200, 0), (300, 0)])])
    result = gaz.locate(
        "In Prenzlauer Berg wurde eine Person verletzt. In der Teststraße kam es zu einem Streit."
    )
    assert result["geocode_candidates"] == ["teststrasse"]


def test_direction_and_later_restriction_endpoints_do_not_replace_scene():
    gaz = Gazetteer([road("Teststraße", [(0, 0), (100, 0)]), road("Anderstraße", [(500, 0), (600, 0)])])
    result = gaz.locate(
        "In der Teststraße ereignete sich ein Raub in Richtung Anderstraße. Danach wurde die Straße zwischen Anderstraße und Nebenplatz gesperrt."
    )
    assert result["geocode_candidates"] == ["teststrasse"]


def test_junction_refines_travel_context():
    gaz = Gazetteer([road("Teststraße", [(-100, 0), (100, 0)]), road("Anderstraße", [(0, -100), (0, 100)])])
    result = gaz.locate(
        "Ein Wagen fuhr auf der Teststraße in Richtung Anderstraße. An der Kreuzung Teststraße/Anderstraße kam es zum Unfall."
    )
    assert result["geocode_method"] == "named_street_intersection"
    assert Point(result["coordinates"]).distance(Point(13.4, 52.5)) < 1e-7


def test_unrelated_names_are_not_junction():
    gaz = Gazetteer([road("Teststraße", [(-100, 0), (100, 0)]), road("Anderstraße", [(0, -100), (0, 100)])])
    assert (
        gaz.locate("In der Teststraße und Anderstraße wurden Kontrollen durchgeführt.")["coordinates"] is None
    )


def test_nearby_fragments_and_genuinely_separate_roads():
    gaz = Gazetteer([road("Teststraße", [(0, 0), (100, 0)]), road("Teststraße", [(110, 0), (200, 0)])])
    result = gaz.locate("In der Teststraße wurde eine Person verletzt.")
    assert result["coordinates"] and result["location_extent_m"] == 200
    geom = transform(TO_METRIC, Point(result["coordinates"]))
    assert (
        min(
            geom.distance(LineString([(X, Y), (X + 100, Y)])),
            geom.distance(LineString([(X + 110, Y), (X + 200, Y)])),
        )
        < 0.1
    )
    gaz = Gazetteer([road("Teststraße", [(0, 0), (100, 0)]), road("Teststraße", [(1000, 0), (1100, 0)])])
    assert (
        gaz.locate("In der Teststraße wurde eine Person verletzt.")["geocode_method"]
        == "disconnected_street_review"
    )


def test_locality_resolves_distant_homonyms():
    boundary = transform(
        TO_WGS, Polygon([(X - 100, Y - 100), (X + 200, Y - 100), (X + 200, Y + 100), (X - 100, Y + 100)])
    )
    gaz = Gazetteer(
        [road("Teststraße", [(0, 0), (100, 0)]), road("Teststraße", [(10000, 0), (10100, 0)])],
        localities=[dict(id="district", name="Mitte", admin_level="9", geometry=mapping(boundary))],
    )
    assert gaz.locate("In der Teststraße wurde eine Person verletzt.")["coordinates"] is None
    result = gaz.locate("In der Teststraße wurde eine Person verletzt.", district="Mitte")
    assert result["coordinates"] and result["location_scope"] == "Mitte"


def test_named_places_inflection_and_station_not_neighbourhood():
    station = place("Tiergarten", "station", ident="osm/node/2")
    gaz = Gazetteer([], places=dict(features=[place("Kleiner Tiergarten"), station]))
    assert gaz.locate("Im Kleinen Tiergarten kam es zu einem Streit.")["location_precision"] == "place"
    assert gaz.locate("Am S-Bahnhof Tiergarten wurde eine Person verletzt.")["location_object_ids"] == [
        "osm/node/2"
    ]
    assert (
        gaz.locate("In Tiergarten wurde eine Person in einer unbenannten Schule verletzt.", district="Mitte")[
            "coordinates"
        ]
        is None
    )


def test_same_named_place_branches_abstain():
    gaz = Gazetteer(
        [], places=dict(features=[place("Testpark"), place("Testpark", ident="osm/way/2", dx=2000)])
    )
    assert gaz.locate("Im Testpark kam es zu einem Streit.")["geocode_method"] == "ambiguous_place_review"


def test_station_letter_does_not_match_inside_neighbourhood_name():
    gaz = Gazetteer([], places=dict(features=[place("Hohenschönhausen", "station")]))
    assert gaz.locate("In Neu-Hohenschönhausen wurde eine Person verletzt.")["coordinates"] is None


def test_numbered_street_name_is_not_split_at_month():
    gaz = Gazetteer([road("Straße des 17. Juni", [(0, 0), (100, 0)])])
    assert gaz.locate("Auf der Straße des 17. Juni wurde eine Person verletzt.")["coordinates"]


def test_refinement_does_not_replace_first_explicit_junction():
    gaz = Gazetteer(
        [
            road("Teststraße", [(0, -100), (0, 1000)]),
            road("Anderstraße", [(-100, 0), (100, 0)]),
            road("Nebenstraße", [(-100, 800), (100, 800)]),
        ]
    )
    result = gaz.locate(
        "An der Kreuzung Teststraße/Anderstraße kam es zum Unfall. An der Kreuzung Teststraße/Nebenstraße ereignete sich ein weiterer Unfall."
    )
    assert set(result["geocode_candidates"]) == {"teststrasse", "anderstrasse"}


def test_ordinary_word_business_name_needs_venue_context():
    gaz = Gazetteer([], places=dict(features=[place("Nacht", "bar")]))
    assert gaz.locate("In der Nacht wurde eine Person verletzt.")["coordinates"] is None
    assert gaz.locate("In der Bar „Nacht“ wurde eine Person verletzt.")["location_precision"] == "place"


def test_generic_names_contact_and_policy_not_scene():
    gaz = Gazetteer([road("Aufzug", [(0, 0), (100, 0)]), road("Teststraße", [(200, 0), (300, 0)])])
    assert gaz.locate("Ein Mann wurde in einem Aufzug verletzt.")["coordinates"] is None
    assert (
        gaz.locate("Die Polizei ist telefonisch unter 123 in der Teststraße erreichbar.")["coordinates"]
        is None
    )
    assert (
        gaz.locate("In der Teststraße wurden Fahrzeuge gezählt.", title="Bilanz einer Aktionswoche")[
            "geocode_method"
        ]
        == "non_incident_report"
    )


def test_typo_suggests_but_does_not_fabricate_coordinate():
    gaz = Gazetteer([road("Hermannstraße", [(0, 0), (100, 0)])])
    result = gaz.locate("In der Herrmannstraße wurde eine Person verletzt.")
    assert result["coordinates"] is None and result["geocode_candidates"] == ["hermannstrasse"]
    assert result["geocode_method"] == "spelling_review"


def test_boarding_station_is_not_assault_scene():
    gaz = Gazetteer(
        [road("Teststraße", [(0, 0), (100, 0)])],
        places=dict(features=[place("Anderbahnhof", "station", dx=2000)]),
    )
    result = gaz.locate(
        "Die Männer stiegen am Anderbahnhof in einen Bus ein. Der Fahrer forderte sie an der Bushaltestelle Teststraße zum Aussteigen auf. Daraufhin wurde er geschlagen."
    )
    assert result["geocode_candidates"] == ["teststrasse"]
    assert result["location_precision"] == "street"
    assert (
        gaz.locate(
            "Die Männer stiegen am Anderbahnhof in einen Bus ein. Später wurde der Fahrer geschlagen."
        )["coordinates"]
        is None
    )


def test_control_stop_is_not_later_collision_scene():
    gaz = Gazetteer(
        [
            road("Teststraße", [(0, -100), (0, 100)]),
            road("Anderstraße", [(900, 0), (1100, 0)]),
            road("Nebenstraße", [(1000, -100), (1000, 100)]),
        ]
    )
    result = gaz.locate(
        "Die Polizei forderte den Fahrer in der Teststraße zum Anhalten auf. Später kollidierte er an der Kreuzung Anderstraße/Nebenstraße mit einem Auto."
    )
    assert result["geocode_method"] == "named_street_intersection"
    assert set(result["geocode_candidates"]) == {"anderstrasse", "nebenstrasse"}


def test_explicit_house_number_uses_address_index():
    gaz = Gazetteer(
        [road("Teststraße", [(0, 0), (5000, 0)])],
        addresses=[dict(street="Teststraße", number="12a", coordinates=[13.4, 52.5])],
    )
    result = gaz.locate("In der Teststraße 12a wurde ein Fenster beschädigt.")
    assert result["coordinates"] == [13.4, 52.5] and result["location_precision"] == "address"
    assert gaz.locate("In der Teststraße wurde ein Fenster beschädigt.")["coordinates"] is None


def test_place_hex_and_association_use_named_object_only():
    named, neighbour = place("Testpark"), place("Anderpark", ident="osm/way/2")
    fc = dict(features=[named, neighbour])
    result = Gazetteer([], places=fc).locate("Im Testpark kam es zu einem Streit.")
    event = dict(
        result,
        id="1",
        category="Gewalt",
        poi_mentions=["park"],
        source_url="https://example.org",
        mention_basis="keyword",
    )
    assert hexagons([event], 275)["features"][0]["properties"]["approximate_count"] == 1
    assert [link["poi_id"] for link in associate([event], fc)] == ["osm/way/1"]
    assert associate([event], fc)[0]["status"] == "named_place_candidate"
