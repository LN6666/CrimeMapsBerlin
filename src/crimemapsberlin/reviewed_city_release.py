"""Inspect and promote a reviewed city candidate only after exact owner signoff.

Preparation is read-only for source/decision data. It revalidates the source
inventory, native geometry, explicit map decisions and the full candidate bytes.
It does not grant approval. Promotion checks the same packet again and installs
an immutable generation before atomically switching the public manifest.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from shapely.geometry import shape

from .city_geometry_index import validate_geometry_index
from .geometry_decisions import compile_geometry_decisions
from .map_decisions import compile_map_decisions
from .poi_cities import POI_CITY_SPECS
from .review_decisions import REVIEW_REQUIRED_CITIES
from .reviewed_city_map import _digest as candidate_digest
from .reviewed_city_map import build_candidate
from .reviewed_scenes import build_inventory
from .source_review_pack import read_checkpoint

GENERATION = re.compile(r"^[a-f0-9]{16}-\d{8}T\d{6}$")
OWNER_BLOCKS = {"owner_approval_missing", "owner_map_inspection_and_approval_missing"}
ACCEPTANCE_CHECKS = {
    "source_acquisition",
    "source_semantics",
    "geometry_dispositions",
    "map_semantics",
    "poi_product",
    "data_assembly",
    "browser_behaviour",
    "gap_disclosure",
}


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _sha(path: Path) -> str:
    _no_links(path)
    if not path.is_file():
        raise ValueError(f"Expected a regular file: {path}")
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _no_links(path: Path) -> None:
    if any(part.is_symlink() for part in (path, *path.absolute().parents)):
        raise ValueError(f"Symbolic link in release path: {path}")


def _load(path: Path) -> dict:
    _sha(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object: {path}")
    return value


def file_hashes(root: Path) -> dict[str, str]:
    """Reject links rather than publishing files from outside the checked tree."""
    _no_links(root)
    if not root.is_dir():
        raise ValueError("Candidate/generation must be a regular directory")
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symbolic link in candidate: {path}")
        if path.is_file() and path.name != ".DS_Store":
            result[path.relative_to(root).as_posix()] = _sha(path)
    return result


@dataclass(frozen=True)
class ReleaseInputs:
    city: str
    source_db: Path
    source_pbf_path: Path
    inventory_path: Path
    geometry_index_path: Path
    geometry_ledger_path: Path
    map_ledger_path: Path
    poi_root: Path
    catalog_path: Path
    reviewed_poi_binding_path: Path | None = None
    reviewed_display_path: Path | None = None
    acceptance_path: Path | None = None
    publication_timezone: str | None = None
    month_basis: str = "reviewed_incident_time"

    @classmethod
    def from_json(cls, path: Path) -> ReleaseInputs:
        value = _load(path)
        for key in list(value):
            if (key.endswith("_path") or key in {"source_db", "poi_root"}) and value[key] is not None:
                value[key] = Path(value[key])
        return cls(**value)

    def bindings(self) -> dict:
        paths = {
            key: value for key, value in asdict(self).items() if isinstance(value, Path) and key != "poi_root"
        }
        for name in [
            "boundary.geojson",
            "poi-contract.json",
            "poi-index.json",
            "validation.json",
            "search.json",
        ]:
            paths[f"poi/{name}"] = self.poi_root / name
        return {key: {"path": str(path.absolute()), "sha256": _sha(path)} for key, path in paths.items()}


def _validate_review_chain(inputs: ReleaseInputs) -> None:
    city = inputs.city
    if city not in REVIEW_REQUIRED_CITIES:
        raise ValueError("This release gate requires the official-source city review workflow")
    inventory = _load(inputs.inventory_path)
    fresh = build_inventory(city=city, db_path=inputs.source_db)
    if not fresh["all_current_reviews_supported"] or fresh["inventory_digest"] != inventory.get(
        "inventory_digest"
    ):
        raise ValueError("Source inventory is stale or has missing/uncertain review")
    if fresh["coverage"].get("channel_scan_complete") is not True:
        raise ValueError("Selected official source scan is incomplete")
    index = _load(inputs.geometry_index_path)
    if index.get("source_pbf_sha256") != _sha(inputs.source_pbf_path):
        raise ValueError("Native geometry index belongs to another or stale PBF")
    boundary = _load(inputs.poi_root / "boundary.geojson")
    border = shape(boundary["geometry"])
    validation = validate_geometry_index(
        index,
        city=city,
        border=border,
        boundary_metadata=boundary,
        source_metadata={
            "sha256": index.get("source_pbf_sha256"),
            "pbf_timestamp": index.get("source_pbf_timestamp"),
        },
    )
    if not validation["passed"]:
        raise ValueError("Native geometry index failed validation")
    geometry = _load(inputs.geometry_ledger_path)
    compiled = compile_geometry_decisions(
        inventory=fresh,
        geometry_index=index,
        border=border,
        decision_envelope={
            "schema_version": 1,
            "city": city,
            "inventory_digest": geometry["submitted_inventory_digest"],
            "geometry_index_sha256": geometry["geometry_index_sha256"],
            "decisions": [row["decision"] for row in geometry["decisions"]],
        },
        include_footprint_count_points=geometry.get("footprint_representative_points_enabled", True),
    )
    if not compiled["geometry_review_complete"] or compiled["ledger_sha256"] != geometry.get("ledger_sha256"):
        raise ValueError("Geometry ledger is stale, incomplete or differs from checked native geometry")
    maps = _load(inputs.map_ledger_path)
    rows, _ = read_checkpoint(inputs.source_db)
    rebuilt = compile_map_decisions(
        city=city,
        source_rows=rows,
        inventory=fresh,
        geometry_ledger=compiled,
        decision_envelope={
            "schema_version": 1,
            "city": city,
            "inventory_digest": fresh["inventory_digest"],
            "geometry_ledger_sha256": compiled["ledger_sha256"],
            "decisions": [row["decision"] for row in maps["decisions"]],
        },
    )
    if not rebuilt["map_review_complete"] or rebuilt["ledger_sha256"] != maps.get("ledger_sha256"):
        raise ValueError("Map decision ledger is stale or incomplete")


def prepare_packet(*, inputs: ReleaseInputs, candidate: Path) -> dict:
    """Return an exact review packet; incomplete acceptance stays a release block."""
    if inputs.city not in REVIEW_REQUIRED_CITIES:
        raise ValueError("This release gate requires the official-source city review workflow")
    before = inputs.bindings()
    files = file_hashes(candidate)
    manifest, audit = _load(candidate / "manifest.json"), _load(candidate / "build-audit.json")
    generation = manifest.get("generation", "")
    if (
        not isinstance(generation, str)
        or not GENERATION.fullmatch(generation)
        or audit.get("city") != inputs.city
        or manifest.get("city") != POI_CITY_SPECS[inputs.city].name
    ):
        raise ValueError("Candidate has an invalid generation or different city")
    if manifest.get("owner_approved") is not False or manifest.get("publication_ready") is not False:
        raise ValueError("Preparation requires an unapproved candidate")
    core_audit = {key: value for key, value in audit.items() if key != "candidate_digest"}
    if audit.get("candidate_digest") != candidate_digest({"manifest": manifest, "audit": core_audit}):
        raise ValueError("Candidate digest is invalid")
    _validate_review_chain(inputs)
    # Reproduce current source/GIS/map/POI/display output, including every tile.
    # This catches modified payloads even when an old manifest still hashes correctly.
    with tempfile.TemporaryDirectory(prefix=".release-check-", dir=candidate.parent) as temporary:
        expected = Path(temporary) / "candidate"
        build_candidate(
            city=inputs.city,
            source_db=inputs.source_db,
            inventory_path=inputs.inventory_path,
            geometry_ledger_path=inputs.geometry_ledger_path,
            map_ledger_path=inputs.map_ledger_path,
            poi_root=inputs.poi_root,
            catalog_path=inputs.catalog_path,
            output=expected,
            reviewed_poi_binding_path=inputs.reviewed_poi_binding_path,
            reviewed_display_path=inputs.reviewed_display_path,
            publication_timezone=inputs.publication_timezone,
            month_basis=inputs.month_basis,
        )
        if file_hashes(expected) != files:
            raise ValueError("Candidate bytes differ from the current validated build")
    if inputs.bindings() != before or file_hashes(candidate) != files:
        raise ValueError("Inputs or candidate changed during verification")
    acceptance = _load(inputs.acceptance_path) if inputs.acceptance_path else {}
    evidence_bindings = {}
    evidence_current = True
    for check in sorted(ACCEPTANCE_CHECKS):
        references = acceptance.get("evidence", {}).get(check, [])
        if not isinstance(references, list) or not references:
            evidence_current = False
            continue
        evidence_bindings[check] = []
        for reference in references:
            if not isinstance(reference, dict) or not isinstance(reference.get("path"), str):
                evidence_current = False
                continue
            path = Path(reference["path"])
            if not path.is_absolute():
                evidence_current = False
                continue
            digest = _sha(path)
            if digest != reference.get("sha256"):
                evidence_current = False
            evidence_bindings[check].append({"path": str(path), "sha256": digest})
    accepted = (
        acceptance.get("schema_version") == 1
        and acceptance.get("city") == inputs.city
        and acceptance.get("candidate_digest") == audit["candidate_digest"]
        and acceptance.get("generation") == generation
        and acceptance.get("candidate_file_hashes") == files
        and acceptance.get("input_bindings") == {k: v for k, v in before.items() if k != "acceptance_path"}
        and evidence_current
        and all(acceptance.get("checks", {}).get(key) is True for key in ACCEPTANCE_CHECKS)
    )
    manifest_blocks = set(manifest.get("publication_blocks", []))
    if accepted:
        manifest_blocks.discard("independent_full_technical_acceptance_not_established_by_builder")
    blocks = sorted(
        manifest_blocks
        | (set() if accepted else {"current_candidate_technical_acceptance_missing"})
    )
    packet = {
        "schema_version": 1,
        "city": inputs.city,
        "candidate_digest": audit["candidate_digest"],
        "generation": generation,
        "input_bindings": before,
        "candidate_file_hashes": files,
        "acceptance_evidence_bindings": evidence_bindings,
        "release_gate_sha256": _sha(Path(__file__)),
        "technical_acceptance_current": accepted,
        "source_review_revalidated": True,
        "native_geometry_recompiled": True,
        "map_decisions_revalidated": True,
        "entire_candidate_reproduced": True,
        "publication_blocks": blocks,
        "owner_approved": False,
        "publication_ready": False,
        "scope": {
            "coverage": manifest["coverage"],
            "coverage_scope": manifest["metadata"].get("coverage_scope"),
            "announcements": audit["mappable_articles"],
            "phases": audit["incidents"],
            "locations": audit["formal_locations"],
            "unlocated_display_locations": audit["unresolved_display_locations"],
            "primary_count_points": audit["primary_count_points"],
            "poi_count": audit["poi_count"],
            "not_a_complete_crime_inventory": True,
            "poi_associations_are_context_only": True,
        },
    }
    packet["packet_digest"] = _digest(packet)
    return packet


def validate_owner_approval(packet: dict, approval: dict) -> None:
    """Validate a supplied human signoff; never create or infer one."""
    if (
        approval.get("schema_version") != 1
        or approval.get("city") != packet["city"]
        or approval.get("packet_digest") != packet["packet_digest"]
        or approval.get("candidate_digest") != packet["candidate_digest"]
    ):
        raise ValueError("Owner approval belongs to another or stale packet")
    if approval.get("approved") is not True:
        raise ValueError("Explicit owner approval is missing")
    for key in ["approved_by", "inspection_note"]:
        if not isinstance(approval.get(key), str) or not approval[key].strip():
            raise ValueError("Owner approval requires a name and inspection note")
    if not isinstance(approval.get("approved_at"), str):
        raise TypeError("Owner approval time needs an ISO timestamp")
    clock = datetime.fromisoformat(approval["approved_at"])
    if clock.tzinfo is None:
        raise ValueError("Owner approval time needs a timezone")
    if (
        packet.get("technical_acceptance_current") is not True
        or set(packet["publication_blocks"]) - OWNER_BLOCKS
    ):
        raise ValueError("Unresolved technical/source publication blocks remain")
    if approval.get("accepted_scope") != packet["scope"]:
        raise ValueError("Owner must explicitly accept the packet's coverage and precision limits")


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def promote_candidate(*, inputs: ReleaseInputs, candidate: Path, approval: dict, output: Path) -> dict:
    packet = prepare_packet(inputs=inputs, candidate=candidate)
    validate_owner_approval(packet, approval)
    _no_links(output)
    source, target = candidate.resolve(), output.resolve()
    if target == source or target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError("Release output must be separate from the candidate")
    target.mkdir(parents=True, exist_ok=True)
    # Serialize the commit point; a competing release cannot replace a checked
    # generation or city manifest during this promotion.
    lock_path = target / ".release.lock"
    _no_links(lock_path)
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Another city release is in progress") from error
        return _install_generation(
            inputs=inputs, candidate=source, packet=packet, approval=approval, target=target
        )


def _install_generation(
    *, inputs: ReleaseInputs, candidate: Path, packet: dict, approval: dict, target: Path
) -> dict:
    # Refuse an existing city root with a different city; retain previous generations.
    if (target / "manifest.json").exists() and _load(target / "manifest.json").get("city") != POI_CITY_SPECS[
        inputs.city
    ].name:
        raise ValueError("Release output contains another city's manifest")
    manifest = copy.deepcopy(_load(candidate / "manifest.json"))
    manifest.update(
        status="owner_approved_reviewed_city_map",
        owner_approved=True,
        publication_ready=True,
        publication_blocks=[],
    )
    manifest["metadata"]["review_status"] = "OWNER_APPROVED"
    manifest["metadata"]["owner_authorization_type"] = (
        "standing_routine_batch_authorization"
        if approval.get("authorization_type") == "standing_routine_batch_authorization"
        else "current_packet_owner_approval"
    )
    manifest["metadata"].pop("candidate_notice", None)
    manifest["metadata"]["owner_review_packet_digest"] = packet["packet_digest"]
    generation = packet["generation"]
    expected = {
        key[len(generation) + 1 :]: value
        for key, value in packet["candidate_file_hashes"].items()
        if key.startswith(generation + "/")
    }
    with tempfile.TemporaryDirectory(prefix=".city-release-", dir=target) as temporary:
        staged = Path(temporary) / generation
        shutil.copytree(candidate / generation, staged, ignore=shutil.ignore_patterns(".DS_Store"))
        if file_hashes(staged) != expected:
            raise ValueError("Generation changed while copying; previous publication retained")
        if (
            inputs.bindings() != packet["input_bindings"]
            or file_hashes(candidate) != packet["candidate_file_hashes"]
        ):
            raise ValueError("Inputs changed before publication; previous publication retained")
        for references in packet["acceptance_evidence_bindings"].values():
            if any(_sha(Path(row["path"])) != row["sha256"] for row in references):
                raise ValueError("Acceptance evidence changed before publication")
        final = target / generation
        if final.exists():
            if file_hashes(final) != expected:
                raise ValueError("Existing immutable generation differs; refusing to overwrite")
        else:
            os.replace(staged, final)
        # The manifest is the commit point. Failures before it leave the old
        # manifest readable and never remove any previous good generation.
        _write(Path(temporary) / "manifest.json", manifest)
        receipt = {
            "schema_version": 1,
            "city": inputs.city,
            "generation": generation,
            "packet_digest": packet["packet_digest"],
            "candidate_digest": packet["candidate_digest"],
            "published_at": datetime.now(UTC).isoformat(),
            "owner_approval": approval,
            "generation_file_hashes": expected,
            "public_manifest_sha256": _sha(Path(temporary) / "manifest.json"),
        }
        _write(Path(temporary) / "receipt.json", receipt)
        os.replace(Path(temporary) / "receipt.json", target / f"release-{packet['packet_digest']}.json")
        os.replace(Path(temporary) / "manifest.json", target / "manifest.json")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["packet", "publish"])
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--owner-approval", type=Path)
    args = parser.parse_args()
    inputs = ReleaseInputs.from_json(args.inputs)
    if args.mode == "packet":
        _no_links(args.out)
        if not args.out.resolve().is_relative_to((Path.cwd() / ".runtime").resolve()):
            parser.error("Review packets must remain under .runtime/")
        packet = prepare_packet(inputs=inputs, candidate=args.candidate)
        _write(args.out, packet)
        print(json.dumps({key: packet[key] for key in ["city", "packet_digest", "publication_blocks"]}))
    else:
        if args.owner_approval is None:
            parser.error("Publication requires explicit --owner-approval for the current packet")
        result = promote_candidate(
            inputs=inputs, candidate=args.candidate, approval=_load(args.owner_approval), output=args.out
        )
        print(json.dumps({key: result[key] for key in ["city", "generation", "packet_digest"]}))


if __name__ == "__main__":
    main()
