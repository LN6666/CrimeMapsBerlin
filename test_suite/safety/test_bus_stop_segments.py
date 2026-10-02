import copy

import pytest
from shapely.geometry import box

from crimemapsberlin.city_transit_segment import source_track_segment
from crimemapsberlin.geometry_decisions import _derived_geometry
from crimemapsberlin.reviewed_city_map import _scene


def inputs():
    rows = []
    for ident, coordinates in [(1, [[0, 0], [1, 0], [2, 1]]), (2, [[2, 1], [3, 1], [4, 1]])]:
        rows.append({'id': f'osm/way/{ident}', 'names': ['M55'], 'roles': ['road'],
                     'tags': {'highway': 'service'},
                     'geometry': {'type': 'LineString', 'coordinates': coordinates},
                     'transit_member_source_proof': {
                         'schema_version': 1, 'way_id': ident,
                         'line_alias_basis': 'verified_operational_route_path_membership',
                         'memberships': [{'relation_id': 900, 'line': 'M55', 'mode': 'bus'}],
                     }})
    for ident, coordinate in [(8, [3, 1]), (9, [1, 0])]:
        rows.append({'id': f'osm/node/{ident}',
                     'tags': {'public_transport': 'stop_position', 'bus': 'yes'},
                     'geometry': {'type': 'Point', 'coordinates': coordinate}})
    rows.append({'id': 'osm/relation/900', 'names': ['M55'], 'roles': ['transit_route'],
                 'tags': {'type': 'route', 'route': 'bus', 'ref': 'M55'},
                 'geometry': {'type': 'LineString', 'coordinates': [[0, 0], [4, 1]]},
                 'transit_source_proof': {'schema_version': 1, 'complete': True,
                                         'relation_id': 900, 'member_way_ids': [1, 2],
                                         'member_way_count': 2, 'member_sequence': [1, 2],
                                         'member_source_digest': 'a' * 64}})
    request = {'location_id': '1:location:1', 'label': 'source bus ride', 'role': 'background',
               'city_scope': 'in_city', 'evidence_quotes': ['Both people alighted.'],
               'precision': 'route', 'geometry_task': 'checked_transit_route_geometry_required',
               'transit_route': {'mode': 'bus', 'line': 'M55', 'extent': 'source_segment'},
               'transit_review': {'status': 'reviewed_route'}}
    decision = {'verdict': 'resolved', 'method': 'osm_transit_segment',
                'review_note': 'Native bounded road reference; source robbery follows alighting.',
                'osm_object_groups': [['osm/way/1', 'osm/way/2'], ['osm/node/8'], ['osm/node/9']]}
    return decision, request, {r['id']: r for r in rows}


def test_bus_cut_preserves_original_vertices_and_source_direction_without_interpolation():
    _, _, objects = inputs()
    segment = source_track_segment([objects['osm/way/1'], objects['osm/way/2']],
                                   [objects['osm/node/8'], objects['osm/node/9']], line='M55', mode='bus')
    assert list(segment.coords) == [(3, 1), (2, 1), (1, 0)]


def test_geometry_and_scene_preserve_ride_background_and_historical_extent_uncertainty():
    decision, request, objects = inputs()
    derived = _derived_geometry(decision, request, objects, box(-1, -1, 5, 2), 'frankfurt',
                                include_footprint_count_points=False)
    assert derived['source_object_ids'] == ['osm/way/1', 'osm/way/2', 'osm/node/8', 'osm/node/9']
    assert derived['geometry_usage'] == 'source_road_reference_only'
    assert derived['source_road_extent'] == 'native_endpoint_bounded'
    assert derived['complete_transit_line'] is False
    assert derived['actual_transit_extent_known'] is False
    assert 'count_point' not in derived
    scene = _scene(request, {'decision': decision, 'derived_geometry': derived}, {}, {}, None)
    assert scene['role'] == 'background' and scene['primary_for_count'] is False
    assert scene['coordinates'] is None
    assert scene['source_road_extent'] == 'native_endpoint_bounded'
    assert scene['actual_transit_extent_known'] is False
    assert scene['complete_transit_line'] is False


@pytest.mark.parametrize('change', ['platform', 'off_road', 'wrong_mode'])
def test_bus_endpoints_cannot_be_platforms_snapped_points_or_other_mode_stops(change):
    decision, request, objects = inputs()
    endpoint = objects['osm/node/9']
    if change == 'platform':
        endpoint['tags']['public_transport'] = 'platform'
    elif change == 'off_road':
        endpoint['geometry']['coordinates'][1] += 0.000001
    else:
        endpoint['tags'].pop('bus')
        endpoint['tags']['tram'] = 'yes'
    with pytest.raises(ValueError, match='original mode stop'):
        _derived_geometry(decision, request, objects, box(-1, -1, 5, 2), 'frankfurt')


@pytest.mark.parametrize('change', ['construction', 'footway', 'missing_alias', 'wrong_membership', 'missing_complete_relation'])
def test_unchecked_non_operational_or_unrelated_roads_cannot_supply_a_bus_segment(change):
    decision, request, objects = inputs()
    way = objects['osm/way/1']
    if change == 'construction':
        way['tags']['construction:highway'] = 'service'
    elif change == 'footway':
        way['tags']['highway'] = 'footway'
    elif change == 'missing_alias':
        way['names'] = ['Other road']
    elif change == 'wrong_membership':
        way['transit_member_source_proof']['memberships'][0]['line'] = '63'
    else:
        objects['osm/relation/900']['transit_source_proof']['complete'] = False
    with pytest.raises(ValueError, match='operational native road|complete checked source relation'):
        _derived_geometry(decision, request, objects, box(-1, -1, 5, 2), 'frankfurt')


def test_disconnected_bus_path_cannot_fill_a_gap():
    decision, request, objects = inputs()
    objects['osm/way/2']['geometry']['coordinates'][0] = [2.001, 1]
    with pytest.raises(ValueError, match='unbranched connected path'):
        _derived_geometry(decision, request, objects, box(-1, -1, 5, 2), 'frankfurt')


@pytest.mark.parametrize('change', ['full_line', 'unreviewed_route'])
def test_bus_segment_cannot_replace_full_line_or_unreviewed_source_extent(change):
    decision, request, objects = inputs()
    if change == 'full_line':
        request['transit_route']['extent'] = 'full_line'
    else:
        request['transit_review']['status'] = 'not_applicable'
    with pytest.raises(ValueError, match='reviewed source segment|explicit source route review'):
        _derived_geometry(decision, request, objects, box(-1, -1, 5, 2), 'frankfurt')
