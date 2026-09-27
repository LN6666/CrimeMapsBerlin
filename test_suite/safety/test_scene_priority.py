"""Synthetic scene-selection regressions; no source police narratives are copied."""

import pytest
from shapely.geometry import LineString, Point, mapping
from shapely.ops import transform

from crimemapsberlin.geocode import Gazetteer
from crimemapsberlin.spatial import TO_METRIC, TO_WGS


@pytest.fixture
def gazetteer():
    x, y = TO_METRIC(13.4, 52.5)
    streets = []
    for name, dy in (("Teststraße", 0), ("Anderstraße", 700), ("Nebenstraße", 1400)):
        geometry = transform(TO_WGS, LineString([(x, y + dy), (x + 120, y + dy)]))
        streets.append({"name": name, "geometry": mapping(geometry)})
    return Gazetteer(streets)


def assert_test_street_scene(result):
    assert result["coordinates"] is not None
    assert result["geocode_candidates"] == ["teststrasse"]
    assert result["location_selection"] == "first_explicit_incident_scene"
    point = transform(TO_METRIC, Point(result["coordinates"]))
    x, y = TO_METRIC(13.4, 52.5)
    assert point.distance(LineString([(x, y), (x + 120, y)])) < 0.1


def test_arrest_first_in_report_does_not_replace_earlier_burglary_scene(gazetteer):
    result = gazetteer.locate(
        "Die Polizei nahm in der Anderstraße einen Verdächtigen fest. "
        "Zuvor wurde in ein Haus in der Teststraße eingebrochen."
    )
    assert_test_street_scene(result)
    assert any(
        row["name"] == "anderstrasse" and row["role"] == "response" and row["sentence_index"] == 0
        for row in result["excluded_location_context"]
    )


def test_escape_in_same_sentence_is_not_part_of_burglary_scene(gazetteer):
    result = gazetteer.locate(
        "In der Teststraße wurde in eine Wohnung eingebrochen und der Täter flüchtete über die Anderstraße."
    )
    assert_test_street_scene(result)
    assert any(
        row["name"] == "anderstrasse" and row["role"] == "escape"
        for row in result["excluded_location_context"]
    )
    assert not result["other_scene_candidates"]


def test_later_closure_junction_does_not_override_collision_scene(gazetteer):
    result = gazetteer.locate(
        "In der Teststraße kollidierten zwei Autos. "
        "Für die Unfallaufnahme wurde der Kreuzungsbereich "
        "Teststraße/Anderstraße/Nebenstraße gesperrt."
    )
    assert_test_street_scene(result)
    assert not result["other_scene_candidates"]


def test_initial_observed_travel_yields_to_later_collision(gazetteer):
    result = gazetteer.locate(
        "Die Polizei beobachtete einen Wagen auf der Anderstraße. "
        "Später kollidierte er in der Teststraße mit einem anderen Wagen."
    )
    assert_test_street_scene(result)
    assert result["geocode_evidence"][0]["sentence_index"] == 1


def test_actual_attack_during_control_remains_scene(gazetteer):
    result = gazetteer.locate(
        "Bei einer Verkehrskontrolle in der Teststraße wurde ein Polizeibeamter "
        "angegriffen. Anschließend nahmen Einsatzkräfte den Fahrer in der "
        "Anderstraße fest."
    )
    assert_test_street_scene(result)
    assert not any(row["name"] == "teststrasse" for row in result["excluded_location_context"])


def test_distinct_additional_scenes_are_preserved_without_changing_main_scene(gazetteer):
    result = gazetteer.locate(
        "In der Teststraße wurde ein Fenster beschädigt. "
        "Später wurde in der Anderstraße ein Auto beschädigt. "
        "Danach wurde in der Nebenstraße eine Person geschlagen."
    )
    assert_test_street_scene(result)
    assert result["other_scene_candidates"] == [
        {"name": "anderstrasse", "sentence_index": 1},
        {"name": "nebenstrasse", "sentence_index": 2},
    ]


def test_narrative_location_fallback_is_distinguished_from_explicit_scene(gazetteer):
    result = gazetteer.locate("In der Teststraße befand sich eine Person.")
    assert result["coordinates"] is not None
    assert result["geocode_candidates"] == ["teststrasse"]
    assert result["location_selection"] == "narrative_location"


@pytest.mark.parametrize("trace", ["Einschusslöcher", "Graffiti"])
def test_fixed_building_crime_traces_found_by_police_remain_scene(gazetteer, trace):
    result = gazetteer.locate(
        f"Die Polizei stellte in der Teststraße {trace} an einer Geschäftsfassade fest."
    )
    assert_test_street_scene(result)
    assert not any(row["name"] == "teststrasse" for row in result["excluded_location_context"])


def test_injured_person_discovery_does_not_establish_attack_location(gazetteer):
    result = gazetteer.locate(
        "Einsatzkräfte stellten in der Teststraße einen verletzten Mann fest. "
        "Der Ort des Angriffs ist unbekannt."
    )
    assert result["coordinates"] is None
    assert any(
        row["name"] == "teststrasse" and row["role"] == "response"
        for row in result["excluded_location_context"]
    )
