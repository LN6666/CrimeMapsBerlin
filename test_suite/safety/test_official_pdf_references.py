"""Synthetic PDF provenance and declared-circle geometry checks."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from pyproj import Geod
from shapely.geometry import box

from crimemapsberlin.official_pdf_references import (
    METHOD,
    derive_pdf_circle_reference,
    validate_pdf_referenced_decision,
)


def bound(path, value):
    raw = value if isinstance(value, bytes) else json.dumps(value).encode()
    path.write_bytes(raw)
    return {"file": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


@pytest.fixture
def bundle(tmp_path):
    url = "https://www.presseportal.de/blaulicht/pm/6337/11"
    attachment = "https://www.presseportal.de/download/document/synthetic.pdf"
    final = "https://cache.pressmailing.net/content/synthetic/map.pdf"
    body = "Synthetic historical management notice with no actual offence."
    source = {"id": "11", "url": url, "body": body,
              "sha256": hashlib.sha256(body.encode()).hexdigest()}
    html = (f'<article class="story"><p class="customer">Polizei Hamburg</p>'
            f'<h1>Synthetic</h1><p>{body}</p><a href="{attachment}">Map</a></article>').encode()
    quotes = ["EDR ( 1 NM ) = ROT", "53 30 00 N 010 00 00 E", "Synthetic date UTC"]
    doc = {"document_id": "synthetic-pdf", "parent_source_id": "11",
           "parent_source_url": url, "parent_source_sha256": source["sha256"],
           "publisher": "Polizei Hamburg", "attachment_url": attachment, "final_url": final,
           "parent_html": bound(tmp_path / "parent.html", html),
           "pdf": bound(tmp_path / "map.pdf", b"%PDF-1.7 Synthetic only"),
           "extracted_text": bound(tmp_path / "text.txt", "\n".join(quotes).encode()),
           "page_image": bound(tmp_path / "page.png", b"\x89PNG\r\n\x1a\nSynthetic only")}
    doc["robots"] = [{"snapshot": bound(tmp_path / "police-robots.txt", b"User-agent: *\nAllow: /\n"),
                      "targets": [url, attachment]},
                     {"snapshot": bound(tmp_path / "media-robots.txt", b"User-agent: *\nAllow: /\n"),
                      "targets": [final]}]
    review = {"source_id": "11", "city": "hamburg", "source_sha256": source["sha256"],
              "attachment_sha256": doc["pdf"]["sha256"],
              "extracted_text_sha256": doc["extracted_text"]["sha256"],
              "whole_pdf_read": True, "whole_page_visually_reviewed": True,
              "count_contribution": 0, "reviewer": "Synthetic test author", "evidence_quotes": quotes,
              "horizontal_circle": {"latitude_dms": [53, 30, 0], "longitude_dms": [10, 0, 0],
                                    "radius_nm": 1, "datum_assumption": "WGS84", "height_known": False,
                                    "full_legal_definition_verified": False, "centre_is_incident_point": False}}
    doc["review"] = bound(tmp_path / "review.json", review)
    manifest = {"schema_version": 1, "city": "hamburg", "document": doc}
    spec = bound(tmp_path / "manifest.json", manifest)
    binding = {"manifest_file": spec["file"], "manifest_sha256": spec["sha256"],
               "evidence_sources": {"/scene_inventory/incidents/0/evidence_quotes/1": "synthetic-pdf"}}
    decision = {"scene_inventory": {"incidents": [{"evidence_quotes": [body, quotes[0]]}]},
                "source_document_binding": binding}
    return source, decision, manifest, review


def refresh(bundle):
    _, decision, manifest, review = bundle
    doc = manifest["document"]
    doc["review"] = bound(Path(doc["review"]["file"]), review)
    spec = bound(Path(decision["source_document_binding"]["manifest_file"]), manifest)
    decision["source_document_binding"]["manifest_sha256"] = spec["sha256"]


def validate(bundle):
    source, decision, _, _ = bundle

    def primary(value, source, city, ident):
        assert city == "hamburg" and ident == "11"
        if value["scene_inventory"]["incidents"][0]["evidence_quotes"] != [source["body"]]:
            raise ValueError("Undeclared PDF evidence is not primary evidence")
        return value

    return validate_pdf_referenced_decision(decision, source=source, city="hamburg",
                                          source_id="11", primary_validator=primary)


def test_individual_document_quote_retains_primary_binding(bundle):
    assert validate(bundle) == bundle[1]


@pytest.mark.parametrize("field", ["pdf", "extracted_text", "page_image", "parent_html", "review"])
def test_stale_bound_document_bytes_rejected(bundle, field):
    path = Path(bundle[2]["document"][field]["file"])
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="Stale bound"):
        validate(bundle)


def test_undeclared_or_spliced_pdf_quote_rejected(bundle):
    bundle[1]["scene_inventory"]["incidents"][0]["evidence_quotes"][1] = (
        bundle[0]["body"] + " EDR ( 1 NM ) = ROT")
    with pytest.raises(ValueError, match="crosses documents"):
        validate(bundle)


def test_unbound_quote_cannot_enter_primary_evidence(bundle):
    bundle[1]["scene_inventory"]["incidents"][0]["evidence_quotes"].append("53 30 00 N 010 00 00 E")
    with pytest.raises(ValueError, match="Undeclared PDF"):
        validate(bundle)


def test_pdf_must_be_linked_by_current_police_page(bundle):
    doc = bundle[2]["document"]
    doc["attachment_url"] = "https://www.presseportal.de/download/document/different.pdf"
    refresh(bundle)
    with pytest.raises(ValueError, match="not linked"):
        validate(bundle)


def test_stale_parent_version_rejected(bundle):
    bundle[0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="stale parent"):
        validate(bundle)


def test_redirect_media_robots_denial_rejected(bundle):
    doc = bundle[2]["document"]
    doc["robots"][1]["snapshot"] = bound(Path(doc["robots"][1]["snapshot"]["file"]),
                                         b"User-agent: *\nDisallow: /\n")
    refresh(bundle)
    with pytest.raises(ValueError, match="Robots denies"):
        validate(bundle)


@pytest.mark.parametrize("field,value", [("whole_pdf_read", False), ("count_contribution", 1),
                                        ("count_contribution", False)])
def test_incomplete_review_or_count_increase_rejected(bundle, field, value):
    bundle[3][field] = value
    refresh(bundle)
    with pytest.raises(ValueError, match="incomplete or stale"):
        validate(bundle)


def request(bundle):
    source = bundle[0]
    return {"source_id": source["id"], "source_url": source["url"], "source_sha256": source["sha256"],
            "source_document_binding": copy.deepcopy(bundle[1]["source_document_binding"]),
            "precision": "area", "city_scope": "in_city", "coordinates": None,
            "role": "operation", "poi_contexts": [], "transit_review": {"status": "not_applicable"}}


def derive(bundle, req=None, border=None):
    return derive_pdf_circle_reference({"method": METHOD, "verdict": "resolved", "osm_object_groups": []},
                                       request(bundle) if req is None else req,
                                       box(9, 53, 11, 54) if border is None else border, "hamburg")


def test_nautical_mile_radius_preserved_without_event_or_count_point(bundle):
    result = derive(bundle)
    assert result["radius_metres"] == 1852 and result["sampling_segments"] == 720
    assert len(result["geometry"]["coordinates"][0]) == 721
    assert not any(k.startswith("count_point") for k in result)
    assert result["actual_event_position_known"] is False
    assert result["height_known"] is False and result["full_legal_definition_verified"] is False
    for lon, lat in result["geometry"]["coordinates"][0]:
        assert Geod(ellps="WGS84").inv(10, 53.5, lon, lat)[2] == pytest.approx(1852, abs=1e-6)


@pytest.mark.parametrize("field,value", [("coordinates", [10, 53.5]), ("role", "incident"),
                                        ("precision", "district"), ("poi_contexts", ["guess"]),
                                        ("city_scope", "uncertain")])
def test_circle_cannot_be_promoted_to_incident_or_coarse_point(bundle, field, value):
    req = request(bundle)
    req[field] = value
    with pytest.raises(ValueError, match="never an event point"):
        derive(bundle, req)


def test_radius_or_coordinate_choices_must_match_pdf(bundle):
    bundle[3]["horizontal_circle"]["radius_nm"] = 2
    refresh(bundle)
    with pytest.raises(ValueError, match="differ"):
        derive(bundle)


def test_reference_cannot_claim_complete_legal_definition(bundle):
    bundle[3]["horizontal_circle"]["full_legal_definition_verified"] = True
    refresh(bundle)
    with pytest.raises(ValueError, match="retain height/legal"):
        derive(bundle)


def test_uncropped_circle_must_fit_reviewed_city_display_boundary(bundle):
    with pytest.raises(ValueError, match="exceeds"):
        derive(bundle, border=box(9.99, 53.49, 10.01, 53.51))
