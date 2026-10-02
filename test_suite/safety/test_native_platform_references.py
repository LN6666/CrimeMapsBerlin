import copy
import hashlib
import json

import pytest
from shapely.geometry import box

from crimemapsberlin.native_platform_references import METHOD, native_platform_reference


def digest(v):
    return hashlib.sha256(json.dumps(v, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def inputs():
    objects = {}
    for n, xy in [(1, [10.0, 53.0]), (2, [10.01, 53.01]), (3, [10.02, 53.02])]:
        geo = {"type": "Point", "coordinates": xy}
        objects[f"osm/node/{n}"] = {"id": f"osm/node/{n}", "geometry": geo,
            "geometry_sha256": digest(geo), "roles": ["named_object"],
            "tags": {"name": "Example Stop", "public_transport": "platform"},
            "source_url": f"https://www.openstreetmap.org/node/{n}"}
    decision = {"method": METHOD, "verdict": "resolved",
                "osm_object_groups": [list(objects)]}
    request = {"geometry_task": "checked_point_geocode_required", "precision": "place",
               "city_scope": "in_city", "coordinates": None}
    return decision, request, objects, box(9, 52, 11, 54)


def test_preserves_every_original_coordinate_without_event_or_count_point():
    d, r, objects, border = inputs()
    result = native_platform_reference(d, r, objects, border)
    assert result["geometry"]["coordinates"] == [v["geometry"]["coordinates"] for v in objects.values()]
    assert result["source_object_ids"] == list(objects)
    assert result["native_platform_count"] == 3
    assert result["actual_event_position_known"] is False
    assert result["actual_platform_side_known"] is False
    assert result["coordinates_generated"] is False
    assert not {"count_point", "coordinates", "representative_point"} & result.keys()
    result["geometry"]["coordinates"][0][0] = 99
    assert objects["osm/node/1"]["geometry"]["coordinates"][0] == 10.0


@pytest.mark.parametrize("field,value", [
    ("precision", "district"), ("precision", "point"), ("city_scope", "uncertain"),
    ("coordinates", [10, 53]), ("geometry_task", "checked_road_geometry_required"),
])
def test_rejects_precision_or_event_coordinate_upgrade(field, value):
    d, r, objects, border = inputs(); r[field] = value
    with pytest.raises(ValueError): native_platform_reference(d, r, objects, border)


@pytest.mark.parametrize("groups", [[['osm/node/1']], [['osm/node/1', 'osm/node/1']],
                                     [['osm/node/1'], ['osm/node/2']]])
def test_does_not_choose_single_side_duplicate_id_or_multiple_groups(groups):
    d, r, objects, border = inputs(); d["osm_object_groups"] = groups
    with pytest.raises(ValueError): native_platform_reference(d, r, objects, border)


@pytest.mark.parametrize("change", ["absent", "hash", "different_name", "not_platform",
                                      "wrong_url", "endpoint", "boolean_coordinate"])
def test_rejects_unbound_or_mixed_native_members(change):
    d, r, objects, border = inputs(); node = objects['osm/node/2']
    if change == 'absent': del objects['osm/node/2']
    elif change == 'hash': node['geometry_sha256'] = '0' * 64
    elif change == 'different_name': node['tags']['name'] = 'Other Stop'
    elif change == 'not_platform': node['tags']['public_transport'] = 'stop_position'
    elif change == 'wrong_url': node['source_url'] = 'https://example.com/2'
    elif change == 'endpoint': node['native_road_vertex_source_proof'] = {}
    else: node['geometry']['coordinates'][0] = True; node['geometry_sha256'] = digest(node['geometry'])
    with pytest.raises(ValueError): native_platform_reference(d, r, objects, border)


def test_rejects_platform_outside_city():
    d, r, objects, _ = inputs()
    with pytest.raises(ValueError): native_platform_reference(d, r, objects, box(9, 52, 10.005, 54))


def test_retains_co_located_original_nodes_without_coalescing_or_jitter():
    d, r, objects, border = inputs()
    objects['osm/node/2']['geometry'] = copy.deepcopy(objects['osm/node/1']['geometry'])
    objects['osm/node/2']['geometry_sha256'] = digest(objects['osm/node/2']['geometry'])
    result = native_platform_reference(d, r, objects, border)
    assert result['native_platform_count'] == 3
    assert result['geometry']['coordinates'][0] == result['geometry']['coordinates'][1]
