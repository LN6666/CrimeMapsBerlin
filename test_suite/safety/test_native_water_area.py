"""Native source water rings and reference-only rendering must remain intact."""
import copy
import json
import pytest
from shapely.geometry import Polygon, box, mapping, shape
from crimemapsberlin.city_geometry_index import native_unnamed_water_area_object, write_geometry_index, validate_geometry_index
from crimemapsberlin.geometry_decisions import _derived_geometry
from crimemapsberlin.map_decisions import _count_point
from crimemapsberlin.reviewed_city_map import _scene

META={'sha256':'a'*64,'pbf_timestamp':'2026-09-27T20:23:36Z'}
BORDER=box(8.0,50.0,8.2,50.2)
BOUNDARY={'id':'osm/relation/1','source_pbf_sha256':META['sha256'],'geometry':mapping(BORDER)}
def area(*,relation=False):
    outer=[[7.99,50.01],[8.15,50.01],[8.15,50.15],[7.99,50.15],[7.99,50.01]]
    inner=[[8.02,50.03],[8.02,50.05],[8.04,50.05],[8.04,50.03],[8.02,50.03]]
    tags={'natural':'water','water':'river'}
    if relation:tags['type']='multipolygon'
    rel={'id':11,'tags':tags,'members':[{'type':'w','ref':12,'role':'outer'},{'type':'w','ref':13,'role':'inner'}],'version':2,'timestamp':'2026-01-01 00:00:00+00:00'} if relation else None
    return {'id':'osm/relation/11' if relation else 'osm/way/11','tags':tags,
            'geometry':mapping(Polygon(outer,[inner] if relation else [])),
            'rings':[{'outer_node_ids':[1,2,3,4,1],'outer_coordinates':outer,
                      'inner_rings':[{'node_ids':[5,6,7,8,5],'coordinates':inner}] if relation else []}],
            'relation':rel,'version':2,'timestamp':'2026-01-01 00:00:00+00:00'}
def native(src=None):return native_unnamed_water_area_object(source_area=src or area(relation=True),source_metadata=META,border=BORDER)

@pytest.mark.parametrize('relation',[False,True])
def test_opt_in_city_overlay_preserves_original_rings_and_holes(relation,tmp_path):
    src=area(relation=relation);original=copy.deepcopy(src);row=native(src)
    assert src==original and row['names']==[] and row['roles']==['water_area']
    assert shape(row['geometry']).equals(shape(src['geometry']).intersection(BORDER))
    assert row['native_unnamed_water_area_source_proof']['source_area']==src
    if relation:assert len(shape(row['geometry']).interiors)==1
    index=write_geometry_index(city='frankfurt',objects=[row],border=BORDER,boundary_metadata=BOUNDARY,source_metadata=META,output=tmp_path/'index.json',pipeline_version=5)
    assert index['name_index']=={} and not index['semantic_matching_performed'] and not index['publication_ready']
    assert validate_geometry_index(index,city='frankfurt',border=BORDER,boundary_metadata=BOUNDARY,source_metadata=META)['passed']
    with pytest.raises(ValueError,match='proof'):
        write_geometry_index(city='frankfurt',objects=[row],border=BORDER,boundary_metadata=BOUNDARY,source_metadata=META,output=tmp_path/'default.json')

@pytest.mark.parametrize('change',['invented_name','wrong_surface','building','drop_hole','move_node','bad_node_id','open_ring','wrong_relation_id','missing_members','wrong_member_role','way_with_hole'])
def test_reject_incompatible_or_changed_native_sources(change):
    src=area(relation=True)
    if change=='invented_name':src['tags']['name']='Invented Main'
    elif change=='wrong_surface':src['tags']['natural']='wood'
    elif change=='building':src['tags']['building']='yes'
    elif change=='drop_hole':src['rings'][0]['inner_rings']=[]
    elif change=='move_node':src['rings'][0]['outer_coordinates'][1][0]+=0.01
    elif change=='bad_node_id':src['rings'][0]['outer_node_ids'][1]=False
    elif change=='open_ring':src['rings'][0]['outer_node_ids'][-1]=9
    elif change=='wrong_relation_id':src['relation']['id']=19
    elif change=='missing_members':src['relation']['members']=[]
    elif change=='wrong_member_role':src['relation']['members'][0]['role']='invented'
    else:src['id']='osm/way/11';src['relation']=None
    with pytest.raises(ValueError):native(src)

@pytest.mark.parametrize('change',['source_hash','native_ring','hole','name','role','coordinate','missing_proof'])
def test_index_readback_rejects_tampered_provenance_or_geometry(change,tmp_path):
    idx=write_geometry_index(city='frankfurt',objects=[native()],border=BORDER,boundary_metadata=BOUNDARY,source_metadata=META,output=tmp_path/'index.json',pipeline_version=5)
    idx=json.loads((tmp_path/'index.json').read_text())
    row=idx['objects'][0];proof=row['native_unnamed_water_area_source_proof']
    if change=='source_hash':proof['source_pbf_sha256']='b'*64
    elif change=='native_ring':proof['source_area']['rings'][0]['outer_node_ids'][1]=999
    elif change=='hole':proof['source_area']['rings'][0]['inner_rings']=[]
    elif change=='name':row['names']=['Invented Main']
    elif change=='role':row['roles']=['road']
    elif change=='coordinate':row['geometry']['coordinates'][0][0][0]+=1
    else:del row['native_unnamed_water_area_source_proof']
    assert not validate_geometry_index(idx,city='frankfurt',border=BORDER,boundary_metadata=BOUNDARY,source_metadata=META)['passed']

def request(precision='area'):
    return {'location_id':'s:location:1','label':'Main reference','role':'background','precision':precision,'coordinates':None,'city_scope':'in_city','evidence_quotes':['river'],'geometry_task':'checked_area_geometry_required' if precision=='area' else 'checked_point_geocode_required'}
def derive(req=None,obj=None):
    obj=obj or native();return _derived_geometry({'verdict':'resolved','method':'osm_water_footprint_reference','osm_object_groups':[[obj['id']]]},req or request(),{obj['id']:obj},BORDER,'frankfurt',include_footprint_count_points=True)

@pytest.mark.parametrize('precision',['area','place'])
def test_water_reference_has_no_event_or_count_coordinates_even_when_count_points_enabled(precision):
    req=request(precision);original=copy.deepcopy(req);derived=derive(req)
    assert req==original and derived['geometry_usage']=='source_footprint_reference_only'
    assert derived['actual_event_position_known'] is False and derived['actual_event_extent_known'] is False and 'count_point' not in derived
    row={'decision':{'verdict':'resolved','method':'osm_water_footprint_reference'},'derived_geometry':derived}
    assert _count_point(row) is None
    scene=_scene(req,row,{}, {},None)
    assert scene['coordinates'] is None and scene['primary_for_count'] is False and scene['actual_event_extent_known'] is False
    injected=copy.deepcopy(row);injected['derived_geometry']['count_point']={'type':'Point','coordinates':[8.1,50.1]}
    assert _count_point(injected) is None
    with pytest.raises(ValueError,match='cannot be a primary'):_scene(req,injected,{}, {},req['location_id'])

@pytest.mark.parametrize('change',['address','incident','transit','road','dry_polygon','water_line'])
def test_water_method_rejects_wrong_source_role_precision_or_geometry(change):
    req=request();obj=native()
    if change=='address':req['precision']='address';req['geometry_task']='checked_point_geocode_required'
    elif change=='incident':req['role']='incident'
    elif change=='transit':req['transit_route']={'mode':'boat','line':'invented'}
    elif change=='road':obj['roles']=['road']
    elif change=='dry_polygon':obj['tags']['natural']='wood'
    else:obj['geometry']={'type':'LineString','coordinates':[[8.05,50.05],[8.1,50.1]]}
    with pytest.raises(ValueError):derive(req,obj)

def test_water_area_must_not_be_used_as_a_road_line():
    obj=native()
    with pytest.raises(ValueError,match='road objects'):
        _derived_geometry({'verdict':'resolved','method':'osm_line','osm_object_groups':[[obj['id']]]},request(),{obj['id']:obj},BORDER,'frankfurt')
