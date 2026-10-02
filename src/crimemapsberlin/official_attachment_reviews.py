"""Verify captured official attachments and explicit, source-bound LLM reviews.

This read-only check does not import source decisions, interpret a document,
generate coordinates, or approve a publication. A live URL may return a newer
document than the announcement describes; applicability stays an explicit LLM
decision in the review, with both source versions retained.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser


def _bound(spec):
    if not isinstance(spec, dict) or set(spec) != {"file", "sha256"}:
        raise ValueError("Attachment evidence needs a file/hash binding")
    raw = Path(spec["file"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != spec["sha256"]:
        raise ValueError("Attachment evidence file changed")
    return raw


def _text(value):
    return " ".join(value.split())


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []

    def handle_starttag(self, tag, attrs):
        href = dict(attrs).get("href")
        if tag == "a" and href:
            self.links.append(href)


def validate_attachment_review(binding, *, source):
    """Verify one independently authored review against exact captured bytes."""
    from .hamburg import ArticleParser, article_body

    if not isinstance(binding, dict) or set(binding) != {"manifest", "review"}:
        raise ValueError("Attachment review bundle is incomplete")
    manifest = json.loads(_bound(binding["manifest"]))
    review = json.loads(_bound(binding["review"]))
    if (manifest.get("schema_version") != 1 or manifest.get("city") != "hamburg"
            or review.get("schema_version") != 1 or review.get("city") != "hamburg"):
        raise ValueError("Attachment review city/schema mismatch")
    capture = manifest["capture"]
    if (capture.get("source_id") != source["id"]
            or capture.get("source_url") != source["url"]
            or capture.get("source_sha256") != source["sha256"]
            or review.get("source_id") != source["id"]
            or review.get("source_sha256") != source["sha256"]
            or hashlib.sha256(source["body"].encode()).hexdigest() != source["sha256"]):
        raise ValueError("Attachment review has a stale primary source")
    if (capture.get("status") != 200 or capture.get("response_url") != capture.get("url")
            or review.get("attachment_sha256") != capture.get("sha256")):
        raise ValueError("Attachment review has a stale or unsuccessful capture")
    parent = urlsplit(source["url"])
    if (parent.scheme != "https" or parent.netloc != "www.presseportal.de"
            or parent.path != f'/blaulicht/pm/6337/{source["id"]}'):
        raise ValueError("Attachment parent is not the declared Hamburg police page")
    html = _bound(capture["parent_html"]).decode()
    parser = ArticleParser(); parser.feed(html)
    if parser.customer.strip() != "Polizei Hamburg" or article_body(html) != _text(source["body"]):
        raise ValueError("Attachment parent HTML differs from current police source")
    links = _Links(); links.feed(html)
    target = urlsplit(capture["url"])
    required_urls = {source["url"], capture["url"]}
    if capture["link_kind"] == "actual_primary_police_page_href":
        if (capture["url"] not in links.links or target.scheme != "https"
                or not ((target.netloc == "dokumente.hamburg.de" and target.path.startswith("/resource/blob/"))
                        or (target.netloc == "cache.pressmailing.net"
                            and target.path.startswith("/thumbnail/story_hires/")))):
            raise ValueError("Attachment URL is not a captured official page link")
    elif capture["link_kind"] == "exact_filename_in_primary_body_and_actual_official_justice_index_href":
        index = capture["official_index"]
        index_url = urlsplit(index["url"])
        if (target.scheme != "https" or target.netloc != "justiz.hamburg.de"
                or not target.path.startswith("/resource/blob/")
                or target.path.rsplit("/", 1)[-1] not in source["body"]
                or index_url.scheme != "https" or index_url.netloc != target.netloc
                or index_url.path != "/staatsanwaltschaften/generalstaatsanwaltschaft-hamburg/pressestelle/auslobungen"
                or index.get("status") != 200 or index.get("response_url") != index["url"]):
            raise ValueError("Filename reference is not bound to the official justice index")
        ix = _Links(); ix.feed(_bound({"file": index["file"], "sha256": index["sha256"]}).decode())
        if capture["url"] not in [urljoin(index["url"], link) for link in ix.links]:
            raise ValueError("Filename reference has no actual official index link")
        required_urls.add(index["url"])
    else:
        raise ValueError("Unreviewed attachment link provenance")
    raw = _bound({"file": capture["file"], "sha256": capture["sha256"]})
    if len(raw) != capture["bytes"]:
        raise ValueError("Attachment byte count changed")
    if type(capture.get("page_count")) is not int or not 1 <= capture["page_count"] <= 100:
        raise ValueError("Attachment has an invalid page count")
    inspected = review.get("visually_reviewed_pages")
    if (review.get("whole_document_read") is not True
            or inspected != list(range(1, capture["page_count"] + 1))
            or not review.get("reviewer") or not review.get("reviewed_at")
            or type(review.get("count_contribution")) is not int or review["count_contribution"] != 0
            or review.get("generated_coordinates") is not False
            or review.get("canonical_map_application_complete") is not False):
        raise ValueError("Attachment review is incomplete or claims an unperformed map import")
    if raw.startswith(b"%PDF-"):
        images = capture["page_images"]
        if [page["page"] for page in images] != inspected:
            raise ValueError("Attachment pages are missing or duplicated")
        for page in images:
            if not _bound({"file": page["file"], "sha256": page["sha256"]}).startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("Attachment inspection image is not PNG")
        text_spec = capture["extracted_text"]
    elif raw.startswith(b"\xff\xd8\xff") and capture["page_count"] == 1:
        text_spec = manifest["visual_transcription"]
        if review.get("transcription_method") != "LLM direct visual transcription":
            raise ValueError("Image transcription must retain its explicit visual origin")
    else:
        raise ValueError("Unsupported or invalid captured attachment")
    if review.get("document_text_sha256") != text_spec["sha256"]:
        raise ValueError("Attachment review refers to a different text version")
    document_raw_text = _bound(text_spec).decode()
    document_pages = document_raw_text.split("\f") if raw.startswith(b"%PDF-") else [document_raw_text]
    if document_pages and not document_pages[-1].strip():
        document_pages.pop()
    if len(document_pages) != capture["page_count"]:
        raise ValueError("Extracted text does not retain all individual pages")
    document_pages = [_text(page) for page in document_pages]
    allowed_urls = set()
    for robot in manifest["robots"]:
        parsed = urlsplit(robot["url"])
        if parsed.scheme != "https" or parsed.path != "/robots.txt":
            raise ValueError("Invalid robots snapshot origin")
        rp = RobotFileParser(); rp.parse(_bound(robot["snapshot"]).decode().splitlines())
        for url in robot["targets"]:
            if urlsplit(url).netloc != parsed.netloc or not rp.can_fetch("CrimeMapsBerlin/0.1", url):
                raise ValueError("Robots snapshot does not permit its target")
            allowed_urls.add(url)
    if not required_urls.issubset(allowed_urls):
        raise ValueError("Attachment acquisition URLs lack bound robots snapshots")
    if review.get("document_content_applicability") not in {
        "matches_primary_subject", "different_time_specificity_from_primary", "different_period_at_current_link"
    }:
        raise ValueError("Attachment applicability needs an explicit LLM decision")
    claims = review.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ValueError("Attachment review has no individually sourced claims")
    identifiers = []
    for claim in claims:
        identifiers.append(claim["claim_id"])
        if not claim.get("summary") or not claim.get("evidence"):
            raise ValueError("Attachment claim has no explicit review/evidence")
        for evidence in claim["evidence"]:
            kind, quote = evidence.get("kind"), evidence.get("quote")
            if kind not in {"document", "primary"} or not isinstance(quote, str) or not quote.strip():
                raise ValueError("Attachment claim needs an individual document or primary quote")
            if kind == "document" and evidence.get("page") not in inspected:
                raise ValueError("Attachment claim refers to an unread page")
            body = document_pages[evidence["page"] - 1] if kind == "document" else _text(source["body"])
            if _text(quote) not in body:
                raise ValueError("Attachment claim quote is not in its declared source/page")
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Attachment claim IDs are duplicated")
    return copy.deepcopy(review)


def validate_attachment_referenced_decision(value, *, source, city, source_id, primary_validator):
    """Compose explicit attachment quotes with existing primary/article gates.

    Document evidence is checked in one declared page before the unchanged
    source validator sees the retained primary evidence. Scalar time quotations
    need an explicit primary fallback; this is validation input only, never a
    replacement for the document quotation stored in the actual decision.
    """
    if city != "hamburg" or source_id != source["id"]:
        raise ValueError("Attachment decision belongs to another city/source")
    binding = value.get("source_attachment_binding")
    if not isinstance(binding, dict) or set(binding) != {
        "review_bundle", "evidence_sources", "scalar_primary_fallbacks"
    }:
        raise ValueError("Attachment decision binding is incomplete")
    review = validate_attachment_review(binding["review_bundle"], source=source)
    origins = binding["evidence_sources"]
    fallbacks = binding["scalar_primary_fallbacks"]
    if not isinstance(origins, dict) or not origins or not isinstance(fallbacks, dict):
        raise ValueError("Attachment decision needs individual quotation origins")
    claims = {row["claim_id"]: row for row in review["claims"]}
    primary = copy.deepcopy(value)
    primary.pop("source_attachment_binding")
    grouped = {}
    scalar_paths = set()
    for path, origin in origins.items():
        array = re.fullmatch(
            r"/scene_inventory/(incidents|formal_locations)/\d+/(?:poi_review/|transit_review/)?evidence_quotes/\d+",
            path,
        )
        scalar = re.fullmatch(r"/scene_inventory/incidents/\d+/event_time/evidence_quote", path)
        if not array and not scalar:
            raise ValueError("Attachment quotation has an invalid decision path")
        if not isinstance(origin, dict) or set(origin) != {"claim_id", "evidence_index"}:
            raise ValueError("Attachment quotation needs one reviewed claim origin")
        try:
            evidence = claims[origin["claim_id"]]["evidence"][origin["evidence_index"]]
            parts = path.strip("/").split("/")
            container = primary
            for part in parts[:-1]:
                container = container[int(part)] if isinstance(container, list) else container[part]
            key = int(parts[-1]) if isinstance(container, list) else parts[-1]
            quote = container[key]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Attachment quotation points to missing evidence") from exc
        if (type(origin["evidence_index"]) is not int or origin["evidence_index"] < 0
                or evidence["kind"] != "document" or quote != _text(evidence["quote"])):
            raise ValueError("Attachment quotation differs from its individual reviewed page")
        if scalar:
            if review["document_content_applicability"] == "different_period_at_current_link":
                raise ValueError("Different-period attachment cannot supply primary event time")
            fallback = fallbacks.get(path)
            if (not isinstance(fallback, str) or len(fallback) < 15
                    or fallback != _text(fallback) or fallback not in _text(source["body"])):
                raise ValueError("Attachment scalar evidence has no explicit primary fallback")
            container[key] = fallback
            scalar_paths.add(path)
        else:
            grouped.setdefault(path.rsplit("/", 1)[0], (container, []))[1].append(key)
    if set(fallbacks) != scalar_paths:
        raise ValueError("Attachment scalar fallback paths do not match the quotations")
    for container, indices in grouped.values():
        # Appended document quotations do not shift previously bound article
        # quotation indices in a composed primary/reference decision.
        if sorted(indices) != list(range(min(indices), len(container))):
            raise ValueError("Attachment array quotations must follow retained primary/article evidence")
        for index in sorted(indices, reverse=True):
            del container[index]
        if not container:
            raise ValueError("Supplemented evidence retains a primary announcement anchor")
    if primary_validator(primary, source, city, source_id) != primary:
        raise ValueError("Attachment primary/reference decision is not canonical")
    return copy.deepcopy(value)
