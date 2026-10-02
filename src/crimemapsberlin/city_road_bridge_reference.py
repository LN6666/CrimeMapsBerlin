"""A native bridge bounds a road reference, never a collision/count position."""
from __future__ import annotations

import copy
import re

from shapely.geometry import Polygon, mapping, shape
from shapely.ops import transform

from .city_geometry_index import _digest
from .city_rail_crossing_reference import valid_crossing_way
from .poi_cities import POI_CITY_SPECS
from .spatial import metric_transforms

METHOD = 'osm_road_under_bridge_reference'
PROOF = 'native_bridge_outline_source_proof'
HEX = re.compile(r'[0-9a-f]{64}')


def native_bridge_outline_object(*, source_object, source_cache_sha256, source_metadata, border):
    if set(source_object) != {'id', 'tags', 'geometry', 'node_ids'}:
        raise ValueError('bridge needs its complete original way and node sequence')
    ident = source_object['id']; tags = source_object['tags']; nodes = source_object['node_ids']
    if (not isinstance(ident, str) or not re.fullmatch(r'osm/way/[1-9][0-9]*', ident)
            or not isinstance(tags, dict) or tags.get('man_made') != 'bridge'
            or tags.get('layer') != '1'
            or any(tags.get(k) for k in ['name', 'official_name', 'short_name', 'alt_name', 'loc_name', 'old_name'])
            or not all(isinstance(k, str) and isinstance(v, str) for k, v in tags.items())
            or not all(isinstance(h, str) and HEX.fullmatch(h) for h in [source_cache_sha256, source_metadata.get('sha256')])):
        raise ValueError('unnamed original bridge identity, grade or provenance is invalid')
    if source_object['geometry'].get('type') != 'LineString':
        raise ValueError('bridge footprint needs its original closed way')
    coordinates = source_object['geometry'].get('coordinates', [])
    if (not isinstance(nodes, list) or len(nodes) < 4 or len(nodes) != len(coordinates)
            or any(type(n) is not int or n <= 0 for n in nodes)
            or nodes[0] != nodes[-1] or coordinates[0] != coordinates[-1]):
        raise ValueError('original bridge node ring is incomplete')
    polygon = Polygon(coordinates)
    if polygon.is_empty or not polygon.is_valid or not border.covers(polygon):
        raise ValueError('original bridge footprint is invalid or outside the city')
    geometry = mapping(polygon)
    return {'id': ident, 'source_url': 'https://www.openstreetmap.org/' + ident.removeprefix('osm/'),
        'roles': ['facility_reference'], 'names': [], 'tags': dict(sorted(tags.items())),
        'dimension': 'area', 'geometry': geometry, 'geometry_sha256': _digest(geometry),
        PROOF: {'schema_version': 1, 'source_pbf_sha256': source_metadata['sha256'],
            'source_cache_sha256': source_cache_sha256, 'source_object': copy.deepcopy(source_object),
            'source_object_sha256': _digest(source_object), 'original_geometry_clipped': False}}


def valid_bridge_outline(row, *, pipeline_version, source_metadata, border):
    proof = row.get(PROOF)
    if pipeline_version != 8 or not isinstance(proof, dict) or set(proof) != {
            'schema_version', 'source_pbf_sha256', 'source_cache_sha256', 'source_object',
            'source_object_sha256', 'original_geometry_clipped'}:
        return False
    if (proof['schema_version'] != 1 or proof['original_geometry_clipped'] is not False
            or proof['source_pbf_sha256'] != source_metadata.get('sha256')
            or proof['source_object_sha256'] != _digest(proof['source_object'])):
        return False
    try:
        expected = native_bridge_outline_object(source_object=proof['source_object'],
            source_cache_sha256=proof['source_cache_sha256'], source_metadata=source_metadata, border=border)
        return _digest(expected) == _digest(row)
    except (ValueError, TypeError, KeyError, IndexError):
        return False


def derive_underpass_reference(decision, request, objects, border, city):
    if (request.get('precision') != 'place'
            or request.get('geometry_task') != 'checked_point_geocode_required'
            or request.get('city_scope') != 'in_city' or request.get('coordinates') is not None
            or request.get('transit_route') is not None
            or request.get('transit_review', {}).get('status') != 'not_applicable'):
        raise ValueError('bridge road reference requires a stationary source place with no route or point')
    groups = decision['osm_object_groups']
    if len(groups) != 3 or [len(g) for g in groups] != [1, 2, 1]:
        raise ValueError('bridge reference needs one outline, two original upper roads and one lower road')
    ids = [i for g in groups for i in g]
    if len(set(ids)) != 4:
        raise ValueError('bridge reference objects must be distinct')
    try:
        bridge = objects[groups[0][0]]; upper = [objects[i] for i in groups[1]]; lower = objects[groups[2][0]]
    except KeyError as exc:
        raise ValueError('bridge reference object is absent') from exc
    bp = bridge.get(PROOF, {}); pbf = bp.get('source_pbf_sha256')
    if not valid_bridge_outline(bridge, pipeline_version=8, source_metadata={'sha256': pbf}, border=border):
        raise ValueError('original bridge outline proof is invalid')
    road_rows = [*upper, lower]
    if any(not valid_crossing_way(r, source_pbf_sha256=pbf) for r in road_rows):
        raise ValueError('original upper/lower road proof is invalid')
    originals = [r['native_crossing_way_source_proof']['source_way'] for r in road_rows]
    if any(r['native_crossing_way_source_proof']['source_cache_sha256'] != bp['source_cache_sha256'] for r in road_rows):
        raise ValueError('bridge and roads require the same checked native cache')
    if any(not border.covers(shape(r['geometry'])) for r in road_rows):
        raise ValueError('bridge carrier road escapes the municipality')
    polygon = shape(bridge['geometry']); source = bp['source_object']
    bridge_vertices = {n: tuple(c) for n, c in zip(source['node_ids'], source['geometry']['coordinates'])}
    lower_original = originals[-1]; lt = lower_original['tags']
    if (lt.get('highway') != 'motorway' or lt.get('oneway') != 'yes'
            or lt.get('layer', '0') != '0' or lt.get('bridge', 'no') != 'no'
            or lt.get('tunnel', 'no') != 'no'):
        raise ValueError('lower original road must be a directed surface motorway')
    lower_nodes = set(lower_original.get('node_ids', []))
    if not lower_nodes:
        raise ValueError('original lower road nodes are missing')
    names = set()
    for original in originals[:2]:
        tags = original['tags']; nodes = original.get('node_ids', []); coordinates = original['geometry']['coordinates']
        if (tags.get('bridge') != 'yes' or tags.get('layer') != '1'
                or not tags.get('highway') or not tags.get('name') or not nodes):
            raise ValueError('upper original roads need named bridge and grade evidence')
        if (nodes[0] not in bridge_vertices or nodes[-1] not in bridge_vertices
                or tuple(coordinates[0]) != bridge_vertices[nodes[0]]
                or tuple(coordinates[-1]) != bridge_vertices[nodes[-1]]
                or set(nodes) & lower_nodes or not polygon.covers(shape(original['geometry']))):
            raise ValueError('upper/lower nodes or original bridge coverage differ')
        names.add(tags['name'])
    if len(names) != 1:
        raise ValueError('upper bridge road identity is ambiguous')
    quotes = request.get('evidence_quotes', [])
    if not quotes or not all(isinstance(q, str) for q in quotes):
        raise ValueError('source bridge evidence is missing')
    text = ' '.join(quotes); name = next(iter(names)); ref = lt.get('ref', '')
    ref_match = re.fullmatch(r'([A-Za-z]+)\s*(\d+[A-Za-z]?)', ref)
    if (not re.search(r'\bBrücke\b', text)
            or not re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', text)
            or ref_match is None
            or not re.search(r'\b' + re.escape(ref_match[1]) + r'\s*' + re.escape(ref_match[2]) + r'\b', text)):
        raise ValueError('source evidence does not bind the named bridge road and motorway')
    destinations = sorted({t.strip() for t in re.split(r'[;|]', lt.get('destination:lanes', '')) if t.strip()})
    directions = [d for d in destinations if re.search(r'(?:Fahrtrichtung|Richtung)\s+' + re.escape(d) + r'\b', text)]
    if len(directions) != 1:
        raise ValueError('source motorway direction has no unique original destination binding')
    forward, inverse = metric_transforms(POI_CITY_SPECS[city].epsg)
    road = transform(forward, shape(lower['geometry'])); outline = transform(forward, polygon)
    clipped = road.intersection(outline)
    if (clipped.geom_type != 'LineString' or clipped.is_empty or not clipped.is_valid
            or not 0 < clipped.length < road.length):
        raise ValueError('native bridge must bound a proper finite lower road section')
    geometry = mapping(transform(inverse, clipped))
    if not border.covers(shape(geometry)):
        raise ValueError('derived underpass reference escapes the municipality')
    return {'type': 'LineString', 'geometry': geometry, 'geometry_sha256': _digest(geometry),
        'source_object_ids': ids, 'source_object_groups': groups,
        'geometry_usage': 'source_road_reference_only', 'source_road_extent': 'native_bridge_outline_bounded',
        'actual_non_transit_extent_known': False, 'actual_event_position_known': False,
        'actual_event_extent_known': False, 'eligible_as_event_count_geometry': False,
        'road_under_bridge_reference': {'bridge_object_id': bridge['id'], 'upper_road_ids': groups[1],
            'lower_road_id': lower['id'], 'source_road_name': name, 'source_motorway_ref': ref,
            'source_direction': directions[0], 'source_pbf_sha256': pbf,
            'source_cache_sha256': bp['source_cache_sha256'],
            'finite_reference_length_m': round(clipped.length, 3),
            'whole_native_lower_way_length_m': round(road.length, 3),
            'source_address_identity_verified': False, 'actual_event_extent_known': False}}
