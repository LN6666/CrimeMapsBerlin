"""Failure checks for provenance, grade separation, source binding and counting."""
import copy

import pytest
from crimemapsberlin.city_road_bridge_reference import native_bridge_outline_object, valid_bridge_outline
from shapely.geometry import box

from crimemapsberlin.city_geometry_index import _digest
from crimemapsberlin.city_rail_crossing_reference import enrich_crossing_way
from crimemapsberlin.geometry_decisions import _derived_geometry
from crimemapsberlin.map_decisions import _count_point
from crimemapsberlin.reviewed_city_map import _scene


def fixture():
    border=box(8.69,50.12,8.71,50.14);pbf='b'*64;cache='a'*64
    outline={'id':'osm/way/1','tags':{'man_made':'bridge','layer':'1'},
        'geometry':{'type':'LineString','coordinates':[[8.6998,50.1299],[8.7002,50.1299],
            [8.7002,50.1301],[8.6998,50.1301],[8.6998,50.1299]]},'node_ids':[10,11,12,13,10]}
    objects={outline['id']:native_bridge_outline_object(source_object=outline,source_cache_sha256=cache,
        source_metadata={'sha256':pbf},border=border)}
    for ident,tags,coordinates,nodes in [
        (2,{'highway':'secondary','name':'Upper Road','bridge':'yes','layer':'1'},
         [[8.6998,50.1299],[8.7002,50.1299]],[10,11]),
        (3,{'highway':'secondary','name':'Upper Road','bridge':'yes','layer':'1'},
         [[8.7002,50.1301],[8.6998,50.1301]],[12,13]),
        (4,{'highway':'motorway','ref':'A 1','oneway':'yes','destination:lanes':'North Town'},
         [[8.7,50.1295],[8.7,50.1305]],[20,21])]:
        row={'id':f'osm/way/{ident}','names':[tags.get('name',tags.get('ref'))],'roles':['named_object','road'],
            'tags':{k:v for k,v in tags.items() if k in {'highway','name','ref'}},
            'geometry':{'type':'LineString','coordinates':coordinates}}
        original={'tags':tags,'geometry':row['geometry'],'node_ids':nodes}
        objects[row['id']]=enrich_crossing_way(row,original=original,source_cache_sha256=cache,source_pbf_sha256=pbf)
    request={'geometry_task':'checked_point_geocode_required','precision':'place','city_scope':'in_city',
        'role':'accident','coordinates':None,'transit_review':{'status':'not_applicable'},
        'evidence_quotes':['Brücke Upper Road über A 1 Fahrtrichtung North Town']}
    decision={'verdict':'resolved','method':'osm_road_under_bridge_reference',
        'osm_object_groups':[['osm/way/1'],['osm/way/2','osm/way/3'],['osm/way/4']]}
    return decision,request,objects,border


def derive(d,r,o,b):return _derived_geometry(d,r,o,b,'frankfurt',include_footprint_count_points=True)


def test_underpass_is_finite_reference_and_cannot_be_a_count_point():
    d,r,o,b=fixture();v=derive(d,r,o,b)
    assert v['type']=='LineString' and v['geometry_usage']=='source_road_reference_only'
    assert not v['actual_event_position_known'] and not v['actual_event_extent_known']
    assert 0<v['road_under_bridge_reference']['finite_reference_length_m']<v['road_under_bridge_reference']['whole_native_lower_way_length_m']
    assert 'count_point' not in v and not v['eligible_as_event_count_geometry']
    row={'decision':d,'derived_geometry':v};assert _count_point(row) is None
    loc={**r,'location_id':'1:location:1','label':'source bridge place'}
    scene=_scene(loc,row,{}, {},None)
    assert scene['coordinates'] is None and not scene['primary_for_count']
    assert scene['road_under_bridge_reference']==v['road_under_bridge_reference']
    with pytest.raises(ValueError,match='road reference cannot be a primary'):_scene(loc,row,{}, {},loc['location_id'])


@pytest.mark.parametrize('change',[{'coordinates':[8.7,50.13]},{'precision':'route'},
    {'city_scope':'uncertain'},{'geometry_task':'checked_area_geometry_required'},
    {'transit_route':{'line':'U1'}},{'transit_review':{'status':'source_unknown'}}])
def test_point_route_or_unverified_city_request_is_rejected(change):
    d,r,o,b=fixture();r.update(change)
    with pytest.raises(ValueError):derive(d,r,o,b)


@pytest.mark.parametrize('evidence',['Brücke Other Road über A 1 Fahrtrichtung North Town',
    'Brücke Upper Road über A 2 Fahrtrichtung North Town',
    'Brücke Upper Road über A 10 Fahrtrichtung North Town',
    'Brücke Upper Road über A 1 Fahrtrichtung South Town','Upper Road A 1 North Town'])
def test_source_name_carrier_and_direction_must_be_bound(evidence):
    d,r,o,b=fixture();r['evidence_quotes']=[evidence]
    with pytest.raises(ValueError):derive(d,r,o,b)


@pytest.mark.parametrize('which,key,value',[(2,'layer','0'),(2,'bridge','no'),(4,'layer','1'),
    (4,'tunnel','yes'),(4,'oneway','no')])
def test_rehashed_but_wrong_original_grade_or_direction_is_rejected(which,key,value):
    d,r,o,b=fixture();proof=o[f'osm/way/{which}']['native_crossing_way_source_proof']
    proof['source_way']['tags'][key]=value;proof['source_way_sha256']=_digest(proof['source_way'])
    with pytest.raises(ValueError):derive(d,r,o,b)


@pytest.mark.parametrize('kind',['missing','cache','pbf','geometry','node_coordinate'])
def test_missing_stale_or_tampered_native_proof_is_rejected(kind):
    d,r,o,b=fixture();row=o['osm/way/2'];proof=row['native_crossing_way_source_proof']
    if kind=='missing':row.pop('native_crossing_way_source_proof')
    elif kind=='cache':proof['source_cache_sha256']='c'*64
    elif kind=='pbf':proof['source_pbf_sha256']='d'*64
    elif kind=='geometry':row['geometry']['coordinates'][0][0]+=0.000001
    else:
        original=proof['source_way'];original['node_ids'][0]=12;proof['source_way_sha256']=_digest(original)
    with pytest.raises(ValueError):derive(d,r,o,b)


def test_original_bridge_ring_must_be_versioned_complete_and_in_city():
    _d,_r,o,b=fixture();row=o['osm/way/1']
    assert valid_bridge_outline(row,pipeline_version=8,source_metadata={'sha256':'b'*64},border=b)
    assert not valid_bridge_outline(row,pipeline_version=7,source_metadata={'sha256':'b'*64},border=b)
    assert not valid_bridge_outline(row,pipeline_version=8,source_metadata={'sha256':'d'*64},border=b)
    assert not valid_bridge_outline(row,pipeline_version=8,source_metadata={'sha256':'b'*64},border=box(8.6999,50.13,8.7001,50.1301))
    broken=copy.deepcopy(row);broken['native_bridge_outline_source_proof']['source_object']['node_ids'].pop()
    assert not valid_bridge_outline(broken,pipeline_version=8,source_metadata={'sha256':'b'*64},border=b)


def test_bridge_outline_cannot_be_selected_via_generic_footprint_method():
    d,r,o,b=fixture();d.update(method='osm_footprint',osm_object_groups=[['osm/way/1']])
    with pytest.raises(ValueError,match='only valid for its source-bound underpass'):derive(d,r,o,b)
