import pytest
from shapely.geometry import box, mapping
from shapely.geometry.base import BaseGeometry

from crimemapsberlin.geometry_decisions import compile_geometry_decisions


def _inputs():
    border = box(6.70, 51.15, 6.90, 51.35)
    identity = {
        "source_id": "source-1", "source_sha256": "a" * 64,
        "decision_sha256": "b" * 64, "location_id": "source-1:location:1",
        "geometry_request_sha256": "c" * 64,
    }
    request = {
        **identity, "precision": "address", "geometry_task": "checked_point_geocode_required",
        "coordinates": None,
    }
    inventory = {
        "city": "dusseldorf", "inventory_digest": "d" * 64,
        "all_current_reviews_supported": False, "geometry_requests": [request],
    }
    index = {
        "city": "dusseldorf", "index_sha256": "e" * 64, "objects": [{
            "id": "osm/way/4", "roles": ["address", "named_object"],
            "geometry": mapping(box(6.769, 51.229, 6.771, 51.231)),
        }],
    }
    envelope = {
        "schema_version": 1, "city": "dusseldorf",
        "inventory_digest": inventory["inventory_digest"],
        "geometry_index_sha256": index["index_sha256"], "decisions": [{
            **identity, "schema_version": 1, "city": "dusseldorf", "verdict": "resolved",
            "method": "osm_polygon", "osm_object_groups": [["osm/way/4"]],
            "review_note": "Select the source polygon without adding a point.",
            "reviewer": "test-reviewer", "reviewed_at": "2026-09-30T10:00:00+09:00",
        }],
    }
    return inventory, index, envelope, border


@pytest.mark.parametrize("precision", ["point", "place", "address", "street"])
def test_selected_source_polygon_never_creates_a_representative_point(monkeypatch, precision):
    inventory, index, decisions, border = _inputs()
    request = inventory["geometry_requests"][0]
    request["precision"] = precision
    request["geometry_task"] = (
        "checked_road_geometry_required" if precision == "street"
        else "checked_point_geocode_required"
    )
    if precision == "street":
        index["objects"][0]["roles"].append("road")
    decisions["decisions"][0].update(
        verdict="resolved", method="osm_polygon", osm_object_groups=[["osm/way/4"]],
    )

    def forbidden(*args, **kwargs):
        pytest.fail("The source polygon method must not create a representative point")

    monkeypatch.setattr(BaseGeometry, "representative_point", forbidden)
    result = compile_geometry_decisions(
        inventory=inventory, geometry_index=index, decision_envelope=decisions,
        border=border,
    )
    derived = result["decisions"][0]["derived_geometry"]
    assert derived["type"] == "Polygon"
    assert derived["geometry"] == index["objects"][0]["geometry"]
    assert not any(key.startswith("count_point") for key in derived)
    assert result["publication_ready"] is False


@pytest.mark.parametrize("precision,task,error", [
    ("street", "checked_road_geometry_required", "checked road objects"),
    ("district", "checked_district_geometry_required", "administrative boundary"),
    ("district", "checked_area_geometry_required", "reviewed precision"),
])
def test_polygon_cannot_use_a_building_as_a_road_or_district(precision, task, error):
    inventory, index, decisions, border = _inputs()
    inventory["geometry_requests"][0].update(precision=precision, geometry_task=task)
    decisions["decisions"][0].update(
        verdict="resolved", method="osm_polygon", osm_object_groups=[["osm/way/4"]],
    )
    with pytest.raises(ValueError, match=error):
        compile_geometry_decisions(
            inventory=inventory, geometry_index=index, decision_envelope=decisions,
            border=border,
        )
