"""Local OSM extraction: POI geometry, named streets, compact road context."""

import hashlib
import json
from pathlib import Path

import osmium
from shapely.geometry import LineString, mapping, shape

from crimemapsberlin.spatial import classify_poi

ROOT = Path("data/raw/safety")


class Places(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.elements = []
        self.streets = []
        self.roads = []
        self.factory = osmium.geom.GeoJSONFactory()

    def node(self, n):
        tags = dict(n.tags)
        if classify_poi(tags) and n.location.valid():
            self.elements.append(
                {"type": "node", "id": n.id, "lon": n.location.lon, "lat": n.location.lat, "tags": tags}
            )

    def way(self, w):
        tags = dict(w.tags)
        if not classify_poi(tags) and not tags.get("highway"):
            return
        try:
            coords = [(n.lon, n.lat) for n in w.nodes]
        except osmium.InvalidLocationError:
            return
        if len(coords) < 2:
            return
        if tags.get("highway"):
            line = LineString(coords)
            if tags.get("name"):
                self.streets.append({"name": tags["name"], "geometry": mapping(line)})
            if tags["highway"] in {
                "motorway",
                "trunk",
                "primary",
                "secondary",
                "tertiary",
                "residential",
                "living_street",
                "pedestrian",
            }:
                self.roads.append(
                    {
                        "type": "Feature",
                        "geometry": mapping(line.simplify(0.00003)),
                        "properties": {"name": tags.get("name", ""), "class": tags["highway"]},
                    }
                )
        if classify_poi(tags):
            self.elements.append(
                {
                    "type": "way",
                    "id": w.id,
                    "tags": tags,
                    "geometry": [{"lon": x, "lat": y} for x, y in coords],
                }
            )

    def area(self, a):
        if a.from_way():
            return  # closed ways already handled
        tags = dict(a.tags)
        if not classify_poi(tags):
            return
        try:
            g = json.loads(self.factory.create_multipolygon(a))
        except RuntimeError:
            return
        if shape(g).is_valid:
            self.elements.append({"type": "relation", "id": a.orig_id(), "tags": tags, "geojson_geometry": g})


if __name__ == "__main__":
    src = ROOT / "berlin.osm.pbf"
    if not src.exists():
        raise SystemExit("Run scripts/safety/fetch_osm.py first")
    places = Places()
    places.apply_file(str(src), locations=True)
    dest = ROOT / "berlin-pois.json"
    dest.write_text(json.dumps({"elements": places.elements}))
    (ROOT / "streets.json").write_text(json.dumps(places.streets))
    (ROOT / "roads.json").write_text(
        json.dumps({"type": "FeatureCollection", "features": places.roads}, separators=(",", ":"))
    )
    provenance = ROOT / "berlin.osm.source.json"
    if not provenance.exists():
        raise SystemExit("Missing source manifest; fetch_osm.py records provenance")
    meta = json.loads(provenance.read_text())
    if hashlib.sha256(src.read_bytes()).hexdigest() != meta["sha256"]:
        raise SystemExit("OSM input hash differs from provenance")
    meta.update(elements=len(places.elements), streets=len(places.streets), roads=len(places.roads))
    dest.with_suffix(".source.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))
