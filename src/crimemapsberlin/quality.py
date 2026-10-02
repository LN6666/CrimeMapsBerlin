"""Fail-closed checks before replacing a published map manifest.

These checks detect missing inputs and sudden regressions. They do not certify
that a matched coordinate is the actual incident scene; that needs review.
"""

from pyproj import Geod

GEOD = Geod(ellps="WGS84")


def location_changes(previous_events: list[dict], candidate_events: list[dict]):
    """Locate source-ID losses and changed points requiring inspection before refresh."""
    current = {row["id"]: row for row in candidate_events}
    changes = []
    for old in previous_events:
        ident = old["id"]
        new = current.get(ident)
        if new is None:
            changes.append(dict(id=ident, reason="missing_report"))
            continue
        before, after = old.get("coordinates"), new.get("coordinates")
        if bool(before) != bool(after):
            changes.append(dict(id=ident, reason="location_added_or_withdrawn"))
        elif before and after:
            distance = GEOD.inv(before[0], before[1], after[0], after[1])[2]
            if distance > 100:
                changes.append(dict(id=ident, reason="location_moved", distance_m=round(distance)))
        old_has_scenes = "scene_locations" in old
        new_has_scenes = "scene_locations" in new
        if old_has_scenes != new_has_scenes:
            changes.append(dict(
                id=ident,
                reason="scene_locations_added" if new_has_scenes else "scene_locations_removed",
            ))
            continue
        if not old_has_scenes:
            continue
        old_scenes, new_scenes = old["scene_locations"], new["scene_locations"]
        if len(old_scenes) != len(new_scenes):
            changes.append(dict(
                id=ident,
                reason="scene_added" if len(new_scenes) > len(old_scenes) else "scene_removed",
                before=len(old_scenes), after=len(new_scenes),
            ))
        if [scene.get("role") for scene in old_scenes] != [scene.get("role") for scene in new_scenes]:
            changes.append(dict(id=ident, reason="scene_role_changed"))
        if [scene.get("primary_for_count") for scene in old_scenes] != [
            scene.get("primary_for_count") for scene in new_scenes
        ]:
            changes.append(dict(id=ident, reason="scene_primary_changed"))
        geometry_fields = ("coordinates", "geometry", "candidate_road_geometry")
        if [tuple(scene.get(key) for key in geometry_fields) for scene in old_scenes] != [
            tuple(scene.get(key) for key in geometry_fields) for scene in new_scenes
        ]:
            changes.append(dict(id=ident, reason="scene_geometry_changed"))
        if old_scenes != new_scenes and not any(
            row["id"] == ident and row["reason"].startswith("scene_") for row in changes
        ):
            changes.append(dict(id=ident, reason="scene_details_changed"))
    return changes


def publication_problems(
    candidate: dict, audit: dict, previous: dict | None, previous_audit: dict | None,
    changed_locations: list[dict] | None = None,
    review_counts: dict | None = None,
    owner_approved: bool | None = None,
):
    coverage = candidate["coverage"]
    problems = []
    if coverage["pending"] or coverage["failed"]:
        problems.append(
            f"source backlog/errors: {coverage['pending']} pending, {coverage['failed']} failed"
        )
    if coverage["fetched"] != audit["mapped"] + audit["unlocated"]:
        problems.append("mapped and unlocated counts do not reconcile with fetched reports")
    if sum(row["count"] for row in candidate["months"].values()) != coverage["fetched"]:
        problems.append("monthly counts do not reconcile with fetched reports")
    if review_counts and sum(review_counts.values()) != coverage["fetched"]:
        problems.append("review ledger does not reconcile with fetched reports")
    if review_counts and (
        review_counts["pending"] or review_counts["uncertain"] or review_counts["needs_correction"]
    ):
        problems.append(
            "article review incomplete: "
            + ", ".join(f"{key}={review_counts[key]}" for key in (
                "pending", "uncertain", "needs_correction"
            ))
        )
    if owner_approved is False:
        problems.append("owner inspection and approval pending")
    if not previous:
        return problems
    old = previous["coverage"]
    if coverage["discovered"] < old["discovered"] or coverage["fetched"] < old["fetched"]:
        problems.append("report inventory fell below the previous publication")
    for month, row in previous["months"].items():
        if candidate["months"].get(month, {}).get("count", 0) < row["count"]:
            problems.append(f"published month {month} lost reports")
    if previous_audit and previous_audit.get("generation") == previous.get("generation"):
        if audit["mapped"] < previous_audit["mapped"]:
            problems.append("located-report count fell below the previous publication")
    if changed_locations and owner_approved is not True:
        problems.append(f"{len(changed_locations)} previously published report locations changed")
    return problems
