from copy import deepcopy

import pytest

from crimemapsberlin.static_road_references import METHOD, derive_static_road_reference


def inputs():
    decision = {"method": METHOD, "verdict": "resolved", "osm_object_groups": [["path"], ["start"], ["end"]]}
    request = {
        "precision": "street", "geometry_task": "checked_road_geometry_required",
        "coordinates": None, "city_scope": "in_city",
        "transit_review": {"status": "not_applicable"},
    }
    return decision, request


def test_preserves_native_output_and_unknown_static_position():
    decision, request = inputs()
    original = deepcopy(decision)
    native = {
        "type": "LineString", "geometry": {"type": "LineString", "coordinates": [[10, 53], [10.01, 53]]},
        "geometry_sha256": "native-hash", "source_object_ids": ["path", "start", "end"],
        "source_object_groups": original["osm_object_groups"],
    }
    calls = []

    def strict_compiler(value, req, objects, border, city, **kwargs):
        calls.append((value, req, objects, border, city, kwargs))
        return native

    result = derive_static_road_reference(decision, request, {}, None, "hamburg", compile_base=strict_compiler)
    assert decision == original
    assert len(calls) == 1
    assert calls[0][0]["method"] == "osm_road_segment"
    assert calls[0][0]["osm_object_groups"] == original["osm_object_groups"]
    assert calls[0][-1] == {"include_footprint_count_points": False}
    assert result["geometry"] == native["geometry"]
    assert result["source_object_ids"] == native["source_object_ids"]
    assert "geometry_usage" not in native
    assert result["actual_event_position_known"] is False
    assert result["actual_static_scene_extent_known"] is False
    assert result["static_scene_reference"] is True


@pytest.mark.parametrize("change", [
    {"precision": "district"}, {"geometry_task": "checked_point_geocode_required"},
    {"coordinates": [10, 53]}, {"city_scope": "uncertain"},
    {"transit_route": {"line": "112", "mode": "bus"}},
    {"transit_review": {"status": "reviewed_non_transit_route"}},
])
def test_rejects_other_scene_types_before_native_calculation(change):
    decision, request = inputs()
    request.update(change)

    def should_not_run(*args, **kwargs):
        pytest.fail("invalid static scene reached the native compiler")

    with pytest.raises(ValueError, match="static road reference"):
        derive_static_road_reference(decision, request, {}, None, "hamburg", compile_base=should_not_run)


@pytest.mark.parametrize("bad_result", [
    {"type": "Point"},
    {"type": "LineString", "count_point": {"type": "Point"}},
    {"type": "LineString", "count_point_method": "representative_point"},
])
def test_rejects_point_and_count_products(bad_result):
    decision, request = inputs()
    with pytest.raises(ValueError, match="without a count point"):
        derive_static_road_reference(decision, request, {}, None, "hamburg", compile_base=lambda *a, **k: bad_result)


def test_native_range_failure_remains_a_failure():
    decision, request = inputs()

    def disconnected(*args, **kwargs):
        raise ValueError("native endpoint is not shared")

    with pytest.raises(ValueError, match="native endpoint is not shared"):
        derive_static_road_reference(decision, request, {}, None, "hamburg", compile_base=disconnected)
