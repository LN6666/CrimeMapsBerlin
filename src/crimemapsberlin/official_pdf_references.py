"""Bind reviewed Hamburg police PDFs and derive declared horizontal references.

The caller supplies explicit LLM choices. No text is classified or matched to a
venue; a stated circle centre is never returned as an incident/count point.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from pyproj import Geod
from shapely.geometry import Polygon, mapping

METHOD = "official_pdf_horizontal_circle_reference"


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def _text(value):
    return " ".join(value.split())


def _bound(spec):
    if not isinstance(spec, dict) or set(spec) != {"file", "sha256"}:
        raise ValueError("PDF reference needs an exact file/hash binding")
    try:
        raw = Path(spec["file"]).read_bytes()
    except (OSError, TypeError) as exc:
        raise ValueError("Bound PDF reference file unavailable") from exc
    if hashlib.sha256(raw).hexdigest() != spec["sha256"]:
        raise ValueError("Stale bound PDF reference file")
    return raw


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a" and dict(attrs).get("href"):
            self.links.append(dict(attrs)["href"])


def validate_document_binding(binding, source, city, source_id):
    """Read and check one explicit attachment bundle, without network access."""
    from .hamburg import article_body

    if city != "hamburg" or source["id"] != source_id:
        raise ValueError("PDF reference belongs to a different city/source")
    if not isinstance(binding, dict) or set(binding) != {
        "manifest_file", "manifest_sha256", "evidence_sources"
    }:
        raise ValueError("PDF reference binding is incomplete")
    manifest = json.loads(_bound({"file": binding["manifest_file"],
                                 "sha256": binding["manifest_sha256"]}))
    if manifest.get("schema_version") != 1 or manifest.get("city") != city:
        raise ValueError("PDF reference manifest city/schema mismatch")
    doc = manifest.get("document")
    if not isinstance(doc, dict):
        raise TypeError("PDF reference needs one reviewed document")
    if (doc.get("parent_source_id") != source_id
            or doc.get("parent_source_url") != source["url"]
            or doc.get("parent_source_sha256") != source["sha256"]
            or doc.get("publisher") != "Polizei Hamburg"):
        raise ValueError("PDF reference has a stale parent or publisher")
    parent = urlsplit(source["url"])
    attachment = urlsplit(doc.get("attachment_url", ""))
    final = urlsplit(doc.get("final_url", ""))
    if (parent.scheme != "https" or parent.netloc != "www.presseportal.de"
            or parent.path != f"/blaulicht/pm/6337/{source_id}"
            or attachment.scheme != "https" or attachment.netloc != parent.netloc
            or not attachment.path.startswith("/download/document/")
            or final.scheme != "https" or final.netloc != "cache.pressmailing.net"
            or not final.path.startswith("/content/")):
        raise ValueError("PDF reference URL is not the declared police attachment")
    html = _bound(doc["parent_html"]).decode()
    body = article_body(html)
    if body != _text(source["body"]) or hashlib.sha256(body.encode()).hexdigest() != source["sha256"]:
        raise ValueError("Captured police HTML differs from the current source")
    links = _Links()
    links.feed(html)
    if doc["attachment_url"] not in links.links:
        raise ValueError("Reviewed PDF is not linked by the captured police page")
    pdf = _bound(doc["pdf"])
    if not pdf.startswith(b"%PDF-"):
        raise ValueError("Reference document is not a captured PDF")
    text = _text(_bound(doc["extracted_text"]).decode())
    image = _bound(doc["page_image"])
    if not image.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("PDF page inspection needs the bound PNG")
    robots = doc.get("robots")
    if not isinstance(robots, list) or len(robots) != 2:
        raise ValueError("Both police and redirected media robots must be bound")
    allowed_targets = []
    for row in robots:
        parser = RobotFileParser()
        parser.parse(_bound(row["snapshot"]).decode().splitlines())
        for url in row["targets"]:
            if not parser.can_fetch("CrimeMapsBerlin/0.1", url):
                raise ValueError("Robots denies the bound PDF acquisition")
            allowed_targets.append(url)
    if sorted(allowed_targets) != sorted([source["url"], doc["attachment_url"], doc["final_url"]]):
        raise ValueError("Robots targets differ from the exact capture URLs")
    review = json.loads(_bound(doc["review"]))
    if (review.get("source_id") != source_id or review.get("city") != city
            or review.get("source_sha256") != source["sha256"]
            or review.get("attachment_sha256") != doc["pdf"]["sha256"]
            or review.get("extracted_text_sha256") != doc["extracted_text"]["sha256"]
            or review.get("whole_pdf_read") is not True
            or review.get("whole_page_visually_reviewed") is not True
            or type(review.get("count_contribution")) is not int
            or review.get("count_contribution") != 0
            or not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip()):
        raise ValueError("PDF review is incomplete or stale")
    quotes = review.get("evidence_quotes")
    if not isinstance(quotes, list) or not quotes or any(
        not isinstance(q, str) or not q.strip() or _text(q) not in text for q in quotes
    ):
        raise ValueError("PDF review quote is not in the individual document")
    return doc, review, text


def validate_pdf_referenced_decision(value, *, source, city, source_id, primary_validator):
    """Keep document quotes separate; all other evidence stays source-backed."""
    doc, review, text = validate_document_binding(value["source_document_binding"], source, city, source_id)
    primary = copy.deepcopy(value)
    binding = primary.pop("source_document_binding")
    origins = binding["evidence_sources"]
    if not isinstance(origins, dict) or not origins:
        raise ValueError("PDF reference needs explicit individual quote origins")
    grouped = {}
    for path, document_id in origins.items():
        if (document_id != doc["document_id"] or not re.fullmatch(
                r"/scene_inventory/(incidents|formal_locations)/\d+/evidence_quotes/\d+", path)):
            raise ValueError("PDF quote has an invalid individual document origin")
        parts = path.strip("/").split("/")
        try:
            container = primary[parts[0]][parts[1]][int(parts[2])][parts[3]]
            ix = int(parts[4]); quote = container[ix]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("PDF quote origin points to a missing evidence field") from exc
        if quote not in review["evidence_quotes"] or _text(quote) not in text:
            raise ValueError("PDF quote crosses documents or is unreviewed")
        grouped.setdefault(tuple(parts[:4]), []).append(ix)
    for parts, indices in grouped.items():
        container = primary[parts[0]][parts[1]][int(parts[2])][parts[3]]
        for ix in sorted(indices, reverse=True):
            del container[ix]
        if not container:
            raise ValueError("Each supplemented stage/location retains primary evidence")
    # The normal validator rejects undeclared PDF quotes and cross-body splices.
    if primary_validator(primary, source, city, source_id) != primary:
        raise ValueError("PDF primary decision is not canonical")
    return copy.deepcopy(value)


def derive_pdf_circle_reference(decision, request, border, city):
    """Calculate the stated horizontal circle; no height/legal/count inference."""
    if (decision.get("method") != METHOD or decision.get("verdict") != "resolved"
            or decision.get("osm_object_groups") != [] or request.get("precision") != "area"
            or request.get("city_scope") != "in_city" or request.get("coordinates") is not None
            or request.get("role") not in {"operation", "background"}
            or request.get("poi_contexts") != [] or request.get("transit_route") is not None
            or request.get("transit_review", {}).get("status") != "not_applicable"):
        raise ValueError("PDF circle is an area management reference, never an event point")
    from .hamburg import article_body

    binding = request["source_document_binding"]
    manifest = json.loads(_bound({"file": binding["manifest_file"],
                                 "sha256": binding["manifest_sha256"]}))
    body = article_body(_bound(manifest["document"]["parent_html"]).decode())
    doc, review, text = validate_document_binding(binding, {
        "id": request["source_id"], "url": request["source_url"],
        "sha256": request["source_sha256"], "body": body,
    }, city, request["source_id"])
    claim = review.get("horizontal_circle")
    if not isinstance(claim, dict) or claim.get("datum_assumption") != "WGS84":
        raise ValueError("PDF circle needs an explicit datum assumption")
    lat, lon = claim.get("latitude_dms"), claim.get("longitude_dms")
    if any(not isinstance(v, list) or len(v) != 3 or any(type(x) is not int for x in v)
           for v in [lat, lon]):
        raise ValueError("PDF circle needs explicit degree/minute/second choices")
    if not (0 <= lat[0] <= 90 and 0 <= lon[0] <= 180
            and all(0 <= x < 60 for x in lat[1:] + lon[1:])):
        raise ValueError("PDF circle has invalid angular units")
    radius = claim.get("radius_nm")
    if type(radius) is not int or radius <= 0 or radius > 50:
        raise ValueError("PDF circle radius must be explicitly stated in nautical miles")
    coordinate_quote = f"{lat[0]:02d} {lat[1]:02d} {lat[2]:02d} N {lon[0]:03d} {lon[1]:02d} {lon[2]:02d} E"
    radius_quote = f"EDR ( {radius} NM ) = ROT"
    if any(q not in review["evidence_quotes"] or q not in text for q in [coordinate_quote, radius_quote]):
        raise ValueError("Circle choices differ from the reviewed PDF coordinates/radius")
    if (claim.get("height_known") is not False or claim.get("full_legal_definition_verified") is not False
            or claim.get("centre_is_incident_point") is not False):
        raise ValueError("PDF horizontal reference must retain height/legal/incident uncertainty")
    latitude = lat[0] + lat[1] / 60 + lat[2] / 3600
    longitude = lon[0] + lon[1] / 60 + lon[2] / 3600
    geod = Geod(ellps="WGS84")
    coords = [geod.fwd(longitude, latitude, angle / 2, radius * 1852)[:2]
              for angle in range(720)]
    coords.append(coords[0])
    polygon = Polygon(coords)
    if not polygon.is_valid or not border.covers(polygon):
        raise ValueError("PDF circle is invalid or exceeds the reviewed city display boundary")
    geometry = json.loads(json.dumps(mapping(polygon)))
    return {"type": "Polygon", "geometry": geometry, "geometry_sha256": _digest(geometry),
            "source_object_ids": [], "source_document_id": doc["document_id"],
            "source_attachment_sha256": doc["pdf"]["sha256"],
            "geometry_usage": "official_attachment_horizontal_reference_only",
            "geodesic_model": "WGS84_assumed_not_declared_in_attachment",
            "radius_nm": radius, "radius_metres": radius * 1852,
            "sampling_segments": 720, "height_known": False,
            "full_legal_definition_verified": False, "actual_event_position_known": False}
