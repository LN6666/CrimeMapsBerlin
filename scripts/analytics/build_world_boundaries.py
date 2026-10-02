"""Build pinned, public-domain Natural Earth map units into static SVG paths.

No network access. Run with the source GeoJSON path and output .mjs path.
"""
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

SOURCE_SHA256 = 'b8d421aca6e9e08e8cdf09cc26af111cc3e0deba4fe915611d58ade71e8a4db0'
TOLERANCE = 0.12


def simplify(points):
    if len(points) < 4:
        return points
    a, b = points[0], points[-1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    scale = dx * dx + dy * dy
    def distance(p):
        t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / scale)) if scale else 0
        return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)
    i, dist = max(enumerate(map(distance, points[1:-1]), 1), key=lambda row: row[1])
    if dist <= TOLERANCE:
        return [a, b]
    return simplify(points[:i + 1])[:-1] + simplify(points[i:])


def build(source):
    groups = defaultdict(list)
    source_points = output_points = 0
    for feature in source['features']:
        props = feature['properties']
        if props['ISO_A2_EH'] == 'AQ':
            continue  # Polar continent omitted; AQ totals remain in ranking.
        code = props['ISO_A2_EH']
        if not re.fullmatch('[A-Z]{2}', code):
            code = ''  # No inferred parent assignment for disputed/unmapped units.
        geometry = feature['geometry']
        polygons = [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']
        for polygon in polygons:
            for ring in polygon:
                assert all(abs(a[0] - b[0]) <= 180 for a, b in zip(ring, ring[1:]))
                points = [(lon + 180, 90 - lat) for lon, lat in ring]
                source_points += len(points)
                reduced = simplify(points)
                if len(reduced) < 4:
                    reduced = points  # Keep small native islands, never add markers.
                output_points += len(reduced)
                integer = [(round(x * 100), round(y * 100)) for x, y in reduced]
                if integer[0] == integer[-1]:
                    integer.pop()
                steps = [(b[0] - a[0], b[1] - a[1]) for a, b in zip(integer, integer[1:]) if a != b]
                first = integer[0]
                groups[code].append(f'M{first[0]},{first[1]}' + ('l' + ' '.join(f'{dx},{dy}' for dx, dy in steps) if steps else '') + 'Z')
    paths = [{'code': code, 'd': ''.join(rings)} for code, rings in sorted(groups.items())]
    return paths, {'source_points': source_points, 'output_points': output_points, 'groups': len(paths)}


if __name__ == '__main__':
    source, out = map(Path, sys.argv[1:3])
    raw = source.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SOURCE_SHA256, 'Unexpected source version'
    paths, counts = build(json.loads(raw))
    header = '// Natural Earth 1:50m map units; public domain. See WORLD-MAP-SOURCES.md.\n'
    out.write_text(header + 'export const WORLD_PATHS = Object.freeze(' + json.dumps(paths, separators=(',', ':')) + '.map(Object.freeze));\n')
    print(json.dumps({**counts, 'bytes': out.stat().st_size, 'sha256': hashlib.sha256(out.read_bytes()).hexdigest()}))
