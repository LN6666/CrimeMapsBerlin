"""Read-only, fail-closed binding of reviewed official Berlin attachments.

Supplemental historical episodes remain an explicit context appendix. They do
not silently change the frozen announcement's incident/count/location list.
"""
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from .feed import article_text
from .multiple_scenes import SCENE_PRECISIONS, SCENE_ROLES


def _keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{label} has missing or unknown fields")
    return value


def _bound(path, digest):
    if not isinstance(path, str) or not path or not isinstance(digest, str):
        raise ValueError("source supplement needs file/hash bindings")
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise ValueError(f"source supplement file unavailable: {path}") from exc
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f"source supplement file hash mismatch: {path}")
    return data


def _official(url):
    parsed = urlsplit(url) if isinstance(url, str) else None
    if (parsed is None or parsed.scheme != "https" or parsed.netloc != "www.berlin.de"
            or not parsed.path.startswith("/polizei/")):
        raise ValueError("source supplement needs an official Berlin police URL")


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a" and dict(attrs).get("href"):
            self.links.append(dict(attrs)["href"])


def _comparison_quotes(node, capture, text, quotes):
    found = []
    if isinstance(node, dict):
        if "verbatim_quote" in node:
            if (node.get("source_url") != capture["official_attachment_url"]
                    or node.get("source_file_sha256") != capture["attachment_file_sha256"]
                    or node.get("extracted_text_sha256") != capture["attachment_text_file_sha256"]):
                raise ValueError("source supplement quote has mismatched document provenance")
            found.extend(quotes([node["verbatim_quote"]], text, "supplement comparison"))
        for child in node.values():
            found.extend(_comparison_quotes(child, capture, text, quotes))
    elif isinstance(node, list):
        for child in node:
            found.extend(_comparison_quotes(child, capture, text, quotes))
    return found


def validate_source_supplements(value, source, *, quotes, event_time, reviewed_at):
    if not isinstance(value, list) or not value:
        raise ValueError("source supplement references must be a nonempty list")
    results, seen, documents_seen = [], set(), set()
    for ref in value:
        _keys(ref, {"capture_file", "capture_sha256", "review_file", "review_sha256"}, "supplement reference")
        capture = json.loads(_bound(ref["capture_file"], ref["capture_sha256"]))
        review = json.loads(_bound(ref["review_file"], ref["review_sha256"]))
        required_capture = {"schema_version", "source_id", "frozen_source_url", "frozen_source_sha256",
            "official_article_url", "official_attachment_url", "observed_attachment_url", "article_file",
            "article_file_sha256", "attachment_file", "attachment_file_sha256", "attachment_text_file",
            "attachment_text_file_sha256", "current_extracted_body_sha256", "current_body_matches_frozen",
            "robots_file", "robots_sha256", "robots_allowed", "retrieved_at", "article_redirect_chain",
            "attachment_redirect_chain"}
        if not isinstance(capture, dict) or not required_capture <= capture.keys():
            raise ValueError("source supplement capture is incomplete")
        _keys(review, {"schema_version", "city", "source_id", "source_url", "source_sha256", "reviewer",
            "reviewed_at", "attachment_read_complete", "comparison_file", "comparison_sha256",
            "supplemental_context_episodes", "count_contribution", "review_note"}, "supplement review")
        if (review["schema_version"] != 1 or review["city"] != "berlin"
                or capture.get("schema_version") != 1
                or review["source_id"] != source["source_id"]
                or capture.get("source_id") != source["source_id"]
                or review["source_url"] != source["source_url"]
                or capture.get("frozen_source_url") != source["source_url"]
                or review["source_sha256"] != source["source_sha256"]
                or capture.get("frozen_source_sha256") != source["source_sha256"]):
            raise ValueError("source supplement has stale or mismatched parent identity")
        if (review["attachment_read_complete"] is not True or type(review["count_contribution"]) is not int
                or review["count_contribution"] != 0
                or not isinstance(review["reviewer"], str) or not review["reviewer"].strip()
                or not isinstance(review["review_note"], str) or not review["review_note"].strip()):
            raise ValueError("source supplement needs complete review and zero independent count contribution")
        stamp = reviewed_at(review["reviewed_at"], "source supplement")
        for field in ("official_article_url", "official_attachment_url", "observed_attachment_url"):
            _official(capture.get(field))
        if not urlsplit(capture["official_article_url"]).path.endswith(
            f"/pressemitteilung.{source['source_id']}.php"
        ):
            raise ValueError("source supplement official article ID differs from parent")
        document_key = (capture["official_attachment_url"], capture["attachment_file_sha256"])
        if document_key in documents_seen:
            raise ValueError("duplicate source supplement document")
        documents_seen.add(document_key)
        html = _bound(capture["article_file"], capture["article_file_sha256"]).decode("utf-8")
        body = " ".join(article_text(html).split())
        if (body != " ".join(source["source_body"].split())
                or hashlib.sha256(body.encode()).hexdigest() != source["source_sha256"]
                or capture.get("current_extracted_body_sha256") != source["source_sha256"]
                or capture.get("current_body_matches_frozen") is not True):
            raise ValueError("source supplement current official article differs from frozen body")
        parser = _Links()
        parser.feed(html)
        if capture["observed_attachment_url"] not in {
            urljoin(capture["official_article_url"], link) for link in parser.links
        }:
            raise ValueError("source supplement attachment was not linked by the captured official article")
        document = _bound(capture["attachment_file"], capture["attachment_file_sha256"])
        if not document.startswith((b"%PDF-", b"PK")):
            raise ValueError("source supplement document must be the captured PDF or DOCX")
        text = " ".join(_bound(capture["attachment_text_file"], capture["attachment_text_file_sha256"])
                        .decode("utf-8").split())
        robots = RobotFileParser()
        robots.parse(_bound(capture["robots_file"], capture["robots_sha256"]).decode("utf-8").splitlines())
        if capture.get("robots_allowed") is not True:
            raise ValueError("source supplement acquisition lacks robots permission")
        for field, final_url in (("article_redirect_chain", capture["official_article_url"]),
                                 ("attachment_redirect_chain", capture["official_attachment_url"])):
            chain = capture[field]
            if (not isinstance(chain, list) or not chain or len(chain) > 3
                    or any(not isinstance(hop, dict) for hop in chain)
                    or chain[-1].get("url") != final_url or chain[-1].get("status") != 200):
                raise ValueError("source supplement has invalid bounded acquisition chain")
            for hop in chain:
                _official(hop.get("url"))
                if not robots.can_fetch("CrimeMapsBerlin/0.1", hop["url"]):
                    raise ValueError("source supplement robots snapshot denies acquisition")
        if capture["attachment_redirect_chain"][0]["url"] != capture["observed_attachment_url"]:
            raise ValueError("source supplement acquisition does not start at the observed attachment")
        media = capture.get("attachment_media_files_sha256", {})
        if not isinstance(media, dict):
            raise TypeError("source supplement media bindings must be a file/hash mapping")
        for path, digest in media.items():
            _bound(path, digest)
        comparison = json.loads(_bound(review["comparison_file"], review["comparison_sha256"]))
        if (not isinstance(comparison, dict) or comparison.get("source_id") != source["source_id"]
                or comparison.get("frozen_source_url") != source["source_url"]
                or comparison.get("frozen_source_sha256") != source["source_sha256"]
                or comparison.get("official_attachment_url") != capture["official_attachment_url"]
                or comparison.get("official_attachment_sha256") != capture["attachment_file_sha256"]):
            raise ValueError("source supplement comparison differs from captured source identity")
        inspection = comparison.get("map_inspection", {})
        if not isinstance(inspection, dict) or inspection.get("inspected") is not True:
            raise ValueError("source supplement map must be explicitly inspected")
        _bound(inspection.get("file"), inspection.get("sha256"))
        found_quotes = _comparison_quotes(comparison.get("findings"), capture, text, quotes)
        if not found_quotes:
            raise ValueError("source supplement comparison needs verbatim document evidence")
        episodes = review["supplemental_context_episodes"]
        if not isinstance(episodes, list):
            raise TypeError("source supplement episodes must be explicit, including an empty list")
        locations_seen = set()
        for episode in episodes:
            _keys(episode, {"episode_id", "details", "evidence_quotes", "event_time_review", "locations"},
                  "supplement episode")
            if (not isinstance(episode["episode_id"], str)
                    or not episode["episode_id"].startswith(source["source_id"] + ":supplement:")
                    or episode["episode_id"] in seen or not episode["details"]):
                raise ValueError("source supplement has invalid or duplicate episode identity")
            seen.add(episode["episode_id"])
            quotes(episode["evidence_quotes"], text, "supplement episode")
            event_time(episode["event_time_review"], text, "supplement episode")
            if not isinstance(episode["locations"], list) or not episode["locations"]:
                raise ValueError("source supplement episode needs reviewed locations")
            for location in episode["locations"]:
                _keys(location, {"location_id", "label", "role", "precision", "coordinates", "details",
                    "evidence_quotes", "event_time_review", "poi_contexts", "transit_route"}, "supplement location")
                if (not isinstance(location["location_id"], str)
                        or not location["location_id"].startswith(episode["episode_id"] + ":location:")
                        or location["location_id"] in locations_seen or not location["label"] or not location["details"]
                        or location["role"] not in SCENE_ROLES or location["precision"] not in SCENE_PRECISIONS
                        or location["coordinates"] is not None or location["poi_contexts"] != []
                        or location["transit_route"] is not None):
                    raise ValueError("source supplement context cannot invent positions, POI associations, transit or duplicate locations")
                locations_seen.add(location["location_id"])
                quotes(location["evidence_quotes"], text, "supplement location")
                event_time(location["event_time_review"], text, "supplement location")
        results.append({"reference": dict(ref), "official_attachment_url": capture["official_attachment_url"],
            "official_attachment_sha256": capture["attachment_file_sha256"],
            "attachment_text_sha256": capture["attachment_text_file_sha256"],
            "current_official_article_sha256": capture["current_extracted_body_sha256"],
            "retrieved_at": capture["retrieved_at"], "reviewed_at": stamp, "reviewer": review["reviewer"],
            "review_note": review["review_note"], "map_inspection": inspection,
            "findings": comparison["findings"], "supplemental_context_episodes": episodes,
            "display_usage": "source_bound_supplemental_context_only", "count_contribution": 0})
    return results
