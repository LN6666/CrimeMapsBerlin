"""Crossing landmarks retain original grade/vertices and linked source scope."""
import copy
import pytest
from shapely.geometry import box
from crimemapsberlin.city_geometry_index import _digest
from crimemapsberlin.city_rail_crossing_reference import enrich_crossing_way, valid_crossing_way
from crimemapsberlin.geometry_decisions import _derived_geometry
from crimemapsberlin.map_decisions import _count_point
from crimemapsberlin.reviewed_city_map import _scene


def fixture():
    objects={}
    for ident,name,tags,coords in [
        (1,'First',{'highway':'residential','name':'First'},[[8.6999,50.13],[8.7,50.13],[8.7001,50.13]]),
        (2,'Second',{'highway':'residential','name':'Second'},[[8.7,50.13],[8.7,50.1301],[8.7,50.1302]]),
        (3,'U4',{'railway':'light_rail'},[[8.6999,50.1301],[8.7,50.1301],[8.7001,50.1301]])]:
        row={'id':f'osm/way/{ident}','names':[name],'roles':['named_object']+(['road'] if ident!=3 else []),
            'tags':tags,'geometry':{'type':'LineString','coordinates':coords}}
        if ident==3:row['transit_member_source_proof']={'way_id':3,'source_way_digest':_digest({'tags':tags,'geometry':row['geometry']}),
            'memberships':[{'relation_id':4,'mode':'subway','line':'U4'}]}
        objects[row['id']]=enrich_crossing_way(row,original={'tags':tags,'geometry':row['geometry']},source_cache_sha256='a'*64,source_pbf_sha256='b'*64)
    objects['osm/relation/4']={'id':'osm/relation/4','names':['U4'],'roles':['named_object','transit_route'],
        'tags':{'type':'route','route':'subway','ref':'U4'},
        'geometry':objects['osm/way/3']['geometry'],'transit_source_proof':{'schema_version':1,'relation_id':4,'complete':True,'member_way_ids':[3],
            'member_way_count':1,'member_sequence':[3],'member_source_digest':'c'*64}}
    decision={'verdict':'resolved','method':'osm_rail_crossing_area_reference',
        'osm_object_groups':[['osm/way/1'],['osm/way/2'],['osm/way/3'],['osm/relation/4']]}
    request={'geometry_task':'checked_area_geometry_required','precision':'area','role':'accident',
        'coordinates':None,'transit_review':{'status':'source_backed_context'}}
    routes=[{'mode':'subway','line':'U4','extent':'source_segment'}]
    return decision,request,objects,routes


def derive(d,r,o,contexts):
    return _derived_geometry(d,r,o,box(8.69,50.12,8.71,50.14),'frankfurt',source_transit_contexts=contexts)


def test_original_site_includes_separate_road_and_rail_vertices_without_event_extent():
    d,r,o,c=fixture();v=derive(d,r,o,c)
    assert v['type']=='MultiPoint' and set(v['geometry']['coordinates'])=={(8.7,50.13),(8.7,50.1301)}
    assert v['actual_event_position_known'] is False and v['actual_event_extent_known'] is False
    assert v['rail_crossing_reference']['actual_transit_extent_known'] is False
    assert 'count_point' not in v and 'count_point_method' not in v
    location={**r,'location_id':'1:location:1','label':'source crossing area','city_scope':'in_city','evidence_quotes':['crossing']}
    row={'decision':d,'derived_geometry':v};scene=_scene(location,row,{}, {},None)
    assert scene['coordinates'] is None and scene['location_precision']=='area' and not scene['primary_for_count']
    assert scene['rail_crossing_reference']==v['rail_crossing_reference'] and _count_point(row) is None
    with pytest.raises(ValueError,match='cannot be a primary'):_scene(location,row,{}, {},location['location_id'])


@pytest.mark.parametrize('change',[{'precision':'route'},{'geometry_task':'checked_point_geocode_required'},
    {'coordinates':[8.7,50.13]},{'transit_route':{'line':'U4'}},{'transit_review':{'status':'reviewed_route'}}])
def test_stationary_source_area_cannot_be_changed_into_a_point_or_ride(change):
    d,r,o,c=fixture();r.update(change)
    with pytest.raises(ValueError):derive(d,r,o,c)


@pytest.mark.parametrize('contexts',[[],[{'line':'U1','mode':'subway','extent':'source_segment'}],
    [{'line':'U4','mode':'tram','extent':'source_segment'}],[{'line':'U4','mode':'subway','extent':'full_line'}]])
def test_carrier_must_match_the_linked_current_source_segment(contexts):
    d,r,o,c=fixture()
    with pytest.raises(ValueError,match='linked source segment'):derive(d,r,o,contexts)


@pytest.mark.parametrize('tag,value',[('layer','1'),('level','-1'),('bridge','yes'),('tunnel','yes')])
def test_original_grade_cannot_be_replaced_by_a_planar_crossing(tag,value):
    d,r,o,c=fixture();row=o['osm/way/2'];proof=row['native_crossing_way_source_proof']
    proof['source_way']['tags'][tag]=value;proof['source_way_sha256']=_digest(proof['source_way'])
    with pytest.raises(ValueError,match='grade'):derive(d,r,o,c)


@pytest.mark.parametrize('kind',['missing','geometry','cache_digest','source_digest','node_count','indexed_tag'])
def test_original_source_way_proof_is_bound_and_cannot_be_tampered(kind):
    d,r,o,c=fixture();row=o['osm/way/2'];proof=row['native_crossing_way_source_proof']
    if kind=='missing':row.pop('native_crossing_way_source_proof')
    elif kind=='geometry':proof['source_way']['geometry']['coordinates'][1][0]+=0.00001
    elif kind=='cache_digest':proof['source_cache_sha256']='bad'
    elif kind=='source_digest':proof['source_way_sha256']='0'*64
    elif kind=='node_count':proof['source_way']['node_ids']=[1]
    else:row['tags']['name']='Changed'
    assert not valid_crossing_way(row,source_pbf_sha256='b'*64)
    with pytest.raises(ValueError):derive(d,r,o,c)


def test_wrong_pbf_binding_is_rejected_at_index_readback():
    d,r,o,c=fixture();assert not valid_crossing_way(o['osm/way/1'],source_pbf_sha256='d'*64)


def test_rail_membership_cannot_use_another_carrier_or_incomplete_carrier():
    d,r,o,c=fixture();o['osm/relation/4']['transit_source_proof']['complete']=False
    with pytest.raises(ValueError,match='incomplete'):derive(d,r,o,c)
    d,r,o,c=fixture();o['osm/way/3']['transit_member_source_proof']['memberships'][0]['relation_id']=99
    with pytest.raises(ValueError,match='not in its checked source carrier'):derive(d,r,o,c)


def test_planar_rail_intersection_without_original_vertex_is_rejected():
    d,r,o,c=fixture();row=o['osm/way/3'];row['geometry']['coordinates'].pop(1)
    proof=row['native_crossing_way_source_proof'];proof['source_way']['geometry']=copy.deepcopy(row['geometry'])
    proof['source_way_sha256']=_digest(proof['source_way'])
    row['transit_member_source_proof']['source_way_digest']=_digest({'tags':row['tags'],'geometry':row['geometry']})
    with pytest.raises(ValueError,match='invent a planar'):derive(d,r,o,c)


def test_an_uncrossed_rail_member_cannot_widen_the_reference_to_the_full_line():
    d,r,o,c=fixture();row=o['osm/way/3'];row['geometry']['coordinates']=[[8.6999,50.1303],[8.7001,50.1303]]
    proof=row['native_crossing_way_source_proof'];proof['source_way']['geometry']=copy.deepcopy(row['geometry'])
    proof['source_way_sha256']=_digest(proof['source_way'])
    row['transit_member_source_proof']['source_way_digest']=_digest({'tags':row['tags'],'geometry':row['geometry']})
    with pytest.raises(ValueError,match='no original road crossing'):derive(d,r,o,c)
