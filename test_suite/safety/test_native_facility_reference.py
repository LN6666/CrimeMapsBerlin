"""Ref-only facilities retain original members without invented event points."""
import copy,json
import pytest
from shapely.geometry import box,mapping
from crimemapsberlin.city_geometry_index import (
    native_facility_reference_object,write_geometry_index,validate_geometry_index,
)
from crimemapsberlin.geometry_decisions import _derived_geometry
from crimemapsberlin.map_decisions import _count_point
from crimemapsberlin.reviewed_city_map import _scene

META={'sha256':'a'*64,'pbf_timestamp':'2026-09-27T20:23:36Z'}
BORDER=box(8,50,8.2,50.2)
BOUNDARY={'id':'osm/relation/1','source_pbf_sha256':META['sha256'],'geometry':mapping(BORDER)}

def source(kind='gate',ident=1):
    tags={'access':'private','barrier':'gate','ref':'Tor 23'}
    geo={'type':'Point','coordinates':[8.01+ident*.00001,50.01]}
    obj={'id':f'osm/node/{ident}','tags':tags,'geometry':geo}
    if kind=='stand':
        obj.update(id=f'osm/way/{ident}',tags={'aeroway':'parking_position','ref':'C13'},
            geometry={'type':'LineString','coordinates':[[8.01,50.01],[8.012,50.012]]},node_ids=[11,12])
    elif kind=='crossing':obj['tags']={'railway':'level_crossing','crossing:barrier':'double_half','crossing:light':'yes'}
    return obj

def native(obj):return native_facility_reference_object(source_object=obj,source_cache_sha256='b'*64,source_metadata=META,border=BORDER)
def request(precision='place'):
    return {'location_id':'s:location:1','label':'Source facility','role':'accident','precision':precision,
        'coordinates':None,'city_scope':'in_city','evidence_quotes':['source named facility'],
        'geometry_task':'checked_point_geocode_required' if precision=='place' else 'unresolved_no_geometry'}
def inputs(kind='gate'):
    objects=[native(source(kind,i)) for i in ([1] if kind=='stand' else [1,2])]
    decision={'verdict':'resolved','method':'osm_native_facility_reference','osm_object_groups':[[o['id'] for o in objects]]}
    return decision,request('unknown' if kind=='crossing' else 'place'),{o['id']:o for o in objects}

@pytest.mark.parametrize('kind',['gate','stand','crossing'])
def test_original_unnamed_tags_members_and_nodes_survive_opt_in_readback(kind,tmp_path):
    raw=source(kind);original=copy.deepcopy(raw);row=native(raw)
    assert raw==original and row['names']==[] and row['roles']==['facility_reference']
    assert row['tags']==raw['tags'] and json.loads(json.dumps(row['geometry']))==raw['geometry']
    assert row['native_facility_source_proof']['source_object']==raw
    if kind=='stand':assert row['native_facility_source_proof']['source_object']['node_ids']==[11,12]
    index=write_geometry_index(city='frankfurt',objects=[row],border=BORDER,boundary_metadata=BOUNDARY,
        source_metadata=META,output=tmp_path/'index.json',pipeline_version=6)
    assert index['name_index']=={} and not index['semantic_matching_performed'] and not index['publication_ready']
    assert validate_geometry_index(index,city='frankfurt',border=BORDER,boundary_metadata=BOUNDARY,source_metadata=META)['passed']
    with pytest.raises(ValueError,match='proof'):
        write_geometry_index(city='frankfurt',objects=[row],border=BORDER,boundary_metadata=BOUNDARY,
            source_metadata=META,output=tmp_path/'old.json',pipeline_version=5)

@pytest.mark.parametrize('change',['name','ref','gate_type','stand_as_gate','stand_nodes','invented_nodes','unbarred','outside','cache','pbf'])
def test_reject_invented_facility_identity_or_geometry(change):
    raw=source();cache='b'*64;meta=META
    if change=='name':raw['tags']['name']='Invented airport gate'
    elif change=='ref':del raw['tags']['ref']
    elif change=='gate_type':raw['geometry']={'type':'LineString','coordinates':[[8.01,50.01],[8.02,50.02]]}
    elif change=='stand_as_gate':raw=source('stand');raw['tags']['aeroway']='gate'
    elif change=='stand_nodes':raw=source('stand');raw['node_ids']=[11]
    elif change=='invented_nodes':raw['node_ids']=[99]
    elif change=='unbarred':raw=source('crossing');raw['tags']['crossing:barrier']='no'
    elif change=='outside':raw['geometry']['coordinates']=[9,50]
    elif change=='cache':cache='unknown'
    elif change=='pbf':meta={'sha256':'unknown'}
    with pytest.raises(ValueError):native_facility_reference_object(source_object=raw,source_cache_sha256=cache,source_metadata=meta,border=BORDER)

@pytest.mark.parametrize('change',['source_hash','raw_coordinate','original_nodes','cache_hash','name','role','type','missing_proof'])
def test_readback_rejects_tampered_source_proof_or_output(change,tmp_path):
    idx=write_geometry_index(city='frankfurt',objects=[native(source('stand'))],border=BORDER,
        boundary_metadata=BOUNDARY,source_metadata=META,output=tmp_path/'i.json',pipeline_version=6)
    idx=json.loads(json.dumps(idx));row=idx['objects'][0];proof=row['native_facility_source_proof']
    if change=='source_hash':proof['source_pbf_sha256']='c'*64
    elif change=='raw_coordinate':proof['source_object']['geometry']['coordinates'][0][0]+=.00001
    elif change=='original_nodes':proof['source_object']['node_ids'][0]=999
    elif change=='cache_hash':proof['source_cache_sha256']='bad'
    elif change=='name':row['names']=['Invented C13']
    elif change=='role':row['roles']=['road']
    elif change=='type':row['native_facility_kind']='private_gate'
    else:del row['native_facility_source_proof']
    assert not validate_geometry_index(idx,city='frankfurt',border=BORDER,boundary_metadata=BOUNDARY,source_metadata=META)['passed']

@pytest.mark.parametrize('kind',['gate','stand','crossing'])
def test_facility_reference_keeps_all_original_members_and_forbids_primary_counts(kind):
    d,r,o=inputs(kind);derived=_derived_geometry(d,r,o,BORDER,'frankfurt')
    assert derived['type']=='GeometryCollection' and derived['geometry']['geometries']==[x['geometry'] for x in o.values()]
    assert derived['actual_event_position_known'] is False and derived['actual_event_extent_known'] is False
    assert derived['source_object_ids']==list(o) and 'count_point' not in derived
    row={'decision':d,'derived_geometry':derived};scene=_scene(r,row,{}, {},None)
    assert scene['coordinates'] is None and not scene['primary_for_count']
    derived['count_point']={'type':'Point','coordinates':[8.01,50.01]}
    assert _count_point(row) is None
    with pytest.raises(ValueError,match='cannot be a primary'):_scene(r,row,{}, {},r['location_id'])
    with pytest.raises(ValueError,match='source references only'):
        _derived_geometry({**d,'method':'osm_point','osm_object_groups':[[next(iter(o))]]},request(),o,BORDER,'frankfurt')

@pytest.mark.parametrize('change',['single_gate','mixed','different_ref','multiple_stands','transit','coordinates','district','point','groups','spread','missing_proof','invented_role'])
def test_facility_contract_rejects_incompatible_selection_or_source_precision(change):
    d,r,o=inputs()
    if change=='single_gate':d['osm_object_groups'][0]=d['osm_object_groups'][0][:1]
    elif change=='mixed':o['osm/node/2']=native(source('crossing',2))
    elif change=='different_ref':raw=source('gate',2);raw['tags']['ref']='Tor 24';o['osm/node/2']=native(raw)
    elif change=='multiple_stands':d,r,o=inputs('stand');new=native(source('stand',2));o[new['id']]=new;d['osm_object_groups'][0].append(new['id'])
    elif change=='transit':r['transit_route']={'mode':'bus','line':'63'}
    elif change=='coordinates':r['coordinates']=[8.01,50.01]
    elif change=='district':r.update(precision='district',geometry_task='checked_district_geometry_required')
    elif change=='point':r['precision']='point'
    elif change=='groups':d['osm_object_groups']=[[v] for v in o]
    elif change=='spread':raw=source('gate',2);raw['geometry']['coordinates']=[8.1,50.1];o['osm/node/2']=native(raw)
    elif change=='missing_proof':del o['osm/node/2']['native_facility_source_proof']
    elif change=='invented_role':o['osm/node/2']['roles']=['road']
    with pytest.raises(ValueError):_derived_geometry(d,r,o,BORDER,'frankfurt')
