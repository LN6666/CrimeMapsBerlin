from shapely.geometry import LineString, box, mapping

from crimemapsberlin.berlin_audit_rebuild import _object_groups_for_request


def _line(ident, coordinates):
    return {
        "id": ident,
        "dimension": "line",
        "roles": ["named_object", "road"],
        "tags": {"highway": "residential"},
        "geometry": mapping(LineString(coordinates)),
    }


def test_named_road_is_limited_to_source_named_administrative_area():
    inside = _line("osm/way/inside", [(13.1, 52.4), (13.2, 52.4)])
    outside = _line("osm/way/outside", [(13.4, 52.6), (13.5, 52.6)])
    district = {
        "id": "osm/relation/district",
        "dimension": "polygon",
        "roles": ["named_object", "administrative_boundary"],
        "tags": {"boundary": "administrative", "admin_level": "10"},
        "geometry": mapping(box(13.0, 52.3, 13.3, 52.5)),
    }
    geometry_index = {
        "objects": [inside, outside, district],
        "name_index": {
            "königsweg": [inside["id"], outside["id"]],
            "zehlendorf": [district["id"]],
        },
    }
    request = {
        "location_id": "source:location:1",
        "label": "Königsweg, Zehlendorf",
        "precision": "street",
    }
    candidate = {
        "district": "Steglitz-Zehlendorf",
        "location_label": "Königsweg",
        "geocode_candidates": ["Königsweg"],
        "coordinates": [13.45, 52.6],
    }

    method, groups, _ = _object_groups_for_request(request, candidate, None, geometry_index)

    assert method == "osm_line"
    assert groups == [[inside["id"]]]


def test_named_road_without_area_uses_old_point_only_to_choose_component():
    near_a = _line("osm/way/a", [(13.10, 52.40), (13.11, 52.40)])
    near_b = _line("osm/way/b", [(13.11, 52.40), (13.12, 52.40)])
    far = _line("osm/way/far", [(13.40, 52.60), (13.41, 52.60)])
    geometry_index = {
        "objects": [near_a, near_b, far],
        "name_index": {"testweg": [near_a["id"], near_b["id"], far["id"]]},
    }
    request = {
        "location_id": "source:location:1",
        "label": "Testweg",
        "precision": "street",
    }
    candidate = {
        "district": "",
        "location_label": "Testweg",
        "geocode_candidates": ["Testweg"],
        "coordinates": [13.105, 52.40],
    }

    method, groups, _ = _object_groups_for_request(request, candidate, None, geometry_index)

    assert method == "osm_line"
    assert groups == [[near_a["id"], near_b["id"]]]
