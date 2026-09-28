"""Synthetic regressions for omissions and false geocodes; no copied police reports."""

import pytest
from shapely.geometry import LineString, Point, Polygon, mapping
from shapely.ops import transform

from crimemapsberlin.city_sources import normalized_event_db
from crimemapsberlin.geocode import Gazetteer, events_from_db
from crimemapsberlin.spatial import TO_METRIC, TO_WGS, associate, hexagons, metric_transforms

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


def test_city_specific_projection_keeps_hamburg_street_in_hamburg():
    to_metric, to_wgs = metric_transforms(25832)
    gaz = Gazetteer(
        [{"name": "Teststraße", "geometry": mapping(LineString([(10.0, 53.55), (10.001, 53.55)]))}],
        to_metric=to_metric, to_wgs=to_wgs,
    )
    result = gaz.locate("In der Teststraße ereignete sich ein Raub.")
    assert result["location_precision"] == "street"
    assert 9.99 < result["coordinates"][0] < 10.01
    assert 53.54 < result["coordinates"][1] < 53.56


def test_singular_hamburg_tatort_heading_scopes_a_road_without_inventing_missing_person_scene():
    to_metric, to_wgs = metric_transforms(25832)
    x, y = to_metric(10.0, 53.55)
    first = LineString([(x - 100, y), (x + 100, y)])
    second = LineString([(x + 3000, y), (x + 3100, y)])
    area = Polygon([(x - 250, y - 250), (x + 250, y - 250),
                    (x + 250, y + 250), (x - 250, y + 250)])
    gaz = Gazetteer(
        [{"name": "Baumkamp", "geometry": mapping(transform(to_wgs, line))}
         for line in (first, second)],
        localities=[{"id": "winterhude", "name": "Winterhude", "admin_level": "10",
                     "geometry": mapping(transform(to_wgs, area))}],
        to_metric=to_metric, to_wgs=to_wgs,
    )
    body = "Tatzeit: 04.01.2026, 03:34 Uhr; Tatort: Hamburg-Winterhude, Baumkamp Am Haus wurde eingebrochen."
    result = gaz.locate(body, title="Versuchter Wohnungseinbruch", district="Winterhude")
    assert result["location_precision"] == "street"
    assert result["location_selection"] == "official_tatort_heading"
    assert transform(to_metric, Point(result["coordinates"])).distance(first) < 1
    missing = gaz.locate(
        "Ort: Hamburg-Winterhude, Baumkamp Eine Person wird vermisst.",
        title="Vermisstenfahndung nach einer Person", district="Winterhude",
    )
    assert missing["coordinates"] is None
    assert missing["geocode_method"] == "non_incident_report"
    plural = gaz.locate("Tatorte: Hamburg-Winterhude, Baumkamp; Hamburg-Harburg, Nebenstraße")
    assert plural["coordinates"] is None
    assert plural["geocode_method"] == "multiple_official_scenes"
    mixed = gaz.locate(
        "Tatorte: Hamburg-St. Georg, Norderstraße; Hamburg-HafenCity, Überseeallee. "
        "Der Verdächtige wurde am Neuer Wall festgenommen.",
        title="Tataufklärung zweier Raube",
    )
    assert mixed["coordinates"] is None
    assert mixed["geocode_method"] == "multiple_official_scenes"
    assert "Neuer Wall" not in mixed["location_label"]
    searches = gaz.locate(
        "Orte: Hamburg-Winterhude, Baumkamp, und Hamburg-Harburg, Nebenstraße. "
        "In dem Geschäft am Baumkamp wurden Beweismittel sichergestellt.",
        title="Durchsuchungen an mehreren Orten",
    )
    assert searches["coordinates"] is None
    assert searches["geocode_method"] == "operation_locations_only"
    repeated_singular = gaz.locate(
        "Tatort: Hamburg-Winterhude, Baumkamp. Dort wurde ein Mann beraubt. "
        "Tatort: Hamburg-Harburg, Nebenstraße. Dort wurde eine Frau beraubt.",
        title="Zwei Zeugenaufrufe",
    )
    assert repeated_singular["coordinates"] is None
    assert repeated_singular["geocode_method"] == "multiple_official_scenes"
    collision = gaz.locate(
        body.replace("Tatort:", "Unfallort:"),
        title="Unfall in Hamburg-Winterhude", district="Winterhude",
    )
    assert collision["location_selection"] == "official_tatort_heading"
    assert collision["location_precision"] == "street"
    invitation = gaz.locate(body, title="Einladung zum Fototermin", district="Winterhude")
    assert invitation["geocode_method"] == "non_incident_report"
    summary = gaz.locate(body, title="Bilanz der Silvesternacht", district="Winterhude")
    assert summary["coordinates"] is None
    assert summary["geocode_method"] == "multi_event_summary"
    safety_balance = gaz.locate(body, title="Verkehrssicherheitsbilanz 2025", district="Winterhude")
    assert safety_balance["coordinates"] is None
    assert safety_balance["geocode_method"] == "non_incident_report"
    boats = gaz.locate(body, title="Neue Streifenboote für die Wasserschutzpolizei")
    assert boats["coordinates"] is None
    assert boats["geocode_method"] == "non_incident_report"
    prevention = gaz.locate(
        "Präventionsberatung in der Teststraße.",
        title='"In Hamburg ist man plietsch - Dein Lifehack gegen krumme Dinger"',
    )
    assert prevention["coordinates"] is None
    assert prevention["geocode_method"] == "non_incident_report"
    broadcast = gaz.locate(
        "Ein alter Fall wird im Fernsehen erneut vorgestellt.",
        title='Sendehinweis - Hamburger Fall bei "Aktenzeichen XY... Ungelöst"',
    )
    assert broadcast["coordinates"] is None
    assert broadcast["geocode_method"] == "non_incident_report"
    summit = gaz.locate(
        "Für einen Gipfel richtet die Polizei eine Sicherheitszone ein.",
        title="Nordseegipfel 2026 in Hamburg - Hinweise der Polizei",
    )
    assert summit["coordinates"] is None
    assert summit["geocode_method"] == "non_incident_report"
    match_summary = gaz.locate(
        "Ort: Hamburger Stadtgebiet. Die Polizei zieht eine positive Bilanz. "
        "Zwei Fanmärsche verliefen durch verschiedene Stadtteile.",
        title="Polizeieinsatz anlässlich einer Bundesligabegegnung",
    )
    assert match_summary["coordinates"] is None
    assert match_summary["geocode_method"] == "multi_event_summary"
    reading = gaz.locate(
        "Eine Lesung findet im Polizeimuseum statt.",
        title='"Krimisalon" im Polizeimuseum Hamburg',
    )
    assert reading["coordinates"] is None
    assert reading["geocode_method"] == "non_incident_report"


def test_official_scene_heading_survives_later_arrest_in_same_sentence():
    to_metric, to_wgs = metric_transforms(25832)
    x, y = to_metric(10.0, 53.55)
    street = LineString([(x - 80, y), (x + 80, y)])
    gaz = Gazetteer(
        [{"name": "Raboisen", "geometry": mapping(transform(to_wgs, street))}],
        to_metric=to_metric, to_wgs=to_wgs,
    )
    result = gaz.locate(
        "Tatzeit: 02.01.2026, 16:00 Uhr Tatort: Hamburg-Altstadt, Raboisen "
        "Am Nachmittag wurde ein Verdächtiger festgenommen."
    )
    assert result["location_precision"] == "street"
    assert result["location_selection"] == "official_tatort_heading"

    station = Gazetteer(
        [],
        places={
            "type": "FeatureCollection",
            "features": [place("Hoheluftbrücke", kind="station")],
        },
    ).locate(
        "Tatort: Am Bahnsteig des U-Bahnhofes Hoheluftbrücke Gestern beleidigte ein "
        "Mann seinen Kontrahenten und schlug ihn.",
        title="Zeugenaufruf nach rassistischer Beleidigung",
    )
    assert station["coordinates"] is not None
    assert station["location_selection"] == "official_tatort_heading"


def test_official_u_bahn_line_stop_is_selected_once_as_tatort():
    result = Gazetteer(
        [],
        places={
            "type": "FeatureCollection",
            "features": [place("Wandsbek Markt", kind="station")],
        },
    ).locate(
        "Tatort: Hamburg-Wandsbek, U-Bahn-Linie 1 (U1), Haltestelle Wandsbek Markt "
        "Am U-Bahnhof Wandsbek Markt kamen zwei Personen ums Leben.",
        title="Erste Erkenntnisse nach Tötungsdelikt",
    )
    assert result["coordinates"] is not None
    assert result["location_selection"] == "official_tatort_heading"
    assert result["geocode_evidence"] == [
        {
            "name": "wandsbek markt",
            "kind": "place",
            "role": "primary",
            "sentence_index": 0,
        }
    ]


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


def test_street_near_checked_premises_is_proximity_not_police_destination():
    gaz = Gazetteer([
        road("Steindamm", [(0, 0), (100, 0)]),
        road("Stralsunder Straße", [(1000, 0), (1100, 0)]),
    ])
    result = gaz.locate(
        "Feststellort: Hamburg-St. Georg, Steindamm. Zivilfahnder des "
        "Polizeikommissariats überprüften Räume in einem Haus nahe der Stralsunder Straße, "
        "nachdem Bürger Hinweise auf unerlaubtes Glücksspiel gegeben hatten.",
        district="St. Georg",
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "unscoped_locations_review"
    assert {"name": "stralsunder strasse", "role": "proximity", "sentence_index": 1} in result[
        "excluded_location_context"
    ]


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


def test_three_road_junction_with_split_carriageways():
    gaz = Gazetteer(
        [
            road("Teststraße", [(-100, 0), (100, 0)]),
            road("Anderstraße", [(0, -100), (0, -5)]),
            road("Nebenstraße", [(0, 5), (0, 100)]),
        ]
    )
    result = gaz.locate("An der Kreuzung Teststraße/Anderstraße/Nebenstraße kollidierten zwei Autos.")
    assert result["geocode_method"] == "named_street_intersection"
    point = transform(TO_METRIC, Point(result["coordinates"]))
    assert point.distance(Point(X, Y)) < 20


def test_multiple_distant_crossings_are_not_averaged():
    gaz = Gazetteer(
        [
            road("Teststraße", [(-100, 0), (1100, 0)]),
            road("Anderstraße", [(0, -100), (0, 100)]),
            road("Anderstraße", [(1000, -100), (1000, 100)]),
        ]
    )
    result = gaz.locate("An der Kreuzung Teststraße/Anderstraße kam es zum Unfall.")
    assert result["coordinates"] is None
    assert result["geocode_method"] == "junction_geometry_review"


def test_reported_section_stays_between_end_roads():
    gaz = Gazetteer(
        [
            road("Teststraße", [(-1000, 0), (2000, 0)]),
            road("Anderstraße", [(0, -100), (0, 100)]),
            road("Nebenstraße", [(500, -100), (500, 100)]),
        ]
    )
    result = gaz.locate(
        "In der Teststraße zwischen Anderstraße und Nebenstraße wurde eine Person angegriffen."
    )
    assert result["geocode_method"] == "reported_street_section"
    assert result["location_extent_m"] == 500
    point = transform(TO_METRIC, Point(result["coordinates"]))
    assert X <= point.x <= X + 500 and abs(point.y - Y) < 0.1
    assert result["reported_location_geometry"]["type"] == "LineString"


def test_official_heading_keeps_section_boundary_roads():
    gaz = Gazetteer([
        road("Mainstraße", [(0, 0), (100, 0)]),
        road("Weststraße", [(20, -40), (20, 40)]),
        road("Oststraße", [(80, -40), (80, 40)]),
    ])
    result = gaz.locate(
        "Tatort: Berlin-Mitte, Mainstraße, Gehweg zwischen Weststraße und Oststraße. "
        "Dort wurde eine Person mit einem Messer verletzt.",
        title="Zeugenaufruf nach Auseinandersetzung",
    )
    assert result["geocode_method"] == "reported_street_section"
    assert result["location_label"] == "mainstrasse (zwischen weststrasse / oststrasse)"


def test_official_accident_heading_promotes_section_endpoint_mislabeled_as_restriction():
    gaz = Gazetteer([
        road("Drosselstraße", [(0, 0), (100, 0)]),
        road("Steilshooper Straße", [(20, -40), (20, 40)]),
        road("Bramfelder Straße", [(80, -40), (80, 40)]),
    ])
    result = gaz.locate(
        "Unfallort: Hamburg-Barmbek-Nord, Drosselstraße (zwischen Steilshooper Straße "
        "und Bramfelder Straße) Dort kam es zu einem Verkehrsunfall.",
        title="Zeugenaufruf nach Verkehrsunfall",
    )
    assert result["geocode_method"] == "reported_street_section"
    assert result["location_label"] == (
        "drosselstrasse (zwischen steilshooper strasse / bramfelder strasse)"
    )


def test_official_height_and_later_junction_refine_a_long_road():
    gaz = Gazetteer([
        road("Mainstraße", [(0, 0), (1000, 0)]),
        road("Querweg", [(200, -100), (200, 100)]),
    ])
    official_height = gaz.locate(
        "Tatort: Berlin-Mitte, Mainstraße (Höhe Querweg). "
        "Dort wurde eine Person angegriffen.",
        title="Zeugenaufruf nach Angriff",
    )
    assert official_height["geocode_method"] == "named_street_intersection"
    assert official_height["location_label"] == "mainstrasse / querweg"

    official_slash = gaz.locate(
        "Unfallort: Berlin-Mitte, Mainstraße / Querweg. Dort kollidierten zwei Fahrzeuge.",
        title="Zeugenaufruf nach Verkehrsunfall",
    )
    assert official_slash["geocode_method"] == "named_street_intersection"
    assert official_slash["location_label"] == "mainstrasse / querweg"

    later_detail = gaz.locate(
        "Unfallort: Berlin-Mitte, Mainstraße. Eine Autofahrerin wurde abgedrängt. "
        "Kurz hinter der Einmündung Querweg/Mainstraße wechselte ein Lkw auf ihren Fahrstreifen. "
        "Sie kollidierte dort mit einem Baum.",
        title="Zeugenaufruf nach Verkehrsunfallflucht",
    )
    assert later_detail["geocode_method"] == "named_street_intersection"
    assert later_detail["location_label"] == "mainstrasse / querweg"


def test_official_named_park_outranks_nearby_road_representative():
    park = place("Planten un Blomen", ident="osm/relation/park")
    gaz = Gazetteer(
        [road("St. Petersburger Straße", [(-300, 0), (300, 0)])],
        places={"type": "FeatureCollection", "features": [park]},
    )
    result = gaz.locate(
        "Tatort: Hamburg-St. Pauli, St. Petersburger Straße, Planten un Blomen im Bereich Rosengarten. "
        "In den Grünanlagen von Planten un Blomen wurde ein Mann angegriffen.",
        title="Zeugenaufruf nach Angriff",
    )
    assert result["geocode_method"] == "named_place_representative"
    assert result["location_label"] == "Planten un Blomen"


def test_two_official_streets_joined_by_and_are_not_collapsed_to_the_first():
    result = Gazetteer([
        road("Talstraße", [(0, 0), (100, 0)]),
        road("Simon-von-Utrecht-Straße", [(300, 0), (400, 0)]),
    ]).locate(
        "Tatort: Hamburg-St. Pauli, Talstraße und Simon-von-Utrecht-Straße. "
        "Der Streit begann in der Talstraße; später wurde die Person in der "
        "Simon-von-Utrecht-Straße angegriffen.",
        title="Zeugenaufruf nach Angriff",
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "multiple_locations_review"
    assert result["geocode_candidates"] == ["simon-von-utrecht-strasse", "talstrasse"]

    cross_district = Gazetteer([
        road("Holstenhofweg", [(0, 0), (100, 0)]),
        road("Dannerallee", [(300, 0), (400, 0)]),
    ]).locate(
        "Tatort: Hamburg-Wandsbek, Holstenhofweg und Hamburg-Horn, Dannerallee. "
        "An der ersten Straße wurde das Opfer bedroht, an der zweiten wurde Eigentum genommen.",
        title="Zwei Zuführungen nach Raubdelikt",
    )
    assert cross_district["coordinates"] is None
    assert cross_district["geocode_method"] == "multiple_locations_review"
    assert cross_district["geocode_candidates"] == ["dannerallee", "holstenhofweg"]


def test_distant_explicit_scene_conflicting_with_official_heading_blocks_point():
    gaz = Gazetteer(
        [road("Headingstraße", [(0, 0), (100, 0)])],
        places={
            "type": "FeatureCollection",
            "features": [place("Berliner Tor", kind="station", ident="osm/node/station", dx=800)],
        },
    )
    result = gaz.locate(
        "Tatort: Hamburg-Mitte, Headingstraße. Am Bahnhof Berliner Tor boten Personen "
        "mutmaßlich gefälschte Waren zum Kauf an.",
        title="Festnahmen nach mutmaßlichem Plagiatsverkauf",
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "conflicting_explicit_scenes"
    assert result["geocode_candidates"] == ["berliner tor", "headingstrasse"]


def test_different_named_neighbourhood_with_explicit_drug_handover_conflicts_with_heading():
    heading_area = Polygon([
        (X - 200, Y - 200), (X + 200, Y - 200),
        (X + 200, Y + 200), (X - 200, Y + 200),
    ])
    other_area = Polygon([
        (X + 800, Y - 200), (X + 1200, Y - 200),
        (X + 1200, Y + 200), (X + 800, Y + 200),
    ])
    gaz = Gazetteer(
        [road("Headingstraße", [(0, 0), (100, 0)])],
        localities=[
            dict(id="heading", name="Headingviertel", admin_level="10",
                 geometry=mapping(transform(TO_WGS, heading_area))),
            dict(id="other", name="Fernviertel", admin_level="10",
                 geometry=mapping(transform(TO_WGS, other_area))),
        ],
    )
    result = gaz.locate(
        "Tatort: Hamburg-Headingviertel, Headingstraße. Ein Zeuge beobachtete das "
        "Treffen zweier Fahrzeuge im Hamburger Stadtteil Fernviertel. Dabei übergab "
        "ein Fahrer eine Tüte und erhielt im Gegenzug eine Sporttasche.",
        title="Festnahme nach mutmaßlichem Drogenhandel",
        district="Headingviertel",
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "conflicting_explicit_scenes"
    assert result["geocode_candidates"] == ["fernviertel", "headingstrasse"]
    assert result["other_scene_candidates"] == [
        {"name": "fernviertel", "sentence_index": 1}
    ]
    assert "candidate_road_geometry" not in result


def test_road_race_route_is_not_reduced_to_first_named_street():
    gaz = Gazetteer([road("Teststraße", [(0, 0), (100, 0)])])
    result = gaz.locate(
        "Auf der Teststraße fiel ein Fahrzeug auf und fuhr anschließend über mehrere Autobahnen.",
        title="Verbotenes Kraftfahrzeugrennen - Polizei stoppt Raser",
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "moving_scene_review"

    fixed_scene = gaz.locate(
        "Tatort: Berlin-Mitte, Teststraße. Dort führte der Fahrer ein Straßenrennen durch.",
        title="Verbotenes Straßenrennen",
    )
    assert fixed_scene["coordinates"] is not None
    assert fixed_scene["geocode_method"] == "street_representative"


def test_generic_official_ort_and_unnamed_venue_on_long_road():
    short = Gazetteer([road("Testweg", [(0, 0), (400, 0)])]).locate(
        "Ort: Hamburg-Mitte, Testweg. In einer Wohnung kam es zu einem Brand.",
        title="Person nach Wohnungsbrand verstorben",
    )
    assert short["geocode_method"] == "street_representative"

    long = Gazetteer([road("Hauptstraße", [(0, 0), (1800, 0)])]).locate(
        "Tatort: Hamburg-Mitte, Hauptstraße. Eine unbekannte Spielhalle wurde überfallen.",
        title="Zeugenaufruf nach Überfall auf eine Spielhalle",
    )
    assert long["coordinates"] is None
    assert long["geocode_method"] == "long_or_ambiguous_street_review"

    office = Gazetteer([road("Reeseberg", [(0, 0), (1200, 0)])]).locate(
        "Tatort: Hamburg-Wilstorf, Reeseberg. In den Räumlichkeiten eines Vereins wurde ein Mann überfallen.",
        title="Zeugenaufruf nach versuchtem Raub in Vereinsräumen",
    )
    assert office["coordinates"] is None
    assert office["geocode_method"] == "long_or_ambiguous_street_review"

    yard = Gazetteer([road("Lagerstraße", [(0, 0), (650, 0)])]).locate(
        "Tatort: Hamburg-Mitte, Lagerstraße. Aus dem Bereich eines Gewerbehofes "
        "wurden mehrere Schüsse abgegeben.",
        title="Zeugenaufruf nach Tötungsdelikt",
    )
    assert yard["coordinates"] is None
    assert yard["geocode_method"] == "long_or_ambiguous_street_review"

    residential = Gazetteer([road("Baakenallee", [(0, 0), (650, 0)])]).locate(
        "Tatort: Hamburg-HafenCity, Baakenallee. Der Mann brach in die Wohnung eines "
        "Bewohners ein und entwendete Schmuck.",
        title="Wohnungseinbruchdiebstahl",
    )
    assert residential["coordinates"] is None
    assert residential["geocode_method"] == "long_or_ambiguous_street_review"


def test_police_operation_locations_are_not_used_as_the_underlying_crime_scene():
    result = Gazetteer([
        road("Heidhorst", [(0, 0), (100, 0)]),
        road("Pulverhofsweg", [(300, 0), (400, 0)]),
    ]).locate(
        "Zeit: 25.06.2026, 06:00 Uhr Ort: Hamburg-Lohbrügge, Heidhorst und "
        "Hamburg-Farmsen-Berne, Pulverhofsweg. "
        "Dort wurden ein Haus und Fahrzeuge beschlagnahmt. Der Kredit soll zuvor mit "
        "gefälschten Unterlagen erlangt worden sein.",
        title="Polizei pfändet und beschlagnahmt Vermögenswerte",
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "operation_locations_only"

    prior_scene = Gazetteer([road("Talstraße", [(0, 0), (100, 0)])]).locate(
        "Tatzeit: 24.05.2026, 06:15 Uhr Ort: Hamburg-St. Pauli, Talstraße. "
        "Dort war ein Mann überfallen worden.",
        title="Tataufklärung und Vollstreckung eines Haftbefehls nach Raubdelikt",
    )
    assert prior_scene["coordinates"] is not None
    assert prior_scene["geocode_method"] == "street_representative"


def test_body_discovery_does_not_become_a_killing_point():
    result = Gazetteer([road("Haberkamp", [(0, 0), (100, 0)])]).locate(
        "Feststellzeit: 22.08.2026, 06:15 Uhr Tatort: Hamburg-Poppenbüttel, Haberkamp. "
        "Am Morgen ist eine tödlich verletzte Frau in einer Grünanlage aufgefunden worden.",
        title="Erste Erkenntnisse nach Tötungsdelikt",
        district="Poppenbüttel",
    )
    assert result["coordinates"] is None
    assert result["location_precision"] == "district"
    assert result["geocode_method"] == "discovery_only_scene_review"


def test_attack_in_moving_bus_is_not_reduced_to_road_midpoint():
    result = Gazetteer([road("Mönckebergstraße", [(0, 0), (740, 0)])]).locate(
        "Tatort: Hamburg-Altstadt, Mönckebergstraße. Ein Fahrgast wurde in einem "
        "Linienbus beleidigt und ein Zeuge anschließend angegriffen.",
        title="Öffentlichkeitsfahndung nach Hasskriminalität",
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "moving_scene_review"

    after_departure = Gazetteer([road("Busweg", [(0, 0), (100, 0)])]).locate(
        "Tatort: Hamburg-Mitte, Busweg. Eine Frau suchte Schutz in einem Bus. "
        "Kurz nach dem Anfahren des Busses fielen Schüsse auf das Fahrzeug.",
        title="Schussabgaben auf einen Linienbus",
    )
    assert after_departure["coordinates"] is None
    assert after_departure["geocode_method"] == "moving_scene_review"


def test_transit_used_before_or_after_street_attack_does_not_erase_official_scene():
    gaz = Gazetteer([road("Tatweg", [(0, 0), (100, 0)])])

    arrived = gaz.locate(
        "Tatort: Hamburg-Mitte, Tatweg. Die Gruppe war zuvor in eine U-Bahn gestiegen. "
        "Am Tatweg schlug ein Mann das Opfer.",
        title="Festnahme nach gefährlicher Körperverletzung",
        district="Mitte",
    )
    escaped = gaz.locate(
        "Tatort: Hamburg-Mitte, Tatweg. Dort schlug ein Mann das Opfer. "
        "Anschließend konnte sich das Opfer in eine U-Bahn retten.",
        title="Zeugenaufruf nach gefährlicher Körperverletzung",
        district="Mitte",
    )

    assert arrived["geocode_method"] == "street_representative"
    assert arrived["coordinates"] is not None
    assert escaped["geocode_method"] == "street_representative"
    assert escaped["coordinates"] is not None


def test_official_slash_junction_promotes_a_road_demoted_by_later_response_text():
    gaz = Gazetteer([
        road("Gustav-Falke-Straße", [(-100, 0), (100, 0)]),
        road("Helene-Lange-Straße", [(0, -100), (0, 100)]),
    ])
    result = gaz.locate(
        "Tatort: Hamburg-Harvestehude, Gustav-Falke-Straße/Helene-Lange-Straße "
        "Gestern haben Fahnder zwei Verdächtige festgenommen. Dort fand eine "
        "konspirative Übergabe von Betäubungsmitteln statt.",
        title="Zuführungen nach Verdacht des Betäubungsmittelhandels",
    )
    assert result["coordinates"] is not None
    assert result["geocode_method"] == "named_street_intersection"


def test_repeated_incidents_over_time_are_not_collapsed_to_one_street_point():
    result = Gazetteer([road("Tilsiter Straße", [(0, 0), (1400, 0)])]).locate(
        "Tatort: Hamburg-Wandsbek, Tilsiter Straße. Seit Oktober kam es zu mehrfachen "
        "Diebstählen aus einem nicht näher bezeichneten Lager.",
        title="Festnahmen nach Diebstahl von Maschinen",
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "multi_event_summary"


def test_near_junction_stays_unlocated_and_outranks_earlier_collision():
    gaz = Gazetteer([
        road("Kennedybrücke", [(0, 0), (200, 0)]),
        road("Ferdinandstor", [(100, -100), (100, 100)]),
        road("An der Verbindungsbahn", [(400, 0), (600, 0)]),
    ])
    result = gaz.locate(
        "Unfallort: Hamburg-St. Georg, Kennedybrücke (nahe Ferdinandstor). "
        "Zuvor kollidierte der Wagen in der Straße An der Verbindungsbahn mit einem Kantstein. "
        "Auf der Kennedybrücke nahe Ferdinandstor stieß er mit einem Transporter zusammen.",
        title="Schwerer Verkehrsunfall in Hamburg-St. Georg",
        district="St. Georg",
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "multiple_locations_review"
    assert result["location_label"] == "ferdinandstor / kennedybrücke"
    assert result["location_selection"] == "official_tatort_heading"
    assert result["other_scene_candidates"] == [
        {"name": "an der verbindungsbahn", "sentence_index": 1}
    ]


def test_explicitly_unknown_scene_does_not_map_pre_attack_or_discovery_locations():
    result = Gazetteer([
        road("Eißendorfer Straße", [(0, 0), (100, 0)]),
        road("Mehringweg", [(50, -50), (50, 50)]),
        road("Göhlbachtal", [(200, 0), (300, 0)]),
    ]).locate(
        "Tatort: Hamburg-Eißendorf. Die Männer trafen sich an der Eißendorfer Straße / Mehringweg. "
        "Später wurde der Verletzte im Göhlbachtal gefunden. Die Fahndung führte nicht zur eindeutigen "
        "Lokalisierung des Tatortes.",
        title="Erste Erkenntnisse nach Tötungsdelikt",
        district="Eißendorf",
    )
    assert result["coordinates"] is None
    assert result["location_precision"] == "district"
    assert result["geocode_method"] == "explicitly_unlocated_scene"


def test_discovery_place_is_not_mapped_when_source_says_it_is_not_the_crime_scene():
    result = Gazetteer([
        road("Mehringweg", [(0, 0), (100, 0)]),
        road("Göhlbachtal", [(500, 0), (600, 0)]),
    ]).locate(
        "Ort: Hamburg-Harburg. Der zunächst angenommene Sachverhalt am Mehringweg konnte "
        "widerlegt werden. Der Verletzte wurde im Göhlbachtal gefunden. Bei dem Fundort "
        "handelt es sich nicht um den eigentlichen Tatort.",
        title="Weitere Erkenntnisse nach Tötungsdelikt",
        district="Harburg",
    )
    assert result["coordinates"] is None
    assert result["location_precision"] == "district"
    assert result["geocode_method"] == "explicitly_unlocated_scene"


def test_unlocated_second_scene_does_not_erase_an_independent_official_scene():
    result = Gazetteer([road("Teststraße", [(0, 0), (120, 0)])]).locate(
        "Tatort: Hamburg-Mitte, Teststraße. Dort wurde ein Mann beraubt. "
        "Zu einem zweiten Vorfall war eine eindeutige Lokalisierung des Tatortes nicht möglich.",
        title="Zeugenaufrufe zu zwei Vorfällen",
        district="Mitte",
    )
    assert result["coordinates"] is not None
    assert result["location_label"] == "teststrasse"


def test_arrest_location_stays_response_when_relative_clause_mentions_attack():
    result = Gazetteer([
        road("Tatstraße", [(0, 0), (100, 0)]),
        road("Nebenstraße", [(500, 0), (600, 0)]),
    ]).locate(
        "In der Tatstraße wurde eine Person angegriffen. "
        "In der Nebenstraße wurde der Verdächtige festgenommen, der zuvor das Opfer angegriffen hatte."
    )
    assert result["location_label"] == "tatstrasse"
    assert result["other_scene_candidates"] == []
    assert {row["name"]: row["role"] for row in result["excluded_location_context"]} == {
        "nebenstrasse": "response"
    }


def test_road_coming_from_is_excluded_as_travel_origin():
    result = Gazetteer([
        road("Deichtorplatz", [(0, 0), (200, 0)]),
        road("Oberbaumbrücke", [(-200, 0), (0, 0)]),
        road("Amsinckstraße", [(100, -100), (100, 100)]),
    ]).locate(
        "Unfallort: Hamburg-Altstadt, Deichtorplatz. Die Fußgänger querten den Deichtorplatz "
        "zwischen zwei Grünflächen der Amsinckstraße. Ein Taxi querte von der Straße "
        "Oberbaumbrücke kommend den Deichtorplatz. Dabei kollidierte es mit zwei Fußgängern.",
        title="Zwei Fußgänger bei Verkehrsunfall verletzt",
        district="Altstadt",
    )
    assert result["geocode_candidates"] == ["deichtorplatz"]
    assert {row["name"]: row["role"] for row in result["excluded_location_context"]} == {
        "oberbaumbrücke": "travel_origin"
    }
    assert not result["other_scene_candidates"]


def test_online_police_prevention_advice_is_a_non_incident():
    result = Gazetteer([]).locate(
        "Die Polizei eröffnet einen digitalen Vortragsraum mit Tipps.",
        title="Kriminalpolizeiliche Beratung jetzt auch online",
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "non_incident_report"


def test_arrest_and_seizure_headings_do_not_turn_operation_sites_into_crime_points():
    gaz = Gazetteer([road("Veringstraße", [(0, 0), (800, 0)])])
    for title, narrative in (
        (
            "Polizei verhaftet mutmaßliche Einbrecher",
            "Die Verdächtigen sollen Einbrüche in anderen Stadtteilen begangen haben.",
        ),
        (
            "Sicherstellung von Pyrotechnik",
            "Bei einer Durchsuchung der Wohnanschrift wurden Gegenstände sichergestellt.",
        ),
    ):
        result = gaz.locate(
            f"Zeit: 06.03.2026, 15:26 Uhr Ort: Hamburg-Wilhelmsburg, "
            f"Veringstraße. {narrative}",
            title=title,
        )
        assert result["coordinates"] is None
        assert result["geocode_method"] == "operation_locations_only"

    incident = gaz.locate(
        "Tatzeit: 06.03.2026, 15:26 Uhr Tatort: Hamburg-Wilhelmsburg, "
        "Veringstraße. Dort griff ein Mann einen Passanten an.",
        title="Polizei verhaftet Tatverdächtigen nach Angriff",
    )
    assert incident["coordinates"] is not None


def test_operation_heading_district_is_not_exported_as_an_incident_location():
    reports = [
        dict(
            id="arrest", url="https://example.test/arrest",
            title="Polizei verhaftet mutmaßliche Einbrecher",
            published="2026-03-06T15:51:00", district="Wilhelmsburg",
            body="Zeit: 14.01.2026, 15:26 Uhr Ort: Hamburg-Wilhelmsburg, Veringstraße. "
            "Die beiden wurden hier verhaftet; die Einbrüche geschahen in Ottensen und Stellingen.",
            sha256="a" * 64, revision=1, http_status=200, error=None,
        ),
        dict(
            id="search", url="https://example.test/search",
            title="Sicherstellung von pyrotechnischen Gegenständen",
            published="2026-03-16T16:56:00", district="Bramfeld",
            body="Zeit: 13.03.2026, 07:15 Uhr Ort: Hamburg-Bramfeld, Baumstraße. "
            "Die Polizei durchsuchte dort eine Wohnung; der frühere Tatort ist unbekannt.",
            sha256="b" * 64, revision=1, http_status=200, error=None,
        ),
        dict(
            id="scene", url="https://example.test/scene",
            title="Polizei verhaftet Tatverdächtigen nach Einbruch",
            published="2026-03-17T09:00:00", district="Wilhelmsburg",
            body="Tatzeit: 16.03.2026, 22:00 Uhr Tatort: Hamburg-Wilhelmsburg, "
            "Veringstraße. Dort wurde in eine Wohnung eingebrochen.",
            sha256="c" * 64, revision=1, http_status=200, error=None,
        ),
    ]
    db = normalized_event_db(reports)
    try:
        events = {row["id"]: row for row in events_from_db(
            db,
            Gazetteer([road("Veringstraße", [(0, 0), (100, 0)]),
                       road("Baumstraße", [(200, 0), (300, 0)])]),
        )}
    finally:
        db.close()
    for event in (events["arrest"], events["search"]):
        assert event["geocode_method"] == "operation_locations_only"
        assert event["coordinates"] is None
        assert event["district"] == ""
        assert event["location_label"] == ""
    assert events["scene"]["district"] == "Wilhelmsburg"
    assert events["scene"]["location_label"] == "veringstrasse"


def test_source_first_scene_review_can_override_a_rule_single_scene_result():
    body = (
        "Tatort: Hamburg-Test, Hauptstraße. In der Hauptstraße wurde ein Mann beraubt. "
        "Später durchsuchte die Polizei eine Wohnung in Hamburg-Nebenstadt."
    )
    report = dict(
        id="source-first", url="https://example.test/source-first",
        title="Festnahme nach einem Raub", published="2026-03-06T15:51:00",
        district="Test", body=body, sha256="a" * 64, revision=1,
        http_status=200, error=None,
    )
    decision = {
        "id": "source-first", "source_sha256": "a" * 64,
        "scenes": [
            {
                "scene_id": "source-first:1", "label": "Hauptstraße robbery",
                "role": "incident", "location_precision": "unknown",
                "geocode_method": "llm_reviewed_unlocated_scene",
                "primary_for_count": False, "case_relation": "independent_case",
                "minimum_incidents": 1,
                "evidence_quote": "In der Hauptstraße wurde ein Mann beraubt.",
            },
            {
                "scene_id": "source-first:2", "label": "Nebenstadt apartment search",
                "role": "search", "location_precision": "unknown",
                "geocode_method": "llm_reviewed_unlocated_search",
                "primary_for_count": False,
                "case_relation": "search_arrest_operation",
                "evidence_quote": (
                    "Später durchsuchte die Polizei eine Wohnung in Hamburg-Nebenstadt."
                ),
            },
        ],
    }
    db = normalized_event_db([report])
    try:
        event = events_from_db(
            db, Gazetteer([]), scene_decisions={"source-first": decision},
        )[0]
    finally:
        db.close()
    assert event["geocode_method"] == "multiple_official_scenes"
    assert [scene["role"] for scene in event["scene_locations"]] == ["incident", "search"]
    assert event["coordinates"] is None
    assert event["district"] == ""
    assert event["location_label"] == ""


def test_rule_flag_does_not_create_an_unreviewed_semantic_scene_inventory():
    report = dict(
        id="rule-flag", url="https://example.test/rule-flag",
        title="Zwei Vorfälle", published="2026-03-06T15:51:00", district="Test",
        body=(
            "Tatorte: a) Hamburg-Test, Hauptstraße b) Hamburg-Test, Nebenstraße. "
            "a) Ein Mann wurde beraubt. b) Eine Frau wurde beraubt."
        ),
        sha256="b" * 64, revision=1, http_status=200, error=None,
    )
    db = normalized_event_db([report])
    try:
        event = events_from_db(db, Gazetteer([]))[0]
    finally:
        db.close()
    assert event["geocode_method"] == "multiple_official_scenes"
    assert event["scene_review_required"] is True
    assert "scene_locations" not in event


def test_corridor_heading_is_not_exported_as_one_administrative_district():
    report = dict(
        id="corridor", url="https://example.test/corridor",
        title="Verkehrshinweis für das Wochenende",
        published="2026-03-06T15:51:00",
        district="Stellingen bis Hamburg-Heimfeld",
        body=(
            "Die Autobahn wird zwischen den Anschlussstellen Stellingen und Heimfeld "
            "für Bauarbeiten gesperrt."
        ),
        sha256="c" * 64, revision=1, http_status=200, error=None,
    )
    db = normalized_event_db([report])
    try:
        event = events_from_db(db, Gazetteer([]))[0]
    finally:
        db.close()
    assert event["geocode_method"] == "non_incident_report"
    assert event["district"] == ""
    assert event["location_label"] == "Stellingen bis Hamburg-Heimfeld"


def test_named_forest_assault_in_arrest_followups_keeps_area_without_a_point():
    gaz = Gazetteer([])
    first = gaz.locate(
        "Zeit: 19.06.2026 und 27.06.2026 Ort: Hamburg-Waldort, Waldorter Wald und "
        "Bahnhof Fernstadt. Das Opfer hielt sich im Waldorter Wald auf. Dort stach "
        "der Täter mit einem Messer auf ihn ein. Der Verdächtige wurde später "
        "am Bahnhof Fernstadt verhaftet.",
        title="Eine Verhaftung nach versuchtem Tötungsdelikt in Hamburg-Waldort",
        district="Waldort",
    )
    followup = gaz.locate(
        "Zeit: 19.06.2026 Ort: Hamburg-Waldort, Waldorter Wald. Nachdem es zu einem "
        "versuchten Tötungsdelikt gekommen war, wurde ein zweiter Verdächtiger "
        "anderswo verhaftet. Dieser soll sich zur Tatzeit ebenfalls in dem Wald "
        "aufgehalten haben und gemeinschaftlich auf ihr Opfer eingewirkt haben.",
        title="Weitere Verhaftung nach versuchtem Tötungsdelikt in Hamburg-Waldort",
        district="Waldort",
    )
    for result in (first, followup):
        assert result["coordinates"] is None
        assert result["location_precision"] == "district"
        assert result["location_label"] == "Waldorter Wald"
        assert result["geocode_candidates"] == ["waldorter wald"]
        assert result["geocode_method"] == "named_area_geometry_review"

    arrest_only = gaz.locate(
        "Zeit: 19.06.2026 Ort: Hamburg-Waldort, Waldorter Wald. "
        "Die Polizei verhaftete dort einen Tatverdächtigen; der Tatort ist unbekannt.",
        title="Verhaftung nach versuchtem Tötungsdelikt in Hamburg-Waldort",
        district="Waldort",
    )
    assert arrest_only["geocode_method"] == "operation_locations_only"
    assert arrest_only["location_label"] == ""


@pytest.mark.parametrize(
    "scene",
    [
        "Der Arbeiter wurde in einem Industrieunternehmen tödlich verletzt.",
        "Ein Bewohner wurde in einer Wohnunterkunft mit einem Messer verletzt.",
        "Zwei Männer stiegen aus einer Parkbucht und griffen einen Passanten an.",
        "Die Täter waren zuvor zu ihm ins Auto gestiegen und bedrohten ihn.",
        "Auf einer Grünfläche neben einem Gebäude wurde eine Person angegriffen.",
        "In der Verkaufsfiliale eines Händlers wurden Waren betrügerisch erworben.",
        "Eine Wohnung in einem Mehrfamilienhaus geriet in Brand.",
        "Ein Unbekannter ist in eine Wohnung eingebrochen.",
        "Ein Zeuge beobachtete das Treffen zweier Fahrzeuge und eine verdächtige Übergabe.",
    ],
)
def test_long_street_with_unnamed_indoor_or_vehicle_scene_has_no_midpoint(scene):
    result = Gazetteer([road("Luisenweg", [(0, 0), (900, 0)])]).locate(
        f"Tatzeit: 10.03.2026, 14:50 Uhr Tatort: Hamburg-Hamm, Luisenweg. {scene}"
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "long_or_ambiguous_street_review"
    assert result["candidate_road_geometry"]


def test_immediately_after_named_crossing_is_an_approximate_junction():
    gaz = Gazetteer([
        road("Habichtstraße", [(0, 0), (1100, 0)]),
        road("Lämmersieth", [(900, -100), (900, 100)]),
    ])
    result = gaz.locate(
        "Unfallzeit: 20.03.2026, 14:53 Uhr Unfallort: Hamburg-Barmbek-Nord, "
        "Habichtstraße. Der Fahrer befuhr die Habichtstraße in Richtung Wandsbek. "
        "Unmittelbar hinter der Kreuzung Lämmersieth bog er nach links ab. "
        "Dabei kollidierte sein Pkw mit einem Motorrad."
    )
    assert result["geocode_method"] == "named_street_intersection"
    assert result["location_precision"] == "street"
    assert result["location_extent_m"] >= 75
    assert result["coordinates"] is not None


@pytest.mark.parametrize(
    ("direction", "expected_y"),
    [("nördlichen", 320), ("südlichen", 0)],
)
def test_fixed_crash_at_qualified_crossing_refines_official_road(direction, expected_y):
    gaz = Gazetteer([
        road("Schlenzigstraße", [(0, -40), (0, 360)]),
        road("Stenzelring", [(-80, 0), (80, 0)]),
        road("Stenzelring", [(-80, 320), (80, 320)]),
    ])
    result = gaz.locate(
        "Tatzeit: 17.02.2026, 19:35 Uhr Tatort: Hamburg-Wilhelmsburg, "
        "Schlenzigstraße. Zwei Autos bogen vom südlichen Teil des Stenzelrings "
        "in die Schlenzigstraße ab. Mutmaßlich aufgrund hoher Geschwindigkeit "
        f"verlor der Fahrer in Höhe des {direction} Stenzelrings die Kontrolle "
        "über sein Fahrzeug und kam nach links von der Fahrbahn ab.",
        title="Zeugenaufruf nach mutmaßlichem Kraftfahrzeugrennen und Unfallflucht",
    )
    assert result["geocode_method"] == "named_street_intersection"
    assert result["location_precision"] == "street"
    assert result["location_extent_m"] == 100
    point = transform(TO_METRIC, Point(result["coordinates"]))
    assert point.distance(Point(X, Y + expected_y)) < 1
    assert {item["name"] for item in result["geocode_evidence"]} == {
        "schlenzigstrasse", "stenzelrings",
    }


def test_qualified_crossing_without_two_distinct_junctions_stays_unlocated():
    gaz = Gazetteer([
        road("Schlenzigstraße", [(0, -40), (0, 360)]),
        road("Stenzelring", [(-80, 0), (80, 0)]),
    ])
    result = gaz.locate(
        "Tatort: Hamburg-Wilhelmsburg, Schlenzigstraße. Der Wagen verlor in Höhe "
        "des nördlichen Stenzelrings die Kontrolle und kam von der Fahrbahn ab.",
        title="Unfall auf der Schlenzigstraße",
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "junction_geometry_review"


def test_police_stop_after_moving_blue_light_offence_is_not_the_crime_point():
    gaz = Gazetteer([
        road("Schiffbeker Weg", [(0, 0), (500, 0)]),
        road("Elfsaal", [(450, -100), (450, 100)]),
    ])
    result = gaz.locate(
        "Tatzeit: 24.02.2026, 17:11 Uhr Tatort: Hamburg-Jenfeld, Schiffbeker Weg. "
        "Der Fahrer nutzte unerlaubt ein Blaulicht auf der Bundesautobahn (BAB) 1 "
        "und nötigte dort andere Fahrer. Die Polizisten hielten das Auto wenig "
        "später im Bereich Schiffbeker Weg, Ecke Elfsaal an.",
        title="Unerlaubt mit Blaulicht unterwegs - Polizei stoppt Autofahrer",
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "moving_scene_review"

    fixed_scene = gaz.locate(
        "Tatort: Hamburg-Jenfeld, Schiffbeker Weg. Dort beschädigte ein Fahrer "
        "ein geparktes Auto. Später hielt die Polizei ihn auf der BAB 1 an.",
        title="Autofahrer beschädigt geparktes Auto",
    )
    assert fixed_scene["coordinates"] is not None


def test_honorary_police_appointment_is_not_an_unlocated_incident():
    result = Gazetteer([]).locate(
        "Bei einem Jahresempfang wurde ein Chormitglied ausgezeichnet.",
        title="Erster Vorsitzender des Polizeichors zum Ehrenkommissar ernannt",
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "non_incident_report"


@pytest.mark.parametrize(
    "title",
    [
        "Mehr Sicherheit: Alkoholkonsumverbotszone deutlich ausgeweitet",
        '"sicher.mobil.leben" - Ergebnisse einer bundesweiten Verkehrssicherheitsaktion',
        "Kinder-HIT-Tag von Polizei und Feuerwehr",
        "Die Lange Nacht der Museen und Einweihung einer Ausstellung",
    ],
)
def test_policy_and_nationwide_safety_action_are_non_incidents(title):
    result = Gazetteer([road("Teststraße", [(0, 0), (100, 0)])]).locate(
        "Bei einem Pressetermin in der Teststraße wurden Ergebnisse vorgestellt.",
        title=title,
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "non_incident_report"


def test_nationwide_control_results_with_many_criminal_cases_are_an_unlocated_summary():
    result = Gazetteer([road("Teststraße", [(0, 0), (100, 0)])]).locate(
        "Zeit: 28.04.2026, ab 07:00 Uhr; Ort: Bundesgebiet. Bei stationären und "
        "mobilen Kontrollen wurden in Hamburg 33 Strafverfahren unter anderem wegen "
        "Fahrens ohne Fahrerlaubnis und Trunkenheit im Straßenverkehr eingeleitet.",
        title='"sicher.mobil.leben" - Ergebnisse einer bundesweiten '
        "Verkehrssicherheitsaktion",
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "multi_event_summary"


@pytest.mark.parametrize(
    "title",
    [
        "Polizei und Staatsanwaltschaft starten Gemeinsame Eingangs- und Bearbeitungsstelle",
        'Aufruf zur Teilnahme an der "Befragung zu Sicherheit und Kriminalität in Deutschland"',
        "Motorradsaison: Informationstag der Polizei an einem Konzerthaus",
        "Frühjahrstagung der Arbeitsgemeinschaft der Polizeipräsidentinnen und Polizeipräsidenten",
        "Hinweise der Polizei zum Wochenende anlässlich des Hafengeburtstags",
        'Taufe des hybriden Polizeiboots "Testboot" beim Hafengeburtstag',
        "Schiffstaufe: Weiteres hybrides Polizeiboot für den Hafen",
        "Peterwagen fahren künftig dauerhaft mit Blaulicht",
    ],
)
def test_administration_surveys_ceremonies_and_policy_are_non_incidents(title):
    result = Gazetteer([road("Weitblick", [(0, 0), (100, 0)])]).locate(
        "Mit Weitblick wird das Vorhaben umgesetzt. Der Termin ist in der Teststraße.",
        title=title,
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "non_incident_report"


def test_multi_site_joint_control_is_a_summary_not_a_crime_point():
    result = Gazetteer([road("Kontrollweg", [(0, 0), (900, 0)])]).locate(
        "Ort: Hamburg-Mitte, Kontrollweg und Innenstadt. Einsatzkräfte führten "
        "stationäre und mobile Verkehrskontrollen durch.",
        title="Verbundeinsatz zur Überprüfung von Sozialleistungsbetrug",
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "multi_event_summary"


def test_official_generic_street_name_is_kept_but_ordinary_travel_word_is_not():
    gaz = Gazetteer(
        [
            road("Schulweg", [(0, 0), (100, 0)]),
            road("Heimweg", [(500, 0), (600, 0)]),
        ]
    )
    official = gaz.locate(
        "Tatort: Hamburg-Mitte, Schulweg. Dort wurde eine Scheibe beschädigt.",
        title="Zeugenaufruf nach Sachbeschädigung",
    )
    assert official["coordinates"] is not None
    assert official["geocode_candidates"] == ["schulweg"]
    ordinary = gaz.locate("Ein Senior befand sich auf dem Heimweg, als er angegriffen wurde.")
    assert ordinary["coordinates"] is None
    assert ordinary["geocode_candidates"] == []


def test_named_bus_stop_height_is_not_treated_as_a_road_intersection():
    gaz = Gazetteer(
        [
            road("Kieler Straße", [(-100, 0), (100, 0)]),
            road("Wördemanns Weg", [(0, -100), (0, 100)]),
        ]
    )
    result = gaz.locate(
        'Unfallort: Hamburg-Stellingen, Kieler Straße, in Höhe Bushaltestelle "Wördemanns Weg". '
        "Dort kollidierte ein Auto mit einem Fußgänger.",
        title="Zeugenaufruf nach Verkehrsunfall",
        district="Stellingen",
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "named_transit_stop_review"
    assert result["location_label"] == "kieler strasse / bushaltestelle wördemanns weg"


def test_named_bus_stop_at_official_junction_is_kept_as_source_evidence_without_a_point():
    gaz = Gazetteer(
        [
            road("Straßburger Straße", [(-100, 0), (100, 0)]),
            road("Nordschleswiger Straße", [(0, -100), (0, 100)]),
        ],
        places={
            "type": "FeatureCollection",
            "features": [place(
                "U-Straßburger Straße", kind="station", ident="osm/node/stop", dx=60,
            )],
        },
    )
    result = gaz.locate(
        "Tatort: Hamburg-Dulsberg, Straßburger Straße/Nordschleswiger Straße "
        "(Bushaltestelle). Der Geschädigte hielt sich an der Bushaltestelle "
        "\"U-Straßburger Straße\" auf, als er angegriffen wurde.",
        title="Zeugenaufruf nach gefährlicher Körperverletzung",
        district="Dulsberg",
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "named_transit_stop_review"
    assert result["location_label"] == (
        "strassburger strasse / nordschleswiger strasse / "
        "bushaltestelle u-strassburger strasse"
    )
    assert result["geocode_candidates"] == [
        "nordschleswiger strasse", "strassburger strasse", "u-strassburger strasse",
    ]
    assert [row["kind"] for row in result["geocode_evidence"]] == [
        "street", "street", "source_named_stop",
    ]
    assert result["location_object_ids"] == []


@pytest.mark.parametrize(
    "collision",
    [
        "Dabei kam es zu einer Kollision mit einem Radfahrer.",
        "Aus bislang ungeklärter Ursache kam es zu einer Kollision mit einem Radfahrer.",
    ],
)
def test_turn_onto_named_road_before_collision_refines_official_long_road(collision):
    gaz = Gazetteer(
        [
            road("Mainstraße", [(-100, 0), (100, 0)]),
            road("Querweg", [(0, -100), (0, 100)]),
        ]
    )
    result = gaz.locate(
        "Unfallort: Hamburg-Mitte, Mainstraße. Der Lkw befuhr den Querweg und wollte "
        f"weiter auf die Mainstraße fahren. {collision}",
        title="Zeugenaufruf nach Verkehrsunfall",
    )
    assert result["geocode_method"] == "named_street_intersection"
    assert set(result["geocode_candidates"]) == {"mainstrasse", "querweg"}


def test_explicit_junction_is_retained_when_collision_is_in_next_anaphoric_sentence():
    gaz = Gazetteer(
        [
            road("Mainstraße", [(-100, 0), (100, 0)]),
            road("Brückenweg", [(0, -100), (0, 100)]),
        ]
    )
    result = gaz.locate(
        "Tatort: Hamburg-Mitte, Mainstraße. Im Einmündungsbereich Brückenweg / "
        "Mainstraße wechselte der Fahrer den Fahrstreifen. Hierbei kollidierte er mit "
        "einem Lastwagen.",
        title="Ermittlungen nach Verkehrsunfallflucht",
    )
    assert result["geocode_method"] == "named_street_intersection"
    assert set(result["geocode_candidates"]) == {"mainstrasse", "brückenweg"}


def test_later_reported_road_section_refines_heading_or_stays_under_review():
    complete = Gazetteer(
        [
            road("Hauptdeich", [(-100, 0), (700, 0)]),
            road("Westweg", [(0, -100), (0, 100)]),
            road("Ostweg", [(500, -100), (500, 100)]),
        ]
    ).locate(
        "Unfallort: Hamburg-Mitte, Hauptdeich. Im Bereich zwischen dem Westweg und "
        "dem Ostweg stieß ein Transporter mit einem Bus zusammen.",
        title="Zeugenaufruf nach Verkehrsunfall",
    )
    assert complete["geocode_method"] == "reported_street_section"
    assert complete["location_extent_m"] == 500

    incomplete = Gazetteer(
        [
            road("Hauptdeich", [(-100, 0), (700, 0)]),
            road("Westweg", [(0, -100), (0, 100)]),
        ]
    ).locate(
        "Unfallort: Hamburg-Mitte, Hauptdeich. Im Bereich zwischen dem Westweg und "
        "dem nicht erfassten Fährweg stieß ein Transporter mit einem Bus zusammen.",
        title="Zeugenaufruf nach Verkehrsunfall",
    )
    assert incomplete["coordinates"] is None
    assert incomplete["geocode_method"] == "street_section_review"

    source_only = Gazetteer(
        [
            road("Hauptdeich", [(-100, 0), (700, 0)]),
            road("Westdamm", [(0, -100), (0, 100)]),
            road("Neuer Fährweg", [(500, -100), (500, 100)]),
        ]
    ).locate(
        "Unfallort: Hamburg-Mitte, Hauptdeich. Im Bereich zwischen dem Westdamm und "
        "dem Neuenfelder Fährweg stieß ein Transporter mit einem Bus zusammen.",
        title="Zeugenaufruf nach Verkehrsunfall",
    )
    assert source_only["coordinates"] is None
    assert source_only["geocode_method"] == "street_section_review"
    assert source_only["location_label"] == (
        "hauptdeich (zwischen westdamm / neuenfelder fährweg)"
    )
    assert set(source_only["geocode_candidates"]) == {
        "hauptdeich", "westdamm", "neuenfelder fährweg",
    }
    assert "neuer fährweg" not in source_only["geocode_candidates"]
    assert any(
        row == {
            "name": "neuenfelder fährweg", "kind": "source_named_street",
            "role": "section_boundary", "sentence_index": 1,
        }
        for row in source_only["geocode_evidence"]
    )


def test_attack_inside_moving_s_bahn_is_not_mapped_to_exit_station():
    result = Gazetteer([road("Jungfernstieg", [(0, 0), (330, 0)])]).locate(
        "Tatort: Hamburg-Neustadt, Jungfernstieg, S-Bahn (S3). Zwei Menschen wurden "
        "in einer S-Bahn kurz vor der Haltestelle beleidigt und geschlagen. Sie verließen "
        "die S-Bahn an der Station Jungfernstieg; der Angreifer blieb im Zug.",
        title="Zeugenaufruf nach Hasskriminalität",
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "moving_scene_review"


def test_same_named_stop_and_official_road_are_not_two_scenes():
    stop = place("Straßburger Straße", kind="station", ident="osm/node/stop")
    gaz = Gazetteer(
        [
            road("Straßburger Straße", [(-100, 0), (100, 0)]),
            road("Nordweg", [(0, -100), (0, 100)]),
        ],
        places={"type": "FeatureCollection", "features": [stop]},
    )
    result = gaz.locate(
        "Tatort: Hamburg-Dulsberg, Straßburger Straße/Nordweg. An der Haltestelle "
        "Straßburger Straße wurde ein Mann angegriffen.",
        title="Zeugenaufruf nach Körperverletzung",
    )
    assert result["geocode_method"] == "named_street_intersection"
    assert result["other_scene_candidates"] == []


def test_closed_missing_person_search_with_no_crime_evidence_is_not_an_incident():
    result = Gazetteer([road("Teststraße", [(0, 0), (100, 0)])]).locate(
        "Ort: Hamburg-Mitte, Teststraße. Es liegen keine Hinweise auf Straftaten vor.",
        title="Erledigung der Öffentlichkeitsfahndung nach einer Frau",
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "non_incident_report"


def test_longer_compound_road_name_suppresses_embedded_short_name():
    result = Gazetteer([
        road("Henry-Schütz-Allee", [(0, 0), (100, 0)]),
        road("Allee", [(1000, 0), (1100, 0)]),
    ]).locate(
        "Tatort: Hamburg-Langenhorn, Henry-Schütz-Allee. Dort wurde ein Fenster beschädigt."
    )
    assert result["geocode_candidates"] == ["henry-schütz-allee"]


@pytest.mark.parametrize(
    ("body", "expected_method"),
    [
        (
            "Tatort: Hamburg-Test, Hauptstraße. Die Beteiligten trafen sich an der Ecke "
            "Hauptstraße/Querweg. Danach führte ihn der Mann zu einem nahegelegenen Feldweg. "
            "Dort schlugen mehrere Personen ihn.",
            "unnamed_area_review",
        ),
        (
            "Unfallort: Hamburg-Test, Hauptstraße. Der Arbeiter wurde auf einem Seeschiff "
             "am bordeigenen Kran eingeklemmt.", "unnamed_area_review"),
        (
            "Feststellzeit: 10.06.2026, 10:00 Uhr Ort: Hamburg-Test, Hauptstraße. "
             "Ein Mann wurde dort leblos aufgefunden. Es gilt zu klären, ob der Auffindeort "
             "auch der eigentliche Tatort ist.", "explicitly_unlocated_scene"),
    ],
)
def test_offroad_and_uncertain_discovery_scenes_do_not_get_road_points(body, expected_method):
    gaz = Gazetteer([
        road("Hauptstraße", [(0, 0), (1000, 0)]),
        road("Querweg", [(300, -100), (300, 100)]),
    ])
    result = gaz.locate(body, district="Test")
    assert result["coordinates"] is None
    assert result["geocode_method"] == expected_method


def test_unnamed_skatepark_scene_demotes_heading_road_used_only_as_escape_direction():
    result = Gazetteer([road("Randstraße", [(0, 0), (800, 0)])]).locate(
        "Tatort: Hamburg-Test, Randstraße. Im Bereich des Skateparks forderte ein "
        "Unbekannter die Tasche und verletzte den Geschädigten. Der Angreifer flüchtete "
        "aus dem Park in Richtung Randstraße.",
        title="Zeugenaufruf nach versuchtem Raub",
        district="Test",
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "unnamed_area_review"
    assert result["location_label"] == "Unbenannter Skatepark"
    assert result["geocode_candidates"] == []
    assert result["geocode_evidence"] == [{
        "name": "Unbenannter Skatepark", "kind": "source_unnamed_area",
        "role": "primary", "sentence_index": 1,
    }]
    assert result["excluded_location_context"] == [{
        "name": "randstrasse", "role": "direction", "sentence_index": 2,
    }]
    assert "candidate_road_geometry" not in result


@pytest.mark.parametrize(
    "anchor",
    [
        "Auf Höhe der Querstraße kollidierte das Auto mit einem Mast.",
        "Vor der Querstraße querte der Radfahrer die Fahrbahn und kollidierte mit einem Pkw.",
        "Etwa in Höhe der Einmündung Querstraße fuhr das Auto auf ein anderes auf.",
        "Das Auto befuhr die Hauptstraße, bog nach links in die Querstraße ein und kollidierte.",
        "An der Bushaltestelle Querstraße/Hauptstraße verließ sie den Bus, bevor ihr Schmuck entrissen wurde.",
    ],
)
def test_official_road_uses_explicit_narrative_junction_instead_of_road_midpoint(anchor):
    gaz = Gazetteer([
        road("Hauptstraße", [(0, 0), (1000, 0)]),
        road("Querstraße", [(300, -100), (300, 100)]),
    ])
    result = gaz.locate(
        "Unfallort: Hamburg-Test, Hauptstraße. " + anchor,
        title="Zeugenaufruf nach Zusammenstoß", district="Test",
    )
    assert result["geocode_method"] == "named_street_intersection"
    assert transform(TO_METRIC, Point(result["coordinates"])).distance(Point(X + 300, Y)) < 15
    assert result["location_extent_m"] >= 100


def test_rail_underpass_followup_inherits_only_range_and_explicit_case_link():
    reports = [
        dict(id="111", url="https://www.presseportal.de/blaulicht/pm/6337/111",
             title="Zeugenaufruf nach Unfall", published="2026-01-02T10:00:00",
             district="Test", body="Unfallzeit: 02.01.2026, 10:25 Uhr Unfallort: "
             "Hamburg-Test, Hauptstraße. Der Lkw fuhr kurz vor der Bahnunterführung "
             "einen Mann an.", sha256="a" * 64, revision=1, http_status=200, error=None),
        dict(id="222", url="https://www.presseportal.de/blaulicht/pm/6337/222",
             title="Mann verstirbt nach Unfall", published="2026-01-20T10:00:00",
             district="Test", body="Unfallzeit: 02.01.2026, 10:25 Uhr Unfallort: "
             "Hamburg-Test, Hauptstraße. Zum Hintergrund siehe "
             "https://www.presseportal.de/blaulicht/pm/6337/111 . Der Mann starb später.",
             sha256="b" * 64, revision=1, http_status=200, error=None),
    ]
    db = normalized_event_db(reports)
    try:
        events = {e["id"]: e for e in events_from_db(
            db, Gazetteer([road("Hauptstraße", [(0, 0), (1200, 0)])])
        )}
    finally:
        db.close()
    assert all(e["coordinates"] is None for e in events.values())
    assert events["111"]["candidate_road_geometry"]
    assert events["222"]["candidate_road_geometry"]
    assert events["222"]["followup_of_source_id"] == "111"


def test_bounded_section_falls_inside_unique_locality_when_heading_locality_is_invalid():
    area = Polygon([(X - 100, Y - 100), (X + 600, Y - 100),
                    (X + 600, Y + 100), (X - 100, Y + 100)])
    gaz = Gazetteer([
        road("Drosselstraße", [(0, 0), (500, 0)]),
        road("Weststraße", [(0, -100), (0, 100)]),
        road("Oststraße", [(500, -100), (500, 100)]),
    ], localities=[dict(id="north", name="Barmbek-Nord", admin_level="10",
                       geometry=mapping(transform(TO_WGS, area)))])
    result = gaz.locate(
        "Unfallort: Hamburg-Bramfeld-Nord, Drosselstraße "
        "(zwischen Weststraße und Oststraße). Ein Bus kollidierte mit einem Baum.",
        district="Bramfeld-Nord",
    )
    assert result["geocode_method"] == "reported_street_section"
    assert result["reported_location_geometry"]
    assert result["district"] == result["location_scope"] == "Barmbek-Nord"


def test_section_without_identified_main_road_is_not_end_point():
    gaz = Gazetteer(
        [
            road("Anderstraße", [(0, -100), (0, 100)]),
            road("Nebenstraße", [(500, -100), (500, 100)]),
        ]
    )
    result = gaz.locate("Zwischen Anderstraße und Nebenstraße kam es zu einem Raub.")
    assert result["coordinates"] is None
    assert result["geocode_method"] == "street_section_review"


@pytest.mark.parametrize("description", ["zwischen zwei Personen", "zwischen 2:30 Uhr und 2:45 Uhr"])
def test_people_or_time_range_does_not_replace_explicit_junction(description):
    gaz = Gazetteer(
        [
            road("Teststraße", [(-100, 0), (100, 0)]),
            road("Anderstraße", [(0, -100), (0, 100)]),
        ]
    )
    result = gaz.locate(f"An der Ecke Teststraße/Anderstraße kam es {description} zu einem Raub.")
    assert result["geocode_method"] == "named_street_intersection"


def test_station_vicinity_is_not_the_station_node_and_denied_response_site_is_not_a_scene():
    gaz = Gazetteer(
        [road("Berner Heerweg", [(0, 0), (200, 0)]),
         road("Blumenau", [(0, -100), (0, 100)]),
         road("Von-Essen-Straße", [(-100, 0), (100, 0)])],
        places=dict(features=[place("Berne", kind="station")]),
    )
    nearby = gaz.locate(
        "Tatort: Hamburg-Test, Berner Heerweg, U-Bahnhof Berne. "
        "Im Bereich des U-Bahnhofs Berne wurden Passanten angegriffen.",
        title="Zeugenaufruf nach Angriff", district="Test",
    )
    assert nearby["coordinates"] is None
    assert nearby["location_object_ids"] == []
    assert nearby["geocode_method"] == "named_place_area_review"
    denied = gaz.locate(
        "Ort: Hamburg-Test, Blumenau/Von-Essen-Straße. Ein Zeuge meldete Schüsse. "
        "Die Polizei geht davon aus, dass es sich bei dem Einsatzort in Test "
        "nicht um den eigentlichen Tatort handelt.",
        title="Zeugenaufruf nach Schüssen", district="Test",
    )
    assert denied["coordinates"] is None
    assert denied["location_label"] == ""
    assert denied["geocode_method"] == "reported_site_not_scene"


@pytest.mark.parametrize(
    "scene",
    [
        "In einem unbenannten Juweliergeschäft wurde Schmuck geraubt.",
        "Im Geschäftshaus wurde ein Fenster beschädigt.",
        "Im Eingangsbereich eines Geschäftsgebäudes wurde ein Fenster beschädigt.",
        "Im Wohnhaus wurden zwei Fenster durch Schüsse beschädigt.",
        "Ein Auto kollidierte auf der Straße mit einem Fahrrad.",
    ],
)
def test_long_road_does_not_locate_an_unknown_venue_or_collision(scene):
    result = Gazetteer([road("Hauptstraße", [(0, 0), (800, 0)])]).locate(
        "Tatort: Hamburg-Test, Hauptstraße. " + scene,
        title="Zeugenaufruf", district="Test",
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "long_or_ambiguous_street_review"


def test_explicit_corner_and_two_neighbourhood_scenes_keep_distinct_roles():
    gaz = Gazetteer([
        road("Hauptstraße", [(0, 0), (800, 0)]),
        road("Querweg", [(250, -100), (250, 100)]),
        road("Nebenstraße", [(1500, 0), (1600, 0)]),
    ])
    corner = gaz.locate(
        "Tatort: Hamburg-Test, Hauptstraße. Auf einer Bank an der Straßenecke "
        "Hauptstraße/Querweg wurde eine Frau beraubt.",
        title="Raub in Hamburg-Test", district="Test",
    )
    assert corner["geocode_method"] == "named_street_intersection"
    assert corner["coordinates"] is not None
    multiple = gaz.locate(
        "Tatort: Hamburg-Test, Hauptstraße und Hamburg-Ander, Nebenstraße. "
        "Ein Opfer wurde im Auto bedroht, später wurden Gegenstände aus seiner Wohnung geraubt.",
        title="Raub an zwei Orten", district="Test",
    )
    assert multiple["coordinates"] is None
    assert multiple["district"] == ""
    assert multiple["geocode_method"] == "multiple_locations_review"


def test_unresolved_named_corner_keeps_both_roads_without_a_midpoint():
    gaz = Gazetteer([
        road("Hauptstraße", [(0, 0), (800, 0)]),
        road("Querweg", [(250, 200), (250, 300)]),
    ])
    result = gaz.locate(
        "Tatort: Hamburg-Test, Hauptstraße. An der Straßenecke Hauptstraße/Querweg "
        "wurde eine Frau beraubt.", title="Raub in Hamburg-Test", district="Test",
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "junction_geometry_review"
    assert set(result["geocode_candidates"]) == {"hauptstrasse", "querweg"}


def test_station_argument_before_a_different_attack_is_not_a_second_scene():
    gaz = Gazetteer(
        [road("Tatweg", [(0, 0), (200, 0)])],
        places=dict(features=[place("Hauptbahnhof", kind="station", dx=500)]),
    )
    result = gaz.locate(
        "Tatort: Hamburg-Test, Tatweg. Am Hauptbahnhof trafen zwei Personen aufeinander, "
        "mit denen sich eine verbale Auseinandersetzung entwickelte. "
        "Danach führten Täter einen Mann zum Tatweg. Dort schlugen sie ihn. "
        "Zeugen trugen den Verletzten zum Hauptbahnhof und riefen den Rettungsdienst.",
        title="Festnahme nach Körperverletzung", district="Test",
    )
    assert result["location_label"] == "tatweg"
    assert result["other_scene_candidates"] == []


def test_explicit_fatal_accident_update_has_case_link_but_no_new_point():
    reports = [
        dict(id="111", url="https://www.presseportal.de/blaulicht/pm/6337/111",
             title="Radfahrer bei Verkehrsunfall verletzt", published="2026-01-02T10:00:00",
             district="Test", body="Unfallzeit: 02.01.2026, 10:25 Uhr Unfallort: Hamburg-Test, "
             "Teststraße. Ein Radfahrer wurde verletzt.", sha256="a" * 64, revision=1,
             http_status=200, error=None),
        dict(id="222", url="https://www.presseportal.de/blaulicht/pm/6337/222",
             title="Radfahrer verstirbt nach Verkehrsunfall", published="2026-01-20T10:00:00",
             district="Test", body="Unfallzeit: 02.01.2026, 10:25 Uhr Unfallort: Hamburg-Test, "
             "Teststraße. Weitere Informationen: https://www.presseportal.de/blaulicht/pm/6337/111 "
             "Der Mann verstarb später im Krankenhaus.", sha256="b" * 64, revision=1,
             http_status=200, error=None),
    ]
    db = normalized_event_db(reports)
    try:
        events = {e["id"]: e for e in events_from_db(
            db, Gazetteer([road("Teststraße", [(0, 0), (200, 0)])])
        )}
    finally:
        db.close()
    assert events["111"]["coordinates"] is not None
    assert events["222"]["coordinates"] is None
    assert events["222"]["followup_of_source_id"] == "111"
    assert events["222"]["geocode_method"] == "followup_report"


def test_fatal_update_can_link_the_second_case_in_an_original_two_accident_report():
    reports = [
        dict(id="111", url="https://www.presseportal.de/blaulicht/pm/6337/111",
             title="Zwei Verkehrsunfälle mit Verletzten", published="2026-01-02T10:00:00",
             district="Test", body="Unfallzeiten: a) 02.01.2026, 10:10 Uhr, "
             "b) 02.01.2026, 10:25 Uhr. Zwei Menschen wurden verletzt.",
             sha256="a" * 64, revision=1, http_status=200, error=None),
        dict(id="222", url="https://www.presseportal.de/blaulicht/pm/6337/222",
             title="Radfahrer verstirbt nach Verkehrsunfall", published="2026-01-20T10:00:00",
             district="Test", body="Unfallzeit: 02.01.2026, 10:25 Uhr Unfallort: "
             "Hamburg-Test, Teststraße. Zum Fall siehe "
             "https://www.presseportal.de/blaulicht/pm/6337/111 . Der Mann verstarb.",
             sha256="b" * 64, revision=1, http_status=200, error=None),
    ]
    db = normalized_event_db(reports)
    try:
        events = {e["id"]: e for e in events_from_db(
            db, Gazetteer([road("Teststraße", [(0, 0), (200, 0)])])
        )}
    finally:
        db.close()
    assert events["222"]["coordinates"] is None
    assert events["222"]["followup_of_source_id"] == "111"


def test_explicit_source_links_distinguish_pure_mixed_background_and_multiple_cases():
    def report(ident, title, published, body, district="Test"):
        return dict(
            id=ident,
            url=f"https://www.presseportal.de/blaulicht/pm/6337/{ident}",
            title=title,
            published=published,
            district=district,
            body=body,
            sha256=ident[0] * 64,
            revision=1,
            http_status=200,
            error=None,
        )

    reports = [
        report(
            "111", "Zeugenaufruf nach Schussabgabe", "2026-01-01T10:00:00",
            "Tatzeit: 01.01.2026, 10:00 Uhr Tatort: Hamburg-Test, Hauptstraße. "
            "Ein Mann wurde durch eine Schussabgabe verletzt.",
        ),
        report(
            "112", "Zeugenaufruf nach Tötungsdelikt", "2026-01-01T11:00:00",
            "Tatzeit: 01.01.2026, 11:00 Uhr Tatort: Hamburg-Test, Nebenstraße. "
            "Die Mordkommission ermittelt.",
        ),
        report(
            "666", "Vermisstenfahndung nach einer Person", "2026-01-01T12:00:00",
            "Ort: Hamburg-Test. Seit dem Vormittag wird eine Person vermisst.",
        ),
        report(
            "222", "Tataufklärung nach Schussabgabe", "2026-01-02T10:00:00",
            "Tatzeit: 01.01.2026, 10:00 Uhr Tatort: Hamburg-Test, Hauptstraße. "
            "Zum ursprünglichen Fall siehe "
            "https://www.presseportal.de/blaulicht/pm/6337/111 . Ein Tatverdächtiger "
            "wurde zu der Schussabgabe ermittelt.",
        ),
        report(
            "333", "Festnahmen nach Schussabgabe", "2026-01-03T10:00:00",
            "Tatzeit: 01.01.2026, 10:00 Uhr Tatort: Hamburg-Test, Hauptstraße. "
            "Zum ursprünglichen Fall siehe "
            "https://www.presseportal.de/blaulicht/pm/6337/111 . Bei der Durchsuchung "
            "wurde eine weitere Person wegen eines Verstoßes gegen das Waffengesetz "
            "vorläufig festgenommen.",
        ),
        report(
            "444", "Verkehrshinweis für eine Veranstaltung", "2026-01-04T10:00:00",
            "Zum Hintergrund siehe https://www.presseportal.de/blaulicht/pm/6337/111 . "
            "Für den kommenden Sonntag werden Straßen gesperrt.", district="",
        ),
        report(
            "555", "Ermittlungen zu mehreren Sachverhalten", "2026-01-05T10:00:00",
            "Die bisherigen Fälle stehen noch nicht sicher miteinander in Verbindung: "
            "https://www.presseportal.de/blaulicht/pm/6337/111 und "
            "https://www.presseportal.de/blaulicht/pm/6337/112 .",
        ),
        report(
            "777", "Erledigung der Vermisstenfahndung nach einer Person",
            "2026-01-06T10:00:00",
            "Zur ursprünglichen Suche siehe "
            "https://www.presseportal.de/blaulicht/pm/6337/666 . Die Person wurde "
            "wohlbehalten gefunden. Hinweise auf Straftaten liegen nicht vor.",
        ),
    ]
    db = normalized_event_db(reports)
    try:
        events = {event["id"]: event for event in events_from_db(
            db,
            Gazetteer([
                road("Hauptstraße", [(0, 0), (200, 0)]),
                road("Nebenstraße", [(500, 0), (700, 0)]),
            ]),
        )}
    finally:
        db.close()

    assert events["222"]["followup_of_source_id"] == "111"
    assert events["222"]["coordinates"] is None
    assert events["222"]["geocode_method"] == "followup_report"
    assert events["333"]["source_reference_ids"] == ["111"]
    assert "followup_of_source_id" not in events["333"]
    assert events["444"]["source_reference_ids"] == ["111"]
    assert events["555"]["source_reference_ids"] == ["111", "112"]
    assert events["777"]["followup_of_source_id"] == "666"
    assert events["777"]["geocode_method"] == "non_incident_report"
    assert events["777"]["coordinates"] is None


def test_single_official_neighbourhood_without_road_remains_district_only():
    area = Polygon([(X - 100, Y - 100), (X + 100, Y - 100),
                    (X + 100, Y + 100), (X - 100, Y + 100)])
    gaz = Gazetteer([], localities=[dict(
        id="winterhude", name="Winterhude", admin_level="10",
        geometry=mapping(transform(TO_WGS, area)),
    )])
    result = gaz.locate(
        "Tatort: Hamburg-Winterhude. Ein angeblicher Beamter versuchte, Wertsachen "
        "von einem Senior abzuholen.", title="Betrugsversuch", district="",
    )
    assert result["coordinates"] is None
    assert result["district"] == "Winterhude"
    assert result["geocode_method"] == "district_only"


def test_time_after_travel_verb_is_not_collision():
    gaz = Gazetteer(
        [
            road("Teststraße", [(1000, 0), (1100, 0)]),
            road("Anderstraße", [(0, 0), (100, 0)]),
        ]
    )
    result = gaz.locate(
        "Der Mann fuhr gegen 22 Uhr von der Teststraße kommend weiter. "
        "In der Anderstraße kollidierte er mit einem Wagen."
    )
    assert result["geocode_candidates"] == ["anderstrasse"]
