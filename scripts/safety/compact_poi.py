"""Lossless native geometry transport, bounded approximation only for reviewed display circles.
No geocoding/GIS/source decisions. Read-only input, exclusively new output directory.
"""
from pathlib import Path
import argparse, hashlib, json, math, os, time, gzip
from collections import Counter

VERSION = 1
EARTH_RADIUS = 6378137.0
MAX_RADIAL_ERROR_M = 0.35

def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()

def sha(data):
    return hashlib.sha256(data).hexdigest()

def distance(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 2*EARTH_RADIUS*math.asin(min(1, math.sqrt(h)))

def compact(feature):
    p = feature['properties']; g = feature['geometry']; center = p.get('center')
    eligible = (p.get('geometry_mode') == '50m_circle' and p.get('boundary_clipped') is False
                and isinstance(center, list) and len(center) == 2
                and all(isinstance(x, (int,float)) and math.isfinite(x) for x in center)
                and abs(center[0]) <= 180 and abs(center[1]) < 85 and g.get('type') == 'Polygon'
                and len(g.get('coordinates', [])) == 1 and len(g['coordinates'][0]) == 33)
    if not eligible: return feature, None
    error = max(abs(distance(center, v)-50) for v in g['coordinates'][0])
    if error > MAX_RADIAL_ERROR_M: return feature, None
    p2 = dict(p, display_radius_m=50, compact_geometry_version=VERSION)
    # center is the already reviewed anchor, byte-for-byte numeric values unchanged.
    return dict(feature, geometry={'type':'Point','coordinates':center}, properties=p2), error

def run(source, target):
    started=time.perf_counter(); m=json.loads((source/'manifest.json').read_bytes()); old=source/m['generation']
    if target.exists(): raise ValueError('output must be a new directory')
    target.mkdir(parents=True); stage=target/'staging'; stage.mkdir()
    ids={}; native_hashes={}; counts=Counter(); totals=Counter(); files=[]; max_error=0
    for p in sorted(old.rglob('*')):
        if not p.is_file(): continue
        rel=p.relative_to(old); out=stage/rel; out.parent.mkdir(parents=True, exist_ok=True)
        raw=p.read_bytes(); totals['before_bytes']+=len(raw)
        if rel.parts[0]=='pois' and p.suffix=='.json':
            fc=json.loads(raw); converted=[]
            for f in fc['features']:
                sid=f['properties'].get('id')
                if not isinstance(sid,str) or not sid: raise ValueError('missing stable object id')
                original=sha(dump(f))
                if sid in ids and ids[sid]!=original: raise ValueError('duplicate stable ID has conflicting data: '+sid)
                if sid not in ids:
                    counts['unique_objects']+=1; counts['unique_'+f['properties']['geometry_mode']]+=1
                ids[sid]=original; counts['tile_rows']+=1
                compacted,error=compact(f)
                if error is not None:
                    counts['encoded_tile_rows']+=1; max_error=max(max_error,error)
                    if compacted['geometry']['coordinates']!=f['properties']['center']: raise AssertionError('center changed')
                else:
                    if dump(compacted)!=dump(f): raise AssertionError('native feature changed')
                    native_hashes[sid]=sha(dump(f['geometry']))
                converted.append(compacted)
            data=dump(dict(fc,features=converted)); out.write_bytes(data)
            totals['before_poi_bytes']+=len(raw); totals['after_poi_bytes']+=len(data)
            totals['before_poi_gzip_bytes']+=len(gzip.compress(raw,compresslevel=6,mtime=0))
            totals['after_poi_gzip_bytes']+=len(gzip.compress(data,compresslevel=6,mtime=0))
        else:
            os.link(p,out); data=raw
        totals['after_bytes']+=len(data)
        files.append({'path':str(rel),'source_sha256':sha(raw),'target_sha256':sha(data),'source_bytes':len(raw),'target_bytes':len(data)})
    # Content-address a new immutable generation, never repurpose a reviewed generation path.
    digest=sha(dump(files)); newgen=digest[:16]+'-'+m['generation'].split('-')[1]
    stage.rename(target/newgen)
    m['generation']=newgen; m['poi_encoding']='point-radius-v1'
    m['metadata']=dict(m['metadata'],transport_source_generation=old.name,transport_digest=digest)
    (target/'manifest.json').write_bytes(dump(m))
    counts['duplicate_rows']=counts['tile_rows']-counts['unique_objects']
    report={'schema_version':1,'source':str(source.resolve()),'source_manifest_sha256':sha((source/'manifest.json').read_bytes()),'source_generation':old.name,'target_generation':newgen,'counts':dict(counts),'sizes':dict(totals),'elapsed_seconds':time.perf_counter()-started,'max_reviewed_vertex_radial_difference_m':max_error,'max_32_segment_chord_error_m':50*(1-math.cos(math.pi/32)),'coordinate_quantization':'none; preserve all numeric values','native_geometry_changed':0,'membership_changed':0,'source_month_links_counts_changed':0,'native_geometry_hashes':native_hashes,'files':files,'publication_ready':False}
    (target/'transport-proof.json').write_bytes(dump(report))
    return {k:v for k,v in report.items() if k not in ('native_geometry_hashes','files')}

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--source',type=Path,required=True);a.add_argument('--out',type=Path,required=True)
    args=a.parse_args();print(json.dumps(run(args.source,args.out),indent=2))
