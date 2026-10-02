"""Build a local-only, hash-verified source pack for source-first LLM review."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import stat
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

CANONICAL_CITY_SLUGS = (
    "berlin",
    "hamburg",
    "munich",
    "cologne",
    "frankfurt",
    "dusseldorf",
    "stuttgart",
    "leipzig",
    "dortmund",
    "bremen",
    "essen",
    "dresden",
    "hannover",
    "nuremberg",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_checkpoint_connection(db: sqlite3.Connection) -> tuple[list[dict], dict]:
    """Normalize and verify one already-open checkpoint snapshot."""
    db.row_factory = sqlite3.Row
    columns = {row[1] for row in db.execute("PRAGMA table_info(reports)")}
    id_column = "id" if "id" in columns else "source_id" if "source_id" in columns else None
    url_column = "url" if "url" in columns else "source_url" if "source_url" in columns else None
    required = {"title", "published", "body", "sha256", "revision"}
    if id_column is None or url_column is None or not required.issubset(columns):
        raise ValueError("Checkpoint reports table has an unsupported schema")
    error_expr = "error" if "error" in columns else "NULL AS error"
    rows = []
    for row in db.execute(
        f"""SELECT {id_column} AS id,{url_column} AS url,title,published,body,
                   sha256,revision,{error_expr}
            FROM reports WHERE body IS NOT NULL ORDER BY published,{id_column}"""
    ):
        body = row["body"]
        if not isinstance(body, str) or not body.strip():
            raise ValueError(f"Stored source body is empty for {row['id']}")
        digest = sha256(body.encode("utf-8"))
        if digest != row["sha256"]:
            raise ValueError(f"Stored source hash mismatch for {row['id']}")
        if row["error"]:
            raise ValueError(f"Fetched source still has an error for {row['id']}")
        rows.append(
            {
                "source_id": row["id"],
                "source_url": row["url"],
                "title": row["title"],
                "published": row["published"],
                "source_body": body,
                "source_sha256": digest,
                "revision": row["revision"],
                "review_status": "pending",
            }
        )
    tables = {
        row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if "sachsen_queue" in tables:
        discovered = db.execute("SELECT count(*) FROM sachsen_queue").fetchone()[0]
        queue_columns = {row[1] for row in db.execute("PRAGMA table_info(sachsen_queue)")}
        errors = (
            db.execute(
                "SELECT count(*) FROM sachsen_queue WHERE COALESCE(error,'')<>''"
            ).fetchone()[0]
            if "error" in queue_columns
            else 0
        )
    else:
        discovered = db.execute("SELECT count(*) FROM reports").fetchone()[0]
        errors = (
            db.execute(
                "SELECT count(*) FROM reports WHERE COALESCE(error,'')<>''"
            ).fetchone()[0]
            if "error" in columns
            else 0
        )
    cursor_tables = [
        row[0]
        for row in db.execute(
            """SELECT name FROM sqlite_master WHERE type='table' AND
               (name LIKE '%archive_cursor' OR name IN ('archive_scan','archive_coverage'))"""
        )
    ]
    cursor_complete = []
    for table in cursor_tables:
        cursor_columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        complete_column = (
            "complete"
            if "complete" in cursor_columns
            else "historical_scan_complete"
            if "historical_scan_complete" in cursor_columns
            else None
        )
        if complete_column:
            cursor_complete.extend(
                bool(row[0]) for row in db.execute(f"SELECT {complete_column} FROM {table}")
            )
    if len({row["source_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate source IDs in checkpoint")
    return rows, {
        "discovered": discovered,
        "bodies_in_pack": len(rows),
        "missing_bodies": discovered - len(rows),
        "source_errors": errors,
        "channel_scan_complete": bool(cursor_complete) and all(cursor_complete),
    }


def read_checkpoint(path: Path) -> tuple[list[dict], dict]:
    if not path.is_file():
        raise ValueError(f"SQLite checkpoint does not exist: {path}")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        # Keep report rows, coverage counts, and cursor state on one read snapshot
        # if a collector commits new checkpoint data while the pack is built.
        db.execute("BEGIN")
        return read_checkpoint_connection(db)


def _safe_zip_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or name != path.as_posix()
        or re.match(r"^[A-Za-z]:", name)
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"Base pack contains an unsafe path: {name}")
    return path


def _verify_sidecar(sidecar: Path, pack: Path, digest: str) -> None:
    if not sidecar.is_file():
        raise ValueError(f"Base pack SHA-256 sidecar does not exist: {sidecar}")
    lines = [line for line in sidecar.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError("Base pack SHA-256 sidecar must contain exactly one entry")
    declared, separator, filename = lines[0].partition("  ")
    if (
        not separator
        or not re.fullmatch(r"[0-9a-f]{64}", declared)
        or filename != pack.name
        or declared != digest
    ):
        raise ValueError("Base pack SHA-256 does not match its sidecar")


def read_base_pack(
    path: Path, *, city: str, channel: str, sidecar_path: Path | None = None
) -> dict:
    if not path.is_file():
        raise ValueError(f"Base pack does not exist: {path}")
    pack_digest = sha256(path.read_bytes())
    sidecars = []
    if sidecar_path is not None:
        sidecars.append(sidecar_path)
    adjacent = path.with_suffix(".sha256")
    if adjacent.is_file() and all(adjacent.resolve() != item.resolve() for item in sidecars):
        sidecars.append(adjacent)
    for sidecar in sidecars:
        _verify_sidecar(sidecar, path, pack_digest)

    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ValueError("Base pack is not a valid ZIP") from exc
    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if not names or len(names) != len(set(names)):
            raise ValueError("Base pack contains no files or duplicate members")
        roots = set()
        for info in infos:
            member = _safe_zip_path(info.filename)
            if info.is_dir() or len(member.parts) < 2:
                raise ValueError("Base pack members must be files below one root directory")
            if stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK:
                raise ValueError("Base pack must not contain symbolic links")
            roots.add(member.parts[0])
        if len(roots) != 1:
            raise ValueError("Base pack must contain exactly one root directory")
        root = roots.pop() + "/"
        manifest_name = root + "MANIFEST.json"
        checksums_name = root + "CHECKSUMS.sha256"
        if manifest_name not in names or checksums_name not in names:
            raise ValueError("Base pack needs one rooted manifest and checksum file")

        checksummed = set()
        for line in archive.read(checksums_name).decode("utf-8").splitlines():
            digest, separator, relative = line.partition("  ")
            relative_path = _safe_zip_path(relative)
            if (
                not separator
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or relative in checksummed
                or relative_path.parts[0] == root.removesuffix("/")
            ):
                raise ValueError("Base pack has an invalid checksum entry")
            member = root + relative
            if member not in names or sha256(archive.read(member)) != digest:
                raise ValueError(f"Base pack checksum mismatch for {relative}")
            checksummed.add(relative)
        expected_checksums = {
            name.removeprefix(root) for name in names if name != checksums_name
        }
        if checksummed != expected_checksums:
            raise ValueError("Base pack contains unchecked or missing members")

        try:
            manifest = json.loads(archive.read(manifest_name))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Base pack manifest is invalid") from exc
        if not isinstance(manifest, dict) or manifest.get("delta_only"):
            raise ValueError("Base pack must be a complete source pack")
        if manifest.get("city") != city or manifest.get("source_channel") != channel:
            raise ValueError("Base pack city or source channel does not match")
        batch_files = manifest.get("batch_files")
        if not isinstance(batch_files, list) or not batch_files:
            raise ValueError("Base pack manifest has no batch files")

        source_hashes = {}
        for relative in batch_files:
            if not isinstance(relative, str) or not re.fullmatch(
                r"batches/source-batch-[0-9]{4}\.ndjson", relative
            ):
                raise ValueError("Base pack manifest has an unsafe batch path")
            member = root + relative
            if member not in names:
                raise ValueError(f"Base pack is missing {relative}")
            try:
                lines = archive.read(member).decode("utf-8").splitlines()
            except UnicodeDecodeError as exc:
                raise ValueError(f"Base pack batch is not UTF-8: {relative}") from exc
            for line in lines:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Base pack batch has invalid JSON: {relative}") from exc
                ident = row.get("source_id") if isinstance(row, dict) else None
                body = row.get("source_body") if isinstance(row, dict) else None
                digest = row.get("source_sha256") if isinstance(row, dict) else None
                if (
                    row.get("city") != city
                    or row.get("source_channel") != channel
                    or not isinstance(ident, str)
                    or not ident
                    or not isinstance(body, str)
                    or not body.strip()
                    or not isinstance(digest, str)
                    or sha256(body.encode("utf-8")) != digest
                    or ident in source_hashes
                ):
                    raise ValueError("Base pack contains an invalid or duplicate source record")
                source_hashes[ident] = digest
        if len(source_hashes) != manifest.get("source_bodies"):
            raise ValueError("Base pack source count does not match its manifest")
    return {
        "filename": path.name,
        "sha256": pack_digest,
        "source_bodies": len(source_hashes),
        "source_hashes": source_hashes,
    }


def review_readme(
    city: str, channel: str, coverage: dict, included: int, base_pack: dict | None
) -> str:
    delta_note = ""
    if base_pack:
        delta_note = f"""
This is a delta-only input relative to `{base_pack['filename']}`
(SHA-256 `{base_pack['sha256']}`). The verified base contains
{base_pack['source_bodies']} source IDs; this pack contains only the {included} current
checkpoint IDs absent from that base. Base IDs and source hashes were revalidated before
this pack was written.
"""
    return f"""# {city} source-first review input

This is a local-only review pack. It contains {included} complete source
bodies acquired from `{channel}` and verified against their stored SHA-256 values.
{delta_note}

## Required review order

1. Read the entire `source_body` before consulting any metadata or earlier lead.
2. Decide whether the announcement contains zero, one, or several distinct incidents.
3. Preserve every source-backed incident, accident, discovery, operation, arrest, search,
   background and unresolved physical scene. Multiple official locations are allowed.
4. A long but explicit road may remain a road range. District-only information gets no
   generated coordinate. Do not turn an arrest, hospital, police station or discovery
   location into the offence scene without source evidence.
5. Preserve the original event time on each incident when the source states it. For an
   incident inside moving public transport, use a reviewed `route` location and record the
   line and whether the source supports a complete line or a bounded segment; a later
   station search remains a separate scene.
6. POI emphasis is context only. When the source supports a type along a street/route or
   near a scene, record an explicit `poi_contexts` item; do not attribute the incident to
   one venue. Keep every separately described incident and investigation location.
7. Quote exact evidence for every semantic decision. Never invent coordinates, source IDs,
   source hashes, dates or missing source text.
8. Copy `source_sha256` exactly into every decision. A changed or missing hash blocks review.

## Output

Return one delta-only ZIP and one status Markdown file. The ZIP must contain:

- `review-decisions.delta.ndjson`
- `scene-decisions.delta.json`
- `scope-decisions.delta.ndjson`
- `open-questions.delta.md`
- `MANIFEST.json`
- `CHECKSUMS.sha256`

Each decision must include `city`, `source_id`, `source_url`, `source_sha256`, verdict,
verbatim evidence and all source-backed scene records. Keep uncertain items uncertain.
Use `schema_version: 1` in every decision. The review NDJSON adds `verdict`,
`evidence_quotes`, `review_note`, `reviewer` and timezone-aware `reviewed_at`; the scope
NDJSON adds `scope_verdict` and `evidence_quotes`. The scene JSON envelope is
`{{"schema_version":1,"city":"{city}","articles":[...]}}`; every article declares
`incident_count`, complete `incidents` and complete `formal_locations`, including an
evidence quote for every incident and location. Zero, one and multiple incidents are valid.
An incident may add source-backed `event_time` and `details`. A location may add
`transit_route` and `poi_contexts`; these fields are optional when the source does not
support them and mandatory when needed to express the reviewed moving-route or POI context.
Do not mark archive coverage complete: this pack reports
`channel_scan_complete={str(coverage['channel_scan_complete']).lower()}`,
`missing_bodies={coverage['missing_bodies']}` and `source_errors={coverage['source_errors']}`.
"""


def build_pack(
    *, city: str, db_path: Path, channel: str, output_dir: Path, batch_size: int,
    base_pack_path: Path | None = None, base_pack_sidecar: Path | None = None,
) -> tuple[Path, Path, Path]:
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,31}", city):
        raise ValueError("City must be a stable lowercase slug")
    if not 1 <= batch_size <= 200:
        raise ValueError("Batch size must be from 1 to 200")
    rows, coverage = read_checkpoint(db_path)
    if not rows:
        raise ValueError("No verified source bodies are available for a review pack")
    base_pack = None
    if base_pack_path:
        base_pack = read_base_pack(
            base_pack_path, city=city, channel=channel, sidecar_path=base_pack_sidecar
        )
        current_hashes = {row["source_id"]: row["source_sha256"] for row in rows}
        for ident, digest in base_pack["source_hashes"].items():
            if current_hashes.get(ident) != digest:
                raise ValueError(f"Base source is missing or changed in checkpoint: {ident}")
        rows = [row for row in rows if row["source_id"] not in base_pack["source_hashes"]]
        base_ids = set(base_pack["source_hashes"])
        delta_ids = {row["source_id"] for row in rows}
        if base_ids & delta_ids or len(base_ids | delta_ids) != coverage["bodies_in_pack"]:
            raise ValueError("Base and delta source IDs do not safely cover the checkpoint")
        if not rows:
            raise ValueError("No source IDs remain after subtracting the base pack")
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    delta = "-delta" if base_pack else ""
    stem = f"CrimeMapsDE-{city}-source-review-input{delta}-{stamp}"
    root = stem + "/"
    files: dict[str, bytes] = {}
    for number, start in enumerate(range(0, len(rows), batch_size), start=1):
        payload = b"".join(
            (
                json.dumps(
                    {"city": city, "source_channel": channel, **row},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
            for row in rows[start : start + batch_size]
        )
        files[f"batches/source-batch-{number:04d}.ndjson"] = payload
    readme = review_readme(city, channel, coverage, len(rows), base_pack).encode("utf-8")
    files["README.md"] = readme
    manifest = {
        "schema_version": 1,
        "pack_id": stem,
        "created_at": datetime.now(UTC).isoformat(),
        "city": city,
        "source_channel": channel,
        "source_bodies": len(rows),
        "batch_size": batch_size,
        "batch_files": sorted(name for name in files if name.startswith("batches/")),
        "coverage": coverage,
        "publication_ready": False,
        "contains_raw_official_bodies": True,
        "commit_to_git": False,
    }
    if base_pack:
        manifest.update(
            {
                "delta_only": True,
                "base_pack": {
                    key: base_pack[key] for key in ("filename", "sha256", "source_bodies")
                },
                "base_source_bodies": base_pack["source_bodies"],
                "delta_source_bodies": len(rows),
                "combined_source_bodies": base_pack["source_bodies"] + len(rows),
            }
        )
    files["MANIFEST.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    checksums = "".join(
        f"{sha256(data)}  {name}\n" for name, data in sorted(files.items())
    ).encode("utf-8")
    files["CHECKSUMS.sha256"] = checksums

    zip_path = output_dir / f"{stem}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(root + name, data)
    external = output_dir / f"{stem}.sha256"
    external.write_text(f"{sha256(zip_path.read_bytes())}  {zip_path.name}\n", encoding="utf-8")
    status = output_dir / f"{stem}-STATUS.md"
    base_status = ""
    if base_pack:
        base_status = (
            f"- Base pack: `{base_pack['filename']}`\n"
            f"- Base pack SHA-256: `{base_pack['sha256']}`\n"
            f"- Base source IDs revalidated: {base_pack['source_bodies']}"
        )
    status.write_text(
        f"""# {city} source review pack status

- Source channel: `{channel}`
- Discovered records in checkpoint: {coverage['discovered']}
- Verified bodies in checkpoint: {coverage['bodies_in_pack']}
- Bodies included in this pack: {len(rows)}
- Missing bodies: {coverage['missing_bodies']}
- Source errors: {coverage['source_errors']}
- Channel scan complete: {coverage['channel_scan_complete']}
{base_status}
- ZIP SHA-256: `{sha256(zip_path.read_bytes())}`

This package is an input for source-first LLM review. It is not a completed city map,
an owner-approved review set or evidence of complete police-report coverage.
""",
        encoding="utf-8",
    )
    return zip_path, external, status


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", choices=CANONICAL_CITY_SLUGS, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--channel", required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".runtime/source-review-packs"),
        help="Local output directory; defaults to a Git-ignored runtime path",
    )
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--base-pack", type=Path)
    parser.add_argument("--base-pack-sha256", type=Path)
    args = parser.parse_args()
    if args.base_pack_sha256 and not args.base_pack:
        parser.error("--base-pack-sha256 requires --base-pack")
    paths = build_pack(
        city=args.city,
        db_path=args.db,
        channel=args.channel,
        output_dir=args.output_dir,
        batch_size=args.batch_size,
        base_pack_path=args.base_pack,
        base_pack_sidecar=args.base_pack_sha256,
    )
    print(json.dumps({"created": [str(path) for path in paths]}, indent=2))


if __name__ == "__main__":
    main()
