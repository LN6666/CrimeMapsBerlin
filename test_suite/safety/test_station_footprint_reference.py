"""Unnamed station buildings retain original rings and remain background references."""
import copy,json
import pytest
from shapely.geometry import box,mapping
from crimemapsberlin.city_geometry_index import native_facility_reference_object,write_geometry_index,validate_geometry_index
from crimemapsberlin.geometry_decisions import _derived_geometry,_digest
from crimemapsberlin.reviewed_city_map import _scene
from crimemapsberlin.map_decisions import _count_point

BORDER=box(8,50,8.2,50.2);META={'sha256':'a'*64,'pbf_timestamp':'2026-09-27T20:23:36Z'}
BOUNDARY={'id':'osm/relation/1','source_pbf_sha256':META['sha256'],'geometry':mapping(BORDER)}
def raw():
    return {'id':'osm/way/1','tags':{'building':'train_station','level':'0'},
        'geometry':{'type':'LineString','coordinates':[[8.01,50.01],[8.09,50.01],[8.09,50.09],[8.01,50.09],[8.01,50.01]]},
        'node_ids':[11,12,13,14,11],'version':1,'timestamp':'2025-08-03T07:55:07Z'}
def native(r):return native_facility_reference_object(source_object=r,source_cache_sha256='c'*64,source_metadata=META,border=BORDER)
def inputs():
    building=native(raw());geo={'type':'Point','coordinates':[8.05,50.05]}
    station={'id':'osm/node/2','source_url':'https://www.openstreetmap.org/node/2','roles':['named_object'],
        'names':['Station'],'tags':{'name':'Station','railway':'station','train':'yes'},'dimension':'point',
        'geometry':geo,'geometry_sha256':_digest(geo)}
    d={'verdict':'resolved','method':'osm_station_footprint_reference','osm_object_groups':[[building['id']],[station['id']]]}
    r={'location_id':'s:location:1','label':'Station as escape direction only','role':'background','precision':'area',
        'coordinates':None,'city_scope':'in_city','geometry_task':'checked_area_geometry_required','evidence_quotes':['toward Station']}
    return d,r,{o['id']:o for o in [building,station]}

def test_original_closed_ring_is_preserved_without_name_or_point_and_requires_pipeline_seven(tmp_path):
    original=raw();unchanged=copy.deepcopy(original);row=native(original)
    assert original==unchanged and row['names']==[] and row['roles']==['facility_reference']
    assert row['native_facility_kind']=='train_station_building' and row['dimension']=='area'
    assert json.loads(json.dumps(row['geometry']))=={'type':'Polygon','coordinates':[original['geometry']['coordinates']]}
    assert row['native_facility_source_proof']['source_object']==original
    idx=write_geometry_index(city='frankfurt',objects=[row],border=BORDER,boundary_metadata=BOUNDARY,source_metadata=META,
        output=tmp_path/'index.json',pipeline_version=7)
    assert validate_geometry_index(idx,city='frankfurt',border=BORDER,boundary_metadata=BOUNDARY,source_metadata=META)['passed']
    for version in [3,6]:
        with pytest.raises(ValueError,match='proof'):write_geometry_index(city='frankfurt',objects=[row],border=BORDER,
            boundary_metadata=BOUNDARY,source_metadata=META,output=tmp_path/f'old-{version}.json',pipeline_version=version)

@pytest.mark.parametrize('change',['open_nodes','open_geometry','missing_nodes','different_building','name','point','polygon_input'])
def test_reject_non_original_station_ring(change):
    r=raw()
    if change=='open_nodes':r['node_ids'][-1]=15
    elif change=='open_geometry':r['geometry']['coordinates'][-1]=[8.02,50.02]
    elif change=='missing_nodes':r['node_ids'].pop()
    elif change=='different_building':r['tags']['building']='commercial'
    elif change=='name':r['tags']['name']='Invented station'
    elif change=='point':r['geometry']={'type':'Point','coordinates':[8.05,50.05]}
    elif change=='polygon_input':r['geometry']={'type':'Polygon','coordinates':[r['geometry']['coordinates']]}
    with pytest.raises(ValueError):native(r)

def test_named_identity_supplies_no_centre_arrival_floor_or_count_geometry():
    d,r,o=inputs();original=copy.deepcopy(o);derived=_derived_geometry(d,r,o,BORDER,'frankfurt')
    assert o==original and json.loads(json.dumps(derived['geometry']))==json.loads(json.dumps(o['osm/way/1']['geometry']))
    assert derived['source_object_ids']==list(o) and derived['geometry_usage']=='source_footprint_reference_only'
    assert 'count_point' not in derived and derived['actual_event_position_known'] is False and derived['actual_event_extent_known'] is False
    identity=derived['station_reference_identity']
    assert not identity['actual_arrival_or_station_entry_proven'] and not identity['interior_level_geometry_proven']
    row={'decision':d,'derived_geometry':derived};scene=_scene(r,row,{}, {},None)
    assert scene['coordinates'] is None and scene['primary_for_count'] is False
    derived['count_point']={'type':'Point','coordinates':[8.05,50.05]};assert _count_point(row) is None
    with pytest.raises(ValueError,match='cannot be a primary'):_scene(r,row,{}, {},r['location_id'])

@pytest.mark.parametrize('change',['outside_station','unnamed','subway','non_rail','line_station','unproved_building',
    'invented_names','incident','district','coordinates','moving','combined_groups','extra_station','wrong_method'])
def test_reject_unsupported_identity_scene_or_selection(change):
    d,r,o=inputs();s=o['osm/node/2'];b=o['osm/way/1']
    if change=='outside_station':s['geometry']['coordinates']=[8.15,50.15]
    elif change=='unnamed':s['names']=[]
    elif change=='subway':s['tags'].update(train='no',subway='yes')
    elif change=='non_rail':s['tags']['railway']='halt'
    elif change=='line_station':s['geometry']={'type':'LineString','coordinates':[[8.03,50.03],[8.07,50.07]]}
    elif change=='unproved_building':del b['native_facility_source_proof']
    elif change=='invented_names':b['names']=['Station']
    elif change=='incident':r['role']='incident'
    elif change=='district':r.update(precision='district',geometry_task='checked_district_geometry_required')
    elif change=='coordinates':r['coordinates']=[8.05,50.05]
    elif change=='moving':r['transit_route']={'mode':'train','line':'S1'}
    elif change=='combined_groups':d['osm_object_groups']=[list(o)]
    elif change=='extra_station':d['osm_object_groups'][1].append('osm/way/1')
    elif change=='wrong_method':d.update(method='osm_footprint',osm_object_groups=[['osm/way/1']]);r.update(precision='place',geometry_task='checked_point_geocode_required')
    with pytest.raises(ValueError):_derived_geometry(d,r,o,BORDER,'frankfurt')
