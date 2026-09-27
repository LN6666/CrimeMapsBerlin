"""Small immutable JSON tiles for static hosting; no server or full-city browser parse."""

import math
from collections import defaultdict

from shapely.geometry import shape

DX = 0.04
DY = 0.025


def tiles(features):
    buckets = defaultdict(list)
    for f in features:
        xmin, ymin, xmax, ymax = shape(f["geometry"]).bounds
        for x in range(math.floor(xmin / DX), math.floor(xmax / DX) + 1):
            for y in range(math.floor(ymin / DY), math.floor(ymax / DY) + 1):
                buckets[f"{x}_{y}"].append(f)
    return {key: {"type": "FeatureCollection", "features": rows} for key, rows in buckets.items()}
