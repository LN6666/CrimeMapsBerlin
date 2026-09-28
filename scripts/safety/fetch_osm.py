"""Download a supported Geofabrik extract with checksum; retain last good input."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2] / "data/raw/safety"
EXTRACTS = {
    "berlin": "https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf",
    "hamburg": "https://download.geofabrik.de/europe/germany/hamburg-latest.osm.pbf",
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--city", choices=EXTRACTS, default="berlin")
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()
    city_root = ROOT if args.city == "berlin" else ROOT / "cities" / args.city
    city_root.mkdir(parents=True, exist_ok=True)
    url = EXTRACTS[args.city]
    dest = city_root / f"{args.city}.osm.pbf"
    if dest.exists() and not args.refresh:
        print("Using local OSM input")
        return
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        r = client.get(url + ".md5")
        r.raise_for_status()
        expected = r.text.split()[0]
        if len(expected) != 32:
            raise ValueError("Invalid published checksum")
        part = dest.with_suffix(".pbf.part")
        md5 = hashlib.md5()
        sha = hashlib.sha256()
        with client.stream("GET", url) as response, part.open("wb") as output:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                output.write(chunk)
                md5.update(chunk)
                sha.update(chunk)
            modified = response.headers.get("last-modified")
        if md5.hexdigest() != expected:
            part.unlink()
            raise ValueError("Checksum mismatch; previous extract retained")
        part.replace(dest)
        meta = dict(
            url=url,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            snapshot=modified,
            sha256=sha.hexdigest(),
            license="ODbL-1.0",
            attribution="© OpenStreetMap contributors / Geofabrik",
        )
        (city_root / f"{args.city}.osm.source.json").write_text(json.dumps(meta, indent=2))
        print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
