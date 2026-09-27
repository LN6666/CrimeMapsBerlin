"""Synthetic scene-context regressions; no police bodies or generated city data."""

import pytest
from shapely.geometry import LineString, Point, Polygon, mapping
from shapely.ops import transform

from crimemapsberlin.geocode import Gazetteer
from crimemapsberlin.spatial import TO_METRIC, TO_WGS

X, Y = TO_METRIC(13.4, 52.5)


def road(name, dx=0):
    geometry = transform(TO_WGS, LineString([(X + dx, Y), (X + dx + 100, Y)]))
    return {"name": name, "geometry": mapping(geometry)}


def station(name="Testplatz", dx=1500):
    geometry = mapping(transform(TO_WGS, Point(X + dx, Y)))
    return {
        "type": "Feature",
        "geometry": geometry,
        "location_geometry": geometry,
        "properties": {
            "id": "osm/node/test-station",
            "name": name,
            "kind": "station",
            "aliases": [],
            "geometry_mode": "osm_point",
        },
    }


@pytest.mark.parametrize(
    "location",
    ["Im S- und U-Bahnhof Testplatz", "In der Nähe des S- und U-Bahnhofs Testplatz"],
)
def test_combined_station_context_does_not_use_same_named_street(location):
    gaz = Gazetteer([road("Testplatz")], places={"type": "FeatureCollection", "features": [station()]})
    result = gaz.locate(f"{location} schlug ein Mann einen anderen Mann.")
    assert result["location_precision"] == "place"
    assert result["location_object_ids"] == ["osm/node/test-station"]
    point = transform(TO_METRIC, Point(result["coordinates"]))
    assert point.distance(Point(X + 1500, Y)) < 0.1


def test_dort_collision_refers_to_current_road():
    result = Gazetteer([road("Teststraße")]).locate(
        "Der Fahrer befuhr die Teststraße. Dort fuhr er einen Fußgänger an."
    )
    assert result["location_precision"] == "street"
    assert result["geocode_candidates"] == ["teststrasse"]
    assert result["location_selection"] == "first_explicit_incident_scene"


def test_intervening_stop_prevents_dort_from_referring_to_old_road():
    result = Gazetteer([road("Teststraße"), road("Anderstraße", dx=1500)]).locate(
        "Ein Mann befuhr die Teststraße. "
        "An der Bushaltestelle Anderstraße stieg er aus. Dort schlug er einen Fahrgast."
    )
    assert result["geocode_candidates"] == ["anderstrasse"]
    point = transform(TO_METRIC, Point(result["coordinates"]))
    assert point.distance(Point(X + 1550, Y)) < 1


@pytest.mark.parametrize("witness", ["Passanten", "Polizeikräfte"])
@pytest.mark.parametrize("fire", ["ein Feuer", "Flammen"])
def test_discovered_fire_is_a_fixed_scene(witness, fire):
    result = Gazetteer([road("Teststraße")]).locate(
        f"{witness} stellten in der Teststraße {fire} fest. Die Feuerwehr löschte den Brand."
    )
    assert result["location_precision"] == "street"
    assert result["geocode_candidates"] == ["teststrasse"]
    assert result["location_selection"] == "first_explicit_incident_scene"


@pytest.mark.parametrize(
    "body",
    [
        "Eine verletzte Person wurde in der Teststraße aufgefunden. Der Tatort ist unbekannt.",
        "Passanten fanden in der Teststraße einen verletzten Mann. Wo er verletzt wurde, ist unklar.",
    ],
)
def test_found_injured_person_does_not_establish_attack_location(body):
    result = Gazetteer([road("Teststraße")]).locate(body)
    assert result["coordinates"] is None
    assert result["location_precision"] == "unknown"


def test_attempted_atm_break_in_precedes_escape_and_arrest_locations():
    result = Gazetteer([road("Teststraße"), road("Anderstraße", dx=1500)]).locate(
        "In der Teststraße versuchten zwei Männer einen Geldautomaten aufzubrechen "
        "und flüchteten anschließend in die Anderstraße. Dort wurden sie festgenommen."
    )
    assert result["location_precision"] == "street"
    assert result["geocode_candidates"] == ["teststrasse"]
    assert result["location_selection"] == "first_explicit_incident_scene"


def test_embedded_original_report_retains_genitive_scene_after_arrest_update():
    result = Gazetteer([road("Testplatz"), road("Anderstraße", dx=1500)]).locate(
        "Nachtragsmeldung: Der Verdächtige wurde in der Anderstraße festgenommen. "
        "Erstmeldung: Im Bereich des Testplatzes kam es zu einem Raub."
    )
    assert result["location_precision"] == "street"
    assert result["geocode_candidates"] == ["testplatzes"]
    assert result["location_selection"] == "first_explicit_incident_scene"


def test_ordinal_police_unit_retains_same_sentence_locality_scope():
    boundary = transform(
        TO_WGS,
        Polygon([(X - 100, Y - 100), (X + 200, Y - 100), (X + 200, Y + 100), (X - 100, Y + 100)]),
    )
    gaz = Gazetteer(
        [road("Teststraße"), road("Teststraße", dx=10000)],
        localities=[
            {
                "id": "test-neighbourhood",
                "name": "Testviertel",
                "admin_level": "10",
                "geometry": mapping(boundary),
            }
        ],
    )
    result = gaz.locate(
        "In Testviertel wurden Einsatzkräfte der 32. Einsatzhundertschaft in der Teststraße angegriffen."
    )
    assert result["location_scope"] == "Testviertel"
    assert result["location_precision"] == "street"
    assert result["geocode_evidence"][0]["sentence_index"] == 0
    point = transform(TO_METRIC, Point(result["coordinates"]))
    assert point.distance(Point(X + 50, Y)) < 1


def crossing_road(name, x=50):
    return {
        "name": name,
        "geometry": mapping(transform(TO_WGS, LineString([(X + x, Y - 50), (X + x, Y + 50)]))),
    }


def test_prior_junction_is_retained_when_collision_repeats_only_main_road():
    gaz = Gazetteer([road("Teststraße"), crossing_road("Anderstraße")])
    result = gaz.locate(
        "Ein Kind wollte die Teststraße an der Kreuzung zur Anderstraße überqueren. "
        "Ein Autofahrer befuhr die Teststraße und fuhr das Kind an."
    )
    assert result["geocode_method"] == "named_street_intersection"
    assert set(result["geocode_candidates"]) == {"teststrasse", "anderstrasse"}


def test_previous_crossing_reference_refines_origin_and_collision_road():
    gaz = Gazetteer([road("Teststraße"), crossing_road("Anderstraße")])
    result = gaz.locate(
        "An der Kreuzung zur Anderstraße fuhr ein Wagen über die Ampel. "
        "Zeitgleich fuhr eine Radfahrerin aus der Anderstraße auf die Fahrbahn der Teststraße. "
        "Dort kollidierten die Fahrzeuge."
    )
    assert result["geocode_method"] == "named_street_intersection"
    assert set(result["geocode_candidates"]) == {"teststrasse", "anderstrasse"}
    assert any(
        e["role"] == "junction_anchor" and e["sentence_index"] == 0 for e in result["geocode_evidence"]
    )


def test_collision_clause_keeps_explicit_junction_but_not_other_driver_origin():
    gaz = Gazetteer([road("Teststraße"), crossing_road("Anderstraße"), crossing_road("Nebenstraße", 80)])
    result = gaz.locate(
        "An der Kreuzung Teststraße/Anderstraße bog er ab und kollidierte mit einem Wagen, "
        "der die Teststraße von der Nebenstraße kommend befuhr."
    )
    assert result["geocode_method"] == "named_street_intersection"
    assert set(result["geocode_candidates"]) == {"teststrasse", "anderstrasse"}


def test_junction_before_collision_clause_needs_no_repeated_road_name():
    result = Gazetteer([road("Teststraße"), crossing_road("Anderstraße")]).locate(
        "Ein Fahrer flüchtete vor einer Kontrolle. "
        "Der Fahrer bog an der Kreuzung Teststraße/Anderstraße ab und kollidierte mit einem Auto."
    )
    assert result["geocode_method"] == "named_street_intersection"
    assert set(result["geocode_candidates"]) == {"teststrasse", "anderstrasse"}


def test_turning_collision_uses_previous_road_not_station_destination():
    gaz = Gazetteer([road("Teststraße"), crossing_road("Anderstraße")], places={"features": [station()]})
    result = gaz.locate(
        "Der Fahrer befuhr die Teststraße. Als er an einer Kreuzung in die Anderstraße abbog, "
        "fuhr er ein Kind an, das die Anderstraße in Richtung U-Bahnhof Testplatz überquerte."
    )
    assert result["geocode_method"] == "named_street_intersection"
    assert result["location_object_ids"] == []
    assert set(result["geocode_candidates"]) == {"teststrasse", "anderstrasse"}


def test_found_burning_object_remains_first_scene_of_multi_scene_report():
    result = Gazetteer([road("Teststraße"), road("Anderstraße", 1500)]).locate(
        "Einsatzkräfte fanden in der Teststraße ein brennendes Plakat. "
        "Später wurde in der Anderstraße ein weiteres Plakat angezündet."
    )
    assert result["geocode_candidates"] == ["teststrasse"]
    assert result["location_selection"] == "first_explicit_incident_scene"


def test_dispatch_station_does_not_locate_attack_inside_moving_train():
    result = Gazetteer([], places={"features": [station()]}).locate(
        "Fahrgäste alarmierten die Polizei zum U-Bahnhof Testplatz. "
        "Im Zug sprach ein Mann eine Frau an. Später schlug er sie während der Fahrt."
    )
    assert result["coordinates"] is None
    assert result["geocode_method"] == "moving_scene_review"


def test_sidewalk_approach_does_not_replace_collision_on_other_road():
    result = Gazetteer([road("Teststraße"), road("Anderstraße", 1500)]).locate(
        "Die Kinder waren auf dem Gehweg der Teststraße unterwegs. "
        "Sie betraten die Fahrbahn der Anderstraße und wurden von einem Wagen erfasst."
    )
    assert result["geocode_candidates"] == ["anderstrasse"]
    assert result["location_selection"] == "first_explicit_incident_scene"


def test_hearing_bang_does_not_establish_unnamed_building_location():
    result = Gazetteer([road("Teststraße")]).locate(
        "In einer unbenannten Schule brach ein Feuer aus. "
        "Eine Passantin in der Teststraße hörte einen Knall und alarmierte die Feuerwehr."
    )
    assert result["coordinates"] is None
    assert any(e["role"] == "witness" for e in result["excluded_location_context"])


def test_nearest_dispatch_neighbourhood_scopes_scene_not_earlier_incident():
    def locality(ident, name, dx):
        return {
            "id": ident,
            "name": name,
            "admin_level": "10",
            "geometry": mapping(transform(TO_WGS, Point(X + dx, Y).buffer(150))),
        }

    gaz = Gazetteer(
        [road("Teststraße"), road("Teststraße", 1500)],
        localities=[locality("old", "Altviertel", 0), locality("new", "Neuviertel", 1500)],
    )
    result = gaz.locate(
        "In Altviertel gab es zuvor einen Polizeieinsatz. Einsatzkräfte wurden nach Neuviertel alarmiert. "
        "Auf der Teststraße stürzte ein Fahrer. Danach wurde er in ein Krankenhaus in Altviertel gebracht."
    )
    assert result["coordinates"]
    assert result["location_scope"] == "Neuviertel"
    assert transform(TO_METRIC, Point(result["coordinates"])).distance(Point(X + 1550, Y)) < 1


def test_sidewalk_to_junction_collision_preserves_both_roads():
    result = Gazetteer([road("Teststraße"), crossing_road("Anderstraße")]).locate(
        "Ein Kind war auf dem Gehweg der Teststraße in Richtung Anderstraße unterwegs. "
        "An der Einmündung zur Anderstraße fuhr es auf die Fahrbahn. "
        "Die 61-Jährige fuhr das Kind an."
    )
    assert result["geocode_method"] == "named_street_intersection"
    assert set(result["geocode_candidates"]) == {"teststrasse", "anderstrasse"}


def test_turn_collision_at_named_crossing_refines_previous_main_road():
    result = Gazetteer([road("Teststraße"), crossing_road("Anderstraße")]).locate(
        "Ein Wagen war auf der Teststraße unterwegs. "
        "In Höhe der Anderstraße fuhr er an den Fahrbahnrand und stieß mit einem Wagen zusammen."
    )
    assert result["geocode_method"] == "named_street_intersection"
    assert set(result["geocode_candidates"]) == {"teststrasse", "anderstrasse"}


def test_vehicle_collision_after_control_loss_retains_named_road():
    result = Gazetteer([road("Teststraße")]).locate(
        "Ein 50-jähriger Mann befuhr mit seinem Auto die Teststraße. "
        "Bei einem Überholvorgang verlor er die Kontrolle. Dieses prallte gegen einen Baum."
    )
    assert result["location_selection"] == "first_explicit_incident_scene"
    assert result["geocode_candidates"] == ["teststrasse"]


def test_crossing_two_named_roads_refines_later_collision():
    result = Gazetteer([road("Teststraße"), crossing_road("Anderstraße")]).locate(
        "Ein Wagen befuhr die Teststraße und überquerte dabei die Anderstraße. "
        "Dabei kam es im Kreuzungsbereich zum Zusammenstoß."
    )
    assert result["geocode_method"] == "named_street_intersection"
    assert set(result["geocode_candidates"]) == {"teststrasse", "anderstrasse"}


def test_qualified_stop_name_does_not_become_other_road_scene():
    result = Gazetteer([road("Teststraße"), road("Anderstraße", 1500)]).locate(
        "Eine Frau steuerte ihr Auto in der Teststraße. Kurz hinter der Bushaltestelle Anderstraße Nord "
        "verlor sie die Kontrolle und kollidierte mit einem Auto."
    )
    assert result["geocode_candidates"] == ["teststrasse"]
    assert result["location_selection"] == "first_explicit_incident_scene"


def test_hearing_bang_and_seeing_fire_establishes_physical_scene():
    result = Gazetteer([road("Teststraße")]).locate(
        "Ein Anwohner hörte in der Teststraße einen Knall und sah einen Feuerschein. "
        "Die Feuerwehr löschte Flammen an den dort geparkten Fahrzeugen."
    )
    assert result["coordinates"]
    assert result["location_selection"] == "first_explicit_incident_scene"


def test_first_physical_damage_scene_on_median_precedes_later_fire():
    result = Gazetteer([road("Teststraße"), road("Anderstraße", 1500)]).locate(
        "Polizisten stellten auf dem Mittelstreifen der Teststraße ein mit Farbe besprühtes Plakat fest. "
        "Später wurden in der Anderstraße brennende Plakate gefunden."
    )
    assert result["geocode_candidates"] == ["teststrasse"]


@pytest.mark.parametrize("summary", ["in Altviertel einen Mann fest", "in Altviertel eine Brandstiftung"])
def test_station_boarding_neighbourhood_does_not_replace_incident_summary(summary):
    def locality(ident, name, dx):
        return {
            "id": ident,
            "name": name,
            "admin_level": "10",
            "geometry": mapping(transform(TO_WGS, Point(X + dx, Y).buffer(200))),
        }

    gaz = Gazetteer(
        [road("Teststraße"), road("Teststraße", 1500)],
        places={"features": [station("Neuviertel", dx=1500)]},
        localities=[locality("old", "Altviertel", 0), locality("new", "Neuviertel", 1500)],
    )
    result = gaz.locate(
        f"Polizisten stellten {summary}. Männer stiegen am S-Bahnhof Neuviertel in einen Bus ein. "
        "An der Bushaltestelle Teststraße hielt der Bus. Daraufhin wurde der Fahrer geschlagen."
    )
    assert result["location_scope"] == "Altviertel"
    assert result["coordinates"]
    assert transform(TO_METRIC, Point(result["coordinates"])).distance(Point(X + 50, Y)) < 1


def test_intervening_journey_does_not_force_scene_into_wrong_neighbourhood():
    def locality(ident, name, dx):
        return {
            "id": ident,
            "name": name,
            "admin_level": "10",
            "geometry": mapping(transform(TO_WGS, Point(X + dx, Y).buffer(200))),
        }

    gaz = Gazetteer(
        [road("Teststraße"), road("Anderstraße", 1500)],
        localities=[locality("old", "Altviertel", 0), locality("new", "Neuviertel", 1500)],
    )
    result = gaz.locate(
        "In Altviertel endete die Flucht eines Fahrers. Zuvor fiel er in Neuviertel auf. "
        "Der Fahrer flüchtete durch die Anderstraße. In der Teststraße kollidierte er mit einem Auto."
    )
    assert result["coordinates"]
    assert result["location_scope"] == "Altviertel"


def test_multi_region_search_operation_does_not_scope_old_station_robbery():
    area = mapping(transform(TO_WGS, Point(X, Y).buffer(200)))
    gaz = Gazetteer(
        [],
        places={"features": [station(dx=1500)]},
        localities=[{"id": "old", "name": "Altviertel", "admin_level": "10", "geometry": area}],
    )
    result = gaz.locate(
        "Polizisten vollstreckten sieben Durchsuchungsbeschlüsse in Altviertel. "
        "Die Tatverdächtigen trafen sich zuvor am S-Bahnhof Testplatz mit einem Mann. "
        "Dort wurden ihm Wertgegenstände geraubt und er wurde geschlagen."
    )
    assert result["coordinates"]
    assert result["location_object_ids"] == ["osm/node/test-station"]


def test_explicit_cross_district_pursuit_junction_is_not_clipped_to_origin():
    area = mapping(transform(TO_WGS, Point(X + 2000, Y).buffer(200)))
    gaz = Gazetteer(
        [road("Teststraße"), crossing_road("Anderstraße")],
        localities=[{"id": "old", "name": "Altviertel", "admin_level": "10", "geometry": area}],
    )
    result = gaz.locate(
        "In Altviertel flüchtete ein Fahrer vor der Polizei. "
        "An der Kreuzung Teststraße/Anderstraße kollidierte er mit einem Wagen.",
        district="bezirksübergreifend",
    )
    assert result["geocode_method"] == "named_street_intersection"
    assert set(result["geocode_candidates"]) == {"teststrasse", "anderstrasse"}
