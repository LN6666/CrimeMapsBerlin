"""Street precision stays a bounded reference, including all matching members."""
import copy
import pytest
from shapely.geometry import LineString,Polygon,box,mapping,shape
from shapely.ops import transform
from crimemapsberlin.geometry_decisions import _derived_geometry,_digest
from crimemapsberlin.map_decisions import _count_point
from crimemapsberlin.reviewed_city_map import _scene
from crimemapsberlin.spatial import metric_transforms

def row(ident,geometry,roles,tags):
    geo=mapping(geometry)
    return {'id':ident,'geometry':geo,'geometry_sha256':_digest(geo),'roles':roles,
        'tags':tags,'names':[tags['name']]}
def inputs():
    objects={
      'osm/way/1':row('osm/way/1',LineString([(8.01,50.05),(8.09,50.05)]),['road','named_object'],{'name':'Street','highway':'residential'}),
      'osm/way/2':row('osm/way/2',LineString([(8.03,50.03),(8.07,50.03)]),['road','named_object'],{'name':'Street','highway':'residential'}),
      'osm/way/3':row('osm/way/3',LineString([(8.1,50.1),(8.11,50.11)]),['road','named_object'],{'name':'Street','highway':'residential'}),
      'osm/relation/4':row('osm/relation/4',Polygon([(8.02,50.02),(8.08,50.02),(8.08,50.08),(8.02,50.08)],
        [[(8.04,50.04),(8.06,50.04),(8.06,50.06),(8.04,50.06)]]),['administrative_boundary','named_object'],
        {'name':'District','admin_level':'10','boundary':'administrative'}),
    }
    decision={'verdict':'resolved','method':'osm_district_road_reference',
        'osm_object_groups':[['osm/way/1','osm/way/2'],['osm/relation/4']]}
    request={'location_id':'s:location:1','label':'Street, District','role':'incident','precision':'street',
        'coordinates':None,'city_scope':'in_city','evidence_quotes':['Street in District'],
        'geometry_task':'checked_road_geometry_required'}
    return decision,request,objects,box(8,50,8.2,50.2)

def derive(values):
    d,r,o,b=values;return _derived_geometry(d,r,o,b,'frankfurt')

def test_metric_clip_keeps_all_district_street_parts_and_holes_without_count_points():
    values=inputs();original=copy.deepcopy(values[:3]);derived=derive(values)
    assert values[:3]==original
    geo=shape(derived['geometry']);boundary=shape(values[2]['osm/relation/4']['geometry'])
    metric,_=metric_transforms('EPSG:25832')
    assert geo.geom_type=='MultiLineString' and transform(metric,geo).difference(transform(metric,boundary).buffer(1e-6)).is_empty
    assert geo.intersection(box(8.04001,50.04001,8.05999,50.05999)).is_empty
    assert 'count_point' not in derived and derived['actual_event_extent_known'] is False
    clip=derived['district_reference_clip']
    assert clip['metric_crs']=='EPSG:25832' and clip['street_name']=='Street' and clip['district_name']=='District'
    assert [v['id'] for v in clip['per_original_object']]==['osm/way/1','osm/way/2']
    assert clip['retained_reference_length_m']<clip['selected_original_length_m']
    assert clip['boundary_intersection_vertices_are_event_coordinates'] is False and clip['historical_boundary_verified'] is False
    row={'decision':values[0],'derived_geometry':derived};scene=_scene(values[1],row,{}, {},None)
    assert scene['coordinates'] is None and not scene['primary_for_count']
    derived['count_point']={'type':'Point','coordinates':[8.03,50.03]};assert _count_point(row) is None
    with pytest.raises(ValueError,match='cannot be a primary'):_scene(values[1],row,{}, {},values[1]['location_id'])

@pytest.mark.parametrize('change',['omit_member','outside_member','different_street','inactive','point','wrong_boundary',
 'wrong_level','two_boundaries','missing_boundary','district_precision','moving','source_point','unmatched_name'])
def test_incomplete_or_incompatible_selections_are_rejected(change):
    values=inputs();d,r,o,b=values
    if change=='omit_member':d['osm_object_groups'][0].pop()
    elif change=='outside_member':d['osm_object_groups'][0].append('osm/way/3')
    elif change=='different_street':o['osm/way/2']['tags']['name']='Other street'
    elif change=='inactive':o['osm/way/2']['tags']['highway']='construction'
    elif change=='point':o['osm/way/2']['geometry']={'type':'Point','coordinates':[8.03,50.03]}
    elif change=='wrong_boundary':o['osm/relation/4']['roles']=['named_object']
    elif change=='wrong_level':o['osm/relation/4']['tags']['admin_level']='8'
    elif change=='two_boundaries':d['osm_object_groups'][1].append('osm/way/3')
    elif change=='missing_boundary':d['osm_object_groups'].pop()
    elif change=='district_precision':r.update(precision='district',geometry_task='checked_district_geometry_required')
    elif change=='moving':r['transit_route']={'mode':'bus','line':'63'}
    elif change=='source_point':r['coordinates']=[8.03,50.03]
    elif change=='unmatched_name':o['osm/way/2']['names']=[]
    with pytest.raises(ValueError):derive(values)

def highway_inputs():
    d,r,o,b=inputs()
    d['method']='osm_district_highway_reference'
    r.update(role='background',evidence_quotes=['B521 in District'])
    for ident in ['osm/way/1','osm/way/2','osm/way/3']:
        o[ident]['tags']['ref']='B 521';o[ident]['names'].append('B 521')
    # A numbered road can change street name, or have no street name.
    o['osm/way/1']['tags']['name']='First street'
    o['osm/way/2']['tags'].pop('name')
    return d,r,o,b

def test_numbered_district_reference_retains_different_and_unnamed_street_members():
    values=highway_inputs();derived=derive(values)
    assert derived['district_reference_clip']['road_ref']=='B 521'
    assert 'street_name' not in derived['district_reference_clip']
    assert [x['id'] for x in derived['district_reference_clip']['per_original_object']]==['osm/way/1','osm/way/2']
    assert derived['actual_event_position_known'] is False and derived['actual_event_extent_known'] is False
    scene=_scene(values[1],{'decision':values[0],'derived_geometry':derived},{},{},None)
    assert scene['coordinates'] is None and not scene['primary_for_count']

@pytest.mark.parametrize('change',['omit_member','outside_member','other_ref','composite_ref','missing_alias',
 'incident','other_source_ref','longer_source_number','source_point','moving'])
def test_numbered_reference_rejects_incomplete_membership_or_source_identity(change):
    values=highway_inputs();d,r,o,b=values
    if change=='omit_member':d['osm_object_groups'][0].pop()
    elif change=='outside_member':d['osm_object_groups'][0].append('osm/way/3')
    elif change=='other_ref':o['osm/way/2']['tags']['ref']='B 522'
    elif change=='composite_ref':
        for x in o.values():
            if 'ref' in x['tags']:x['tags']['ref']='B 521;B 3';x['names'].append('B 521;B 3')
        r['evidence_quotes']=['B521;B3 in District']
    elif change=='missing_alias':o['osm/way/2']['names']=[]
    elif change=='incident':r['role']='incident'
    elif change=='other_source_ref':r['evidence_quotes']=['B522 in District']
    elif change=='longer_source_number':r['evidence_quotes']=['B5210 in District']
    elif change=='source_point':r['coordinates']=[8.03,50.03]
    elif change=='moving':r['transit_route']={'mode':'bus','line':'63'}
    with pytest.raises(ValueError):derive(values)
