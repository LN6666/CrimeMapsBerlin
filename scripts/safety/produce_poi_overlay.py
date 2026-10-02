"""Tile rules-approved POI assemblies; encode display circles after tile assignment.

No source, geocoding, metric geometry, associations, or count computation. This
produces a POI overlay, not a complete city publication. Inputs remain read-only.
"""
import argparse
from collections import Counter, defaultdict
import gzip
import json
import math
from pathlib import Path
import re
import time

from compact_poi import compact, dump, sha

DX, DY = 0.04, 0.025  # Existing crimemapsberlin.tiles grid.


def positions(geometry):
    if geometry is None:
        return
    if geometry.get('type') == 'GeometryCollection':
        for child in geometry.get('geometries', []):
            yield from positions(child)
        return
    def walk(value):
        if not isinstance(value, list):
            raise ValueError('invalid coordinates')
        if len(value) >= 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value[:2]):
            lon, lat = value[:2]
            if not math.isfinite(lon) or not math.isfinite(lat) or abs(lon) > 180 or abs(lat) > 90:
                raise ValueError('invalid geographic position')
            yield lon, lat
        else:
            for child in value:
                yield from walk(child)
    yield from walk(geometry.get('coordinates', []))


def memberships(feature):
    coords = list(positions(feature.get('geometry')))
    if not coords:
        return []
    xs, ys = zip(*coords)
    x0, x1 = math.floor(min(xs)/DX), math.floor(max(xs)/DX)
    y0, y1 = math.floor(min(ys)/DY), math.floor(max(ys)/DY)
    if (x1-x0+1)*(y1-y0+1) > 10000:
        raise ValueError('unbounded feature tile extent')
    return [f'{x}_{y}' for x in range(x0, x1+1) for y in range(y0, y1+1)]


def search_position(feature):
    p, g = feature['properties'], feature.get('geometry') or {}
    center = p.get('center')
    origin = 'existing_properties_center'
    if center is None and g.get('type') == 'Point':
        center = g.get('coordinates')
        origin = 'existing_native_point_coordinates'
    if (isinstance(center, list) and len(center) == 2 and
        all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in center) and
        abs(center[0]) <= 180 and abs(center[1]) <= 90):
        return center, origin
    return None, None


def produce(entry, target):
    started = time.perf_counter()
    city = entry['city']
    if not isinstance(city, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,79}', city):
        raise ValueError('unsafe city identifier')
    source = Path(entry['assembly_pois_path'])
    receipt_path = Path(entry['native_coverage_receipt_path'])
    raw, receipt_raw = source.read_bytes(), receipt_path.read_bytes()
    if sha(raw) != entry['assembly_pois_sha256'] or sha(receipt_raw) != entry['native_coverage_receipt_sha256']:
        raise ValueError(f'{city}: rules input hash changed')
    receipt, assembly = json.loads(receipt_raw), json.loads(raw)
    if receipt['assembly_pois_sha256'] != sha(raw) or receipt['city'] != city:
        raise ValueError(f'{city}: receipt does not bind assembly')
    if not receipt['existing_native_fields_geometry_preserved'] or receipt['automatic_source_association_run'] or receipt['source_links_or_count_points_created']:
        raise ValueError(f'{city}: unexpected source/geometry stage')
    features = assembly['features']
    if len(features) != receipt['display_native_object_count']:
        raise ValueError(f'{city}: count mismatch')
    if target.exists():
        raise ValueError('output must be a new directory')
    target.mkdir(parents=True)
    buckets, originals, encoded, feature_proofs = defaultdict(list), {}, {}, []
    unlocated, search, counts, sizes = [], [], Counter(), Counter()
    max_error = 0
    for feature in features:
        props = feature['properties']
        sid, kind = props.get('id'), props.get('kind')
        if not isinstance(sid, str) or not sid or sid in originals:
            raise ValueError(f'{city}: absent or duplicate stable ID')
        if not isinstance(kind, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,79}', kind):
            raise ValueError(f'{city}: unsafe original kind')
        originals[sid] = feature
        keys = memberships(feature)  # Always original bounds, before Point encoding.
        result, error = compact(feature) if feature.get('geometry') else (feature, None)
        encoded[sid] = result
        if error is None:
            if dump(result) != dump(feature):
                raise AssertionError('native feature changed')
            counts['unchanged_native_or_clipped_objects'] += 1
        else:
            max_error = max(max_error, error)
            counts['encoded_display_circles'] += 1
            restored = dict(result, geometry=feature['geometry'], properties={k:v for k,v in result['properties'].items() if k not in ('display_radius_m', 'compact_geometry_version')})
            if dump(restored) != dump(feature):
                raise AssertionError('non-display metadata changed')
        for key in keys:
            buckets[f'{kind}/{key}'].append(sid)
        if not keys:
            unlocated.append(result)
        feature_proofs.append({'id':sid, 'original_sha256':sha(dump(feature)), 'encoded_sha256':sha(dump(result)), 'original_geometry_sha256':sha(dump(feature.get('geometry'))), 'location_geometry_sha256':sha(dump(feature.get('location_geometry'))), 'tile_memberships':keys})
        center, origin = search_position(feature)
        if center is not None and props.get('name') and props['name'] != kind:
            search.append({'id':sid, 'name':props['name'], 'aliases':props.get('aliases', []), 'kind':kind, 'scope_category':props.get('scope_category', kind), 'center':center})
            counts['search_'+origin] += 1
        elif center is None:
            counts['no_existing_search_position'] += 1
    files = []
    observed_memberships = defaultdict(list)
    for key, ids in sorted(buckets.items()):
        before = dump({'type':'FeatureCollection', 'features':[originals[sid] for sid in ids]})
        after = dump({'type':'FeatureCollection', 'features':[encoded[sid] for sid in ids]})
        rel = f'pois/{key}.json'
        path = target/rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(after)
        # Read actual output, not only the in-memory conversion.
        parsed = json.loads(path.read_bytes())['features']
        if [f['properties']['id'] for f in parsed] != ids:
            raise AssertionError('tile membership changed')
        for f in parsed:
            sid = f['properties']['id']
            if dump(f) != dump(encoded[sid]):
                raise AssertionError('written feature differs')
            observed_memberships[sid].append(key.split('/')[1])
        sizes['before_tiled_poi_bytes'] += len(before)
        sizes['after_tiled_poi_bytes'] += len(after)
        sizes['before_tiled_poi_gzip_bytes'] += len(gzip.compress(before, compresslevel=6, mtime=0))
        sizes['after_tiled_poi_gzip_bytes'] += len(gzip.compress(after, compresslevel=6, mtime=0))
        files.append({'path':rel, 'before_sha256':sha(before), 'after_sha256':sha(after), 'membership_sha256':sha(dump(ids)), 'objects':len(ids), 'before_bytes':len(before), 'after_bytes':len(after)})
    for proof in feature_proofs:
        if sorted(observed_memberships[proof['id']]) != sorted(proof['tile_memberships']):
            raise AssertionError('original extent membership changed')
    counts.update(unique_objects=len(originals), tile_rows=sum(len(ids) for ids in buckets.values()), tiles=len(buckets), unlocated_objects=len(unlocated), search_records=len(search))
    counts['duplicate_tile_rows'] = counts['tile_rows']-counts['unique_objects']+counts['unlocated_objects']
    sizes['input_assembly_file_bytes'] = len(raw)
    sizes['before_unique_canonical_bytes'] = len(dump(assembly))
    sizes['after_unique_canonical_bytes'] = len(dump(dict(assembly, features=list(encoded.values()))))
    extras = {'search.json':search, 'tile-index.json':{'pois':sorted(buckets)}, 'unlocated.json':{'type':'FeatureCollection', 'features':unlocated}, 'feature-proof.json':feature_proofs}
    for rel, value in extras.items():
        data = dump(value)
        (target/rel).write_bytes(data)
        files.append({'path':rel, 'after_sha256':sha(data), 'after_bytes':len(data)})
    digest = sha(dump(files))
    fragment = {'overlay_schema_version':1, 'city':city, 'transport_digest':digest, 'tile_size':[DX,DY], 'tile_index':{'pois':sorted(buckets)}, 'poi_count':len(originals), 'poi_encoding':'point-radius-v1', 'poi_scope_groups':receipt['poi_scope_groups'], 'source_assembly_sha256':sha(raw), 'source_rules_receipt_sha256':sha(receipt_raw), 'publication_ready':False, 'complete_city_manifest':False, 'requires_migration_source_month_road_adapter':True}
    (target/'manifest-fragment.json').write_bytes(dump(fragment))
    report = {'schema_version':1, 'city':city, 'source':str(source.resolve()), 'source_assembly_sha256':sha(raw), 'source_rules_receipt_sha256':sha(receipt_raw), 'transport_digest':digest, 'counts':dict(counts), 'sizes':dict(sizes), 'max_old_vertex_radial_difference_m':max_error, 'tile_grid_source':'existing crimemapsberlin.tiles DX/DY; literal original geometry bounds before encoding', 'native_geometry_changed':0, 'location_geometry_changed':0, 'original_kind_id_metadata_changed':0, 'original_membership_changed':0, 'coordinates_quantized':0, 'new_source_links_count_points_or_associations':0, 'source_and_month_data_read_or_modified':False, 'publication_ready':False, 'elapsed_seconds':time.perf_counter()-started, 'files':files}
    (target/'receipt.json').write_bytes(dump(report))
    print(json.dumps({'city':city, 'counts':dict(counts), 'sizes':dict(sizes)}, ensure_ascii=False), flush=True)
    return {k:v for k,v in report.items() if k != 'files'}


def run(matrix, out):
    if out.exists():
        raise ValueError('output must be a new directory')
    out.mkdir(parents=True)
    raw = matrix.read_bytes()
    entries = json.loads(raw)['cities']
    reports = [produce(entry, out/entry['city']) for entry in entries]
    counts, sizes = Counter(), Counter()
    for report in reports:
        counts.update(report['counts']); sizes.update(report['sizes'])
    result = {'schema_version':1, 'input_matrix_sha256':sha(raw), 'city_count':len(reports), 'counts':dict(counts), 'sizes':dict(sizes), 'cities':reports, 'publication_ready':False, 'complete_city_bundles':False}
    (out/'size-report.json').write_bytes(dump(result))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--matrix', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    result = run(args.matrix, args.out)
    print(json.dumps({k:v for k,v in result.items() if k != 'cities'}, indent=2))
