"""Independent bytes, source/page attribution and no-publication claim checks."""
import hashlib
import json
from pathlib import Path

import pytest

from crimemapsberlin.official_attachment_reviews import validate_attachment_review


def bound(path, value):
    raw = value if isinstance(value, bytes) else json.dumps(value).encode()
    path.write_bytes(raw)
    return {"file": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


@pytest.fixture
def bundle(tmp_path):
    parent = "https://www.presseportal.de/blaulicht/pm/6337/11"
    url = "https://dokumente.hamburg.de/resource/blob/synthetic/august-name.pdf"
    body = "Synthetic August notice; historical attachment terms unverified."
    source = {"id": "11", "url": parent, "body": body,
              "sha256": hashlib.sha256(body.encode()).hexdigest()}
    html = (f'<article class="story"><p class="customer">Polizei Hamburg</p>'
            f'<h1>Synthetic</h1><p>{body}</p><a href="{url}">PDF</a></article>').encode()
    pdf = bound(tmp_path / "document.pdf", b"%PDF-1.7 Synthetic only")
    capture = {**pdf, "bytes": Path(pdf["file"]).stat().st_size, "url": url,
               "response_url": url, "status": 200, "source_id": "11", "source_url": parent,
               "source_sha256": source["sha256"], "parent_html": bound(tmp_path / "parent.html", html),
               "link_kind": "actual_primary_police_page_href", "page_count": 2,
               "extracted_text": bound(tmp_path / "text.txt", b"Signed September.\fValid October.\f"),
               "page_images": [{**bound(tmp_path / f"page-{ix}.png", b"\x89PNG\r\n\x1a\nSynthetic only"),
                                "page": ix} for ix in [1, 2]]}
    manifest = {"schema_version": 1, "city": "hamburg", "capture": capture,
                "robots": [{"url": origin + "/robots.txt",
                            "snapshot": bound(tmp_path / f"robots-{ix}.txt", b"User-agent: *\nAllow: /\n"),
                            "targets": [target]} for ix, (origin, target) in enumerate([
                                ("https://www.presseportal.de", parent),
                                ("https://dokumente.hamburg.de", url)])]}
    review = {"schema_version": 1, "city": "hamburg", "source_id": "11",
              "source_sha256": source["sha256"], "attachment_sha256": pdf["sha256"],
              "document_text_sha256": capture["extracted_text"]["sha256"], "whole_document_read": True,
              "visually_reviewed_pages": [1, 2], "count_contribution": 0,
              "generated_coordinates": False, "canonical_map_application_complete": False,
              "reviewer": "Synthetic author", "reviewed_at": "Synthetic time",
              "document_content_applicability": "different_period_at_current_link",
              "claims": [{"claim_id": "different-period", "summary": "Retain separate captured period.",
                          "evidence": [{"kind": "document", "page": 2, "quote": "Valid October."},
                                       {"kind": "primary", "quote": body}]}]}
    binding = {"manifest": bound(tmp_path / "manifest.json", manifest),
               "review": bound(tmp_path / "review.json", review)}
    return source, manifest, review, binding


def refresh(bundle):
    _, manifest, review, binding = bundle
    binding["manifest"] = bound(Path(binding["manifest"]["file"]), manifest)
    binding["review"] = bound(Path(binding["review"]["file"]), review)


def validate(bundle):
    return validate_attachment_review(bundle[3], source=bundle[0])


def test_different_period_preserved_without_map_import(bundle):
    assert validate(bundle) == bundle[2]
    assert bundle[2]["canonical_map_application_complete"] is False


@pytest.mark.parametrize("field", ["parent_html", "extracted_text", "file"])
def test_stale_captured_bytes_rejected(bundle, field):
    capture = bundle[1]["capture"]
    path = Path(capture[field] if field == "file" else capture[field]["file"])
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="file changed"):
        validate(bundle)


def test_same_url_different_document_cannot_reuse_old_review(bundle):
    capture = bundle[1]["capture"]
    new = bound(Path(capture["file"]), b"%PDF-1.7 Different captured version")
    capture.update(new, bytes=Path(new["file"]).stat().st_size)
    refresh(bundle)
    with pytest.raises(ValueError, match="stale or unsuccessful"):
        validate(bundle)


@pytest.mark.parametrize("kind,page", [("primary", None), ("document", 1)])
def test_wrong_body_or_page_origin_rejected(bundle, kind, page):
    evidence = bundle[2]["claims"][0]["evidence"][0]
    evidence.update(kind=kind, page=page)
    refresh(bundle)
    with pytest.raises(ValueError, match="declared source/page"):
        validate(bundle)


def test_false_canonical_application_claim_rejected(bundle):
    bundle[2]["canonical_map_application_complete"] = True
    refresh(bundle)
    with pytest.raises(ValueError, match="unperformed map import"):
        validate(bundle)


def test_missing_page_image_rejected(bundle):
    bundle[1]["capture"]["page_images"].pop()
    refresh(bundle)
    with pytest.raises(ValueError, match="missing or duplicated"):
        validate(bundle)


def test_robots_origin_cannot_be_borrowed_from_other_host(bundle):
    bundle[1]["robots"][1]["url"] = "https://unrelated.example/robots.txt"
    refresh(bundle)
    with pytest.raises(ValueError, match="does not permit its target"):
        validate(bundle)


def test_filename_alone_without_official_index_is_rejected(bundle):
    bundle[1]["capture"]["link_kind"] = "filename_only"
    refresh(bundle)
    with pytest.raises(ValueError, match="link provenance"):
        validate(bundle)


def filename_reference(bundle):
    source, manifest, review, binding = bundle
    root = Path(binding["manifest"]["file"]).parent
    source["body"] += " reward.pdf"
    source["sha256"] = hashlib.sha256(source["body"].encode()).hexdigest()
    target = "https://justiz.hamburg.de/resource/blob/synthetic/reward.pdf"
    index = "https://justiz.hamburg.de/staatsanwaltschaften/generalstaatsanwaltschaft-hamburg/pressestelle/auslobungen"
    capture = manifest["capture"]
    capture.update(url=target, response_url=target, source_sha256=source["sha256"],
                   link_kind="exact_filename_in_primary_body_and_actual_official_justice_index_href")
    html = (f'<article class="story"><p class="customer">Polizei Hamburg</p>'
            f'<h1>Synthetic</h1><p>{source["body"]}</p></article>').encode()
    capture["parent_html"] = bound(root / "parent.html", html)
    capture["official_index"] = {**bound(root / "index.html", f'<a href="{target}">Reward</a>'.encode()),
                                 "url": index, "response_url": index, "status": 200}
    manifest["robots"][1].update(url="https://justiz.hamburg.de/robots.txt", targets=[target, index])
    review["source_sha256"] = source["sha256"]
    refresh(bundle)


def test_filename_reference_needs_matching_observed_official_link(bundle):
    filename_reference(bundle)
    assert validate(bundle) == bundle[2]
    index = bundle[1]["capture"]["official_index"]
    index.update(bound(Path(index["file"]), b'<a href="/resource/blob/synthetic/other.pdf">Other</a>'))
    refresh(bundle)
    with pytest.raises(ValueError, match="no actual official index link"):
        validate(bundle)


def image_reference(bundle):
    _, manifest, review, binding = bundle
    root = Path(binding["manifest"]["file"]).parent
    capture = manifest["capture"]
    capture.update(bound(root / "image.jpg", b"\xff\xd8\xffSynthetic image only"),
                   bytes=(root / "image.jpg").stat().st_size, page_count=1)
    manifest["visual_transcription"] = bound(root / "visual.txt", b"Valid October.")
    review.update(attachment_sha256=capture["sha256"],
                  document_text_sha256=manifest["visual_transcription"]["sha256"],
                  visually_reviewed_pages=[1], transcription_method="LLM direct visual transcription")
    review["claims"][0]["evidence"][0]["page"] = 1
    refresh(bundle)


def test_image_quote_preserves_visual_origin_and_exact_image_hash(bundle):
    image_reference(bundle)
    assert validate(bundle) == bundle[2]
    Path(bundle[1]["capture"]["file"]).write_bytes(b"\xff\xd8\xffDifferent photo")
    with pytest.raises(ValueError, match="file changed"):
        validate(bundle)


def test_image_cannot_claim_unperformed_automatic_transcription(bundle):
    image_reference(bundle)
    bundle[2]["transcription_method"] = "automatic semantic extraction"
    refresh(bundle)
    with pytest.raises(ValueError, match="explicit visual origin"):
        validate(bundle)
