"""Check map-phase quotes against an individually validated source review.

Article classifications still use the primary body. This optional adapter only
accepts quotes already assigned by the reviewer to the same current phase. It
does not concatenate bodies, classify events, assign locations or approve maps.
"""
from __future__ import annotations

from collections.abc import Callable

from .article_source_references import (
    _digest,
    _require,
    _text,
    validate_source_referenced_decision,
)


def validate_referenced_phase_quotes(
    quotes: object,
    *,
    article: dict,
    source: dict,
    incident_id: str,
    primary_validator: Callable[[dict, dict, str, str], dict],
) -> list[str]:
    """Recheck complete source provenance and the selected phase's own quotes."""
    decision = article.get("source_review_decision")
    _require(isinstance(decision, dict), "Missing complete source review for phase evidence")
    source_id = article["source_id"]
    _require(
        decision.get("source_id") == source_id == source.get("id")
        and decision.get("source_url") == source.get("url")
        and decision.get("source_sha256") == source.get("sha256") == article.get("source_sha256")
        and _digest(decision) == article.get("decision_sha256"),
        "Stale or foreign complete source review for phase evidence",
    )
    verified = validate_source_referenced_decision(
        decision, source=source, city=article["city"], source_id=source_id,
        primary_validator=primary_validator,
    )
    phases = {row["incident_id"]: row for row in verified["scene_inventory"]["incidents"]}
    _require(incident_id in phases, "Unknown reviewed phase for map evidence")
    _require(isinstance(quotes, list) and bool(quotes), "Missing map phase quotes")
    allowed = [_text(quote) for quote in phases[incident_id]["evidence_quotes"]]
    normalized = [_text(quote) for quote in quotes]
    _require(len(normalized) == len(set(normalized)), "Duplicate map phase quotes")
    for quote in normalized:
        _require(any(quote in original for original in allowed),
                 "Map quote is absent from the individually validated same phase")
    return normalized
