"""Local OSM extraction: POI geometry, named streets, compact road context."""

import argparse
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
        self.localities = []
        self.addresses = []
        self.factory = osmium.geom.GeoJSONFactory()

    def node(self, n):
        tags = dict(n.tags)
        if tags.get("addr:street") and tags.get("addr:housenumber") and n.location.valid():
            self.addresses.append(
                dict(
                    id=f"osm/node/{n.id}",
                    street=tags["addr:street"],
                    number=tags["addr:housenumber"],
                    coordinates=[n.location.lon, n.location.lat],
                )
            )
        if classify_poi(tags) and n.location.valid():
            self.elements.append(
                {"type": "node", "id": n.id, "lon": n.location.lon, "lat": n.location.lat, "tags": tags}
            )

    def way(self, w):
        tags = dict(w.tags)
        address = tags.get("addr:street") and tags.get("addr:housenumber")
        if not classify_poi(tags) and not tags.get("highway") and not address:
            return
        try:
            coords = [(n.lon, n.lat) for n in w.nodes]
        except osmium.InvalidLocationError:
            return
        if len(coords) < 2:
            return
        if address and coords[0] == coords[-1] and len(coords) >= 4:
            from shapely.geometry import Polygon

            polygon = Polygon(coords)
            if polygon.is_valid:
                point = polygon.representative_point()
                self.addresses.append(
                    dict(
                        id=f"osm/way/{w.id}",
                        street=tags["addr:street"],
                        number=tags["addr:housenumber"],
                        coordinates=[point.x, point.y],
                    )
                )
        if tags.get("highway"):
            line = LineString(coords)
            if tags.get("name"):
                self.streets.append(
                    {
                        "id": f"osm/way/{w.id}",
                        "name": tags["name"],
                        "highway": tags["highway"],
                        "geometry": mapping(line),
                    }
                )
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
        tags = dict(a.tags)
        locality = tags.get("boundary") == "administrative" and tags.get("admin_level") in {"9", "10"}
        if not locality and (a.from_way() or not classify_poi(tags)):
            return
        try:
            g = json.loads(self.factory.create_multipolygon(a))
        except RuntimeError:
            return
        if not shape(g).is_valid:
            return
        if locality and tags.get("name"):
            self.localities.append(
                dict(
                    id=f"osm/{'way' if a.from_way() else 'relation'}/{a.orig_id()}",
                    name=tags["name"],
                    admin_level=tags["admin_level"],
                    geometry=g,
                )
            )
        elif not a.from_way():
            self.elements.append({"type": "relation", "id": a.orig_id(), "tags": tags, "geojson_geometry": g})


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--city", choices=("berlin", "hamburg"), default="berlin")
    args = p.parse_args()
    city_root = ROOT if args.city == "berlin" else ROOT / "cities" / args.city
    src = city_root / f"{args.city}.osm.pbf"
    if not src.exists():
        raise SystemExit(f"Run scripts/safety/fetch_osm.py --city {args.city} first")
    provenance = city_root / f"{args.city}.osm.source.json"
    if not provenance.exists():
        raise SystemExit("Missing source manifest; fetch_osm.py records provenance")
    meta = json.loads(provenance.read_text())
    if hashlib.sha256(src.read_bytes()).hexdigest() != meta["sha256"]:
        raise SystemExit("OSM input hash differs from provenance")
    places = Places()
    places.apply_file(str(src), locations=True)
    dest = city_root / f"{args.city}-pois.json"
    dest.write_text(json.dumps({"elements": places.elements}))
    (city_root / "streets.json").write_text(json.dumps(places.streets))
    (city_root / "localities.json").write_text(json.dumps(places.localities))
    (city_root / "addresses.json").write_text(json.dumps(places.addresses))
    (city_root / "roads.json").write_text(
        json.dumps({"type": "FeatureCollection", "features": places.roads}, separators=(",", ":"))
    )
    meta.update(
        elements=len(places.elements),
        streets=len(places.streets),
        roads=len(places.roads),
        localities=len(places.localities),
        addresses=len(places.addresses),
        extraction_version=2,
    )
    dest.with_suffix(".source.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))
