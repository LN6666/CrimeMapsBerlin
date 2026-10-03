#!/usr/bin/env python3
"""Apply CSP to built HTML, allowing only reviewed maps and optional GoatCounter."""
import argparse
import html
import re
from pathlib import Path
from urllib.parse import urlsplit

def policy(map_origins=(), goatcounter=False):
    for value in map_origins:
        u = urlsplit(value)
        if u.scheme != "https" or not u.hostname or u.username or u.password or u.port not in {None, 443} or u.path or u.query or u.fragment or not re.fullmatch(r"[a-z0-9.-]+", u.hostname) or value != f"https://{u.hostname}":
            raise ValueError("Map must be an exact lowercase HTTPS DNS origin")
    approved_maps = {"https://vector.openstreetmap.org", "https://demotiles.maplibre.org", "https://tiles.openfreemap.org"}
    if any(value not in approved_maps for value in map_origins):
        raise ValueError("Map origin must be explicitly reviewed and allowlisted")
    maps = " " + " ".join(sorted(set(map_origins))) if map_origins else ""
    script = " https://gc.zgo.at" if goatcounter else ""
    count = " https://ryoushunnei.goatcounter.com/count" if goatcounter else ""
    return "; ".join([
        "default-src 'none'", "script-src 'self'" + script,
        "worker-src 'self'", "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob: https://tile.openstreetmap.org https://gdi.berlin.de" + maps,
        "connect-src 'self' https://tile.openstreetmap.org https://gdi.berlin.de" + maps + count,
        "font-src 'self'", "base-uri 'none'", "object-src 'none'", "form-action 'none'",
        "frame-src 'none'",
    ])

def apply(path, map_origins=(), goatcounter=False):
    text = path.read_text()
    match = re.compile(r'<meta\s+http-equiv="Content-Security-Policy"\s+content="[^"]*"\s*/?>', re.I)
    if len(match.findall(text)) != 1:
        raise ValueError("Expected exactly one CSP meta")
    text = match.sub('<meta http-equiv="Content-Security-Policy" content="' + html.escape(policy(map_origins, goatcounter), quote=True) + '" />', text)
    path.write_text(text)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--html", required=True, type=Path)
    p.add_argument("--map-origin", action="append", default=[])
    p.add_argument("--goatcounter", action="store_true")
    a = p.parse_args()
    apply(a.html, a.map_origin, a.goatcounter)
