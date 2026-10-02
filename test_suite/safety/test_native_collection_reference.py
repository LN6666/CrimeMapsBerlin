"""Preserve native membership and prevent exact-event/count semantics."""
import copy
import pytest
from shapely.geometry import box
from crimemapsberlin.geometry_decisions import _derived_geometry
from crimemapsberlin.map_decisions import _count_point
from crimemapsberlin.reviewed_city_map import _scene

METHOD='osm_place_native_collection_reference';USAGE='source_native_collection_reference_only'
def inputs():
 objects={
  'osm/node/1':{'id':'osm/node/1','roles':['named_object'],'names':['Stop'],'tags':{'bus':'yes','public_transport':'platform'},'geometry':{'type':'Point','coordinates':[1,1]}},
  'osm/way/2':{'id':'osm/way/2','roles':['named_object'],'names':['Stop'],'tags':{'bus':'yes','public_transport':'platform'},'geometry':{'type':'LineString','coordinates':[[0,1],[2,1]]}},
 }
 decision={'verdict':'resolved','method':METHOD,'osm_object_groups':[['osm/node/1','osm/way/2']]}
 request={'geometry_task':'checked_point_geocode_required','precision':'place','coordinates':None}
 return decision,request,objects

def test_mixed_original_members_are_preserved_when_point_is_on_line():
 d,r,o=inputs();result=_derived_geometry(d,r,o,box(-3,-3,3,3),'frankfurt')
 assert result['type']=='GeometryCollection' and len(result['geometry']['geometries'])==2
 assert result['source_object_ids']==list(o) and result['source_object_groups']==d['osm_object_groups']
 assert list(result['geometry']['geometries'][0]['coordinates'])==[1,1]
 assert [list(p) for p in result['geometry']['geometries'][1]['coordinates']]==[[0,1],[2,1]]
 assert result['geometry_usage']==USAGE and result['actual_event_position_known'] is False and result['actual_event_extent_known'] is False
 assert 'count_point' not in result
 row={'decision':d,'derived_geometry':result}
 assert _count_point(row) is None
 row['derived_geometry']['count_point']={'type':'Point','coordinates':[1,1]}
 assert _count_point(row) is None
 location={**r,'location_id':'S:location:1','label':'Stop','role':'incident','city_scope':'in_city','evidence_quotes':['at Stop']}
 scene=_scene(location,row,{}, {},None)
 assert scene['coordinates'] is None and scene['primary_for_count'] is False
 assert scene['geometry_usage']==USAGE and scene['actual_event_extent_known'] is False
 with pytest.raises(ValueError,match='cannot be a primary'):_scene(location,row,{}, {},location['location_id'])

@pytest.mark.parametrize('change',['single','two_groups','duplicate','district','moving','area','missing_name','administrative','not_named','outside','absent','vertex'])
def test_invalid_context_or_original_objects_are_rejected(change):
 d,r,o=inputs(); border=box(-3,-3,3,3)
 if change=='single':d['osm_object_groups']=[['osm/node/1']]
 elif change=='two_groups':d['osm_object_groups']=[['osm/node/1'],['osm/way/2']]
 elif change=='duplicate':d['osm_object_groups']=[['osm/node/1','osm/node/1']]
 elif change=='district':r['precision']='district';r['geometry_task']='checked_area_geometry_required'
 elif change=='moving':r['transit_route']={'mode':'bus','line':'M55','extent':'source_segment'}
 elif change=='area':r['precision']='area';r['geometry_task']='checked_area_geometry_required'
 elif change=='missing_name':o['osm/node/1']['names']=[]
 elif change=='administrative':o['osm/node/1']['roles'].append('administrative_boundary')
 elif change=='not_named':o['osm/node/1']['roles']=[]
 elif change=='outside':border=box(-3,-3,.5,.5)
 elif change=='absent':del o['osm/node/1']
 elif change=='vertex':o['osm/node/1']['native_road_vertex_source_proof']={}
 with pytest.raises(ValueError):_derived_geometry(d,r,o,border,'frankfurt')
