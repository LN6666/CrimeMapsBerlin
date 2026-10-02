"""Verify detached acceptance and safely unpack a single accepted city site."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "security"))
from artifact_gate import verify  # noqa: E402

NAMES = {"berlin": "Berlin", "hamburg": "Hamburg", "munich": "München", "cologne": "Köln",
         "frankfurt": "Frankfurt", "dusseldorf": "Düsseldorf", "stuttgart": "Stuttgart",
         "leipzig": "Leipzig", "dortmund": "Dortmund", "bremen": "Bremen", "essen": "Essen",
         "dresden": "Dresden", "hannover": "Hannover", "nuremberg": "Nürnberg"}
CHECKS = {"source", "semantic", "geometry", "count", "scope", "performance", "navigation",
          "isolation", "browser", "languages", "mobile", "security", "home", "analytics", "feedback"}
BINDINGS = {"source_approval", "source_semantic_geometry", "rules_scope", "performance_encoding",
            "translation_resources"}
MAX_TAR_STREAM_BYTES = 1_010_000_000  # payload plus bounded TAR headers and padding


@contextmanager
def bounded_tar(archive: Path):
    # Bound actual decompression before tarfile can allocate extended metadata.
    with tempfile.TemporaryFile() as spool:
        with gzip.open(archive, "rb") as compressed:
            total = 0
            while chunk := compressed.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_TAR_STREAM_BYTES:
                    raise ValueError("Expanded archive stream exceeds budget")
                spool.write(chunk)
        spool.seek(0)
        count = 0
        while header := spool.read(512):
            if len(header) != 512:
                raise ValueError("Truncated TAR header")
            if not header.strip(b"\0"):
                break
            count += 1
            if count > 100_000 or header[156:157] not in {b"\0", b"0", b"5"}:
                raise ValueError("Extended metadata and special TAR members forbidden")
            size = tarfile.nti(header[124:136])
            if size < 0 or size > 100_000_000:
                raise ValueError("TAR header size exceeds budget")
            if header[156:157] == b"5" and size != 0:
                raise ValueError("Directory TAR member must have zero size")
            spool.seek(((size + 511) // 512) * 512, 1)
        spool.seek(0)
        yield spool


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fresh_prelaunch(value: dict, city: str, repository: str, receipt_sha: str, now: datetime) -> None:
    refresh = value.get("prelaunch_refresh")
    if (not isinstance(refresh, dict) or refresh.get("status") != "passed"
            or refresh.get("city") != city or refresh.get("repository") != repository
            or refresh.get("checked_candidate_receipt_sha256") != receipt_sha
            or not isinstance(refresh.get("evidence_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", refresh["evidence_sha256"])):
        raise ValueError("Checked city-bound prelaunch refresh evidence is required")
    try:
        checked = datetime.fromisoformat(refresh["last_successful_source_check"].replace("Z", "+00:00"))
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ValueError("Invalid prelaunch source-check timestamp") from exc
    if checked.tzinfo is None or checked.utcoffset() is None or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Prelaunch source-check timestamps must include a timezone")
    age = now.astimezone(timezone.utc) - checked.astimezone(timezone.utc)
    if age < timedelta(0) or age > timedelta(hours=72):
        raise ValueError("Prelaunch source check is future-dated or older than 72 hours")


def acceptance(path: Path, expected_sha: str, city: str, repository: str, commit: str,
               *, now: datetime | None = None) -> dict:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha) or sha(path) != expected_sha:
        raise ValueError("Acceptance differs from the trusted repository digest")
    value = json.loads(path.read_text())
    if (city not in NAMES or repository != f"LN6666/crimemaps-{city.capitalize()}"
            or not re.fullmatch(r"[0-9a-f]{40}", commit)):
        raise ValueError("Invalid deployment identity")
    if any(value.get(k) != v for k, v in {"schema_version": 1, "city": city,
           "repository": repository, "code_commit": commit,
           "release_status": "accepted_for_publication"}.items()):
        raise ValueError("Acceptance is stale or belongs to another product")
    if value.get("languages") != ["de", "en", "zh"]:
        raise ValueError("All three actual product languages are required")
    checks = value.get("checks", {})
    if set(checks) != CHECKS:
        raise ValueError("Required product checks missing or unexpected")
    for check in checks.values():
        if (not isinstance(check, dict) or check.get("status") != "passed"
                or not re.fullmatch(r"[0-9a-f]{64}", check.get("evidence_sha256", ""))):
            raise ValueError("Unpassed or unbound product check")
    bindings = value.get("input_bindings", {})
    if set(bindings) != BINDINGS or any(not re.fullmatch(r"[0-9a-f]{64}", str(h)) for h in bindings.values()):
        raise ValueError("Current scientific and presentation inputs must be bound")
    if not re.fullmatch(r"[0-9a-f]{64}", value.get("artifact_receipt_sha256", "")):
        raise ValueError("Detached artifact receipt digest missing")
    fresh_prelaunch(value, city, repository, value["artifact_receipt_sha256"],
                    now if now is not None else datetime.now(timezone.utc))
    return value


def unpack(archive: Path, output: Path) -> None:
    if output.exists() or archive.stat().st_size > 450_000_000:
        raise ValueError("Output exists or archive exceeds transfer budget")
    entries = []
    seen = set()
    total = 0
    with bounded_tar(archive) as spool, tarfile.open(fileobj=spool, mode="r:") as stream:
        for member in stream:
            if len(entries) >= 100_000 or not (member.isdir() or member.isfile()):
                raise ValueError("Unsupported archive member or excessive entries")
            name = member.name.rstrip("/") if member.isdir() else member.name
            path = PurePosixPath(name)
            if (not name or "\\" in name or path.is_absolute() or name != path.as_posix()
                    or any(p in {".", ".."} for p in path.parts)
                    or path.parts[0] != "site" or name in seen):
                raise ValueError("Noncanonical, duplicate, or unsafe archive path")
            seen.add(name)
            if len(path.parts) == 1:
                if not member.isdir():
                    raise ValueError("Archive entrance must be a directory")
                continue
            if member.size < 0 or member.size > 100_000_000:
                raise ValueError("Archive member exceeds budget")
            total += member.size
            if total > 900_000_000:
                raise ValueError("Expanded city site exceeds budget")
            entries.append((member, Path(*path.parts[1:])))
        output.mkdir(parents=True)
        for member, relative in entries:
            target = output / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = stream.extractfile(member)
            if source is None:
                raise ValueError("Unreadable archive member")
            # No archive permissions, links, or extraction hooks are applied.
            with target.open("xb") as destination:
                copied = 0
                while chunk := source.read(1024 * 1024):
                    copied += len(chunk)
                    if copied > member.size:
                        raise ValueError("Archive size mismatch")
                    destination.write(chunk)
            if copied != member.size:
                raise ValueError("Truncated archive member")


def main() -> None:
    parser = argparse.ArgumentParser()
    for argument in ["acceptance", "archive", "receipt", "output"]:
        parser.add_argument(f"--{argument}", type=Path, required=True)
    for argument in ["expected-sha256", "city", "repository", "commit"]:
        parser.add_argument(f"--{argument}", required=True)
    args = parser.parse_args()
    accepted = acceptance(args.acceptance, args.expected_sha256, args.city, args.repository, args.commit)
    unpack(args.archive, args.output)
    result = verify(args.output, args.receipt, accepted["artifact_receipt_sha256"], args.city, args.commit)
    manifest = json.loads((args.output / "safety/manifest.json").read_text())
    if manifest.get("schema_version") != 2 or manifest.get("city") != NAMES[args.city]:
        raise ValueError("Public manifest belongs to another city")
    if (args.output / "safety/cities").exists():
        raise ValueError("Shared historical city trees cannot enter a single-city site")
    print(json.dumps({"city": args.city, "files": len(result["files"]), "bytes": result["total_bytes"],
                      "accepted_code_commit": args.commit, "publication_checks": "passed"}))


if __name__ == "__main__":
    main()
