"""Build a local-only, hash-verified source pack for source-first LLM review."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import zipfile
from datetime import UTC, datetime
from pathlib import Path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_checkpoint(path: Path) -> tuple[list[dict], dict]:
    if not path.is_file():
        raise ValueError(f"SQLite checkpoint does not exist: {path}")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        # Keep report rows, coverage counts, and cursor state on one read snapshot
        # if a collector commits new checkpoint data while the pack is built.
        db.execute("BEGIN")
        columns = {row[1] for row in db.execute("PRAGMA table_info(reports)")}
        required = {"id", "url", "title", "published", "body", "sha256", "revision"}
        if not required.issubset(columns):
            raise ValueError("Checkpoint reports table has an unsupported schema")
        error_expr = "error" if "error" in columns else "NULL AS error"
        rows = []
        for row in db.execute(
            f"""SELECT id,url,title,published,body,sha256,revision,{error_expr}
                FROM reports WHERE body IS NOT NULL ORDER BY published,id"""
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
        discovered = db.execute("SELECT count(*) FROM reports").fetchone()[0]
        errors = (
            db.execute("SELECT count(*) FROM reports WHERE error IS NOT NULL").fetchone()[0]
            if "error" in columns
            else 0
        )
        cursor_tables = [
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%archive_cursor'"
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
                cursor_complete.extend(bool(row[0]) for row in db.execute(
                    f"SELECT {complete_column} FROM {table}"
                ))
    if len({row["source_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate source IDs in checkpoint")
    return rows, {
        "discovered": discovered,
        "bodies_in_pack": len(rows),
        "missing_bodies": discovered - len(rows),
        "source_errors": errors,
        "channel_scan_complete": bool(cursor_complete) and all(cursor_complete),
    }


def review_readme(city: str, channel: str, coverage: dict) -> str:
    return f"""# {city} source-first review input

This is a local-only review pack. It contains {coverage['bodies_in_pack']} complete source
bodies acquired from `{channel}` and verified against their stored SHA-256 values.

## Required review order

1. Read the entire `source_body` before consulting any metadata or earlier lead.
2. Decide whether the announcement contains zero, one, or several distinct incidents.
3. Preserve every source-backed incident, accident, discovery, operation, arrest, search,
   background and unresolved physical scene. Multiple official locations are allowed.
4. A long but explicit road may remain a road range. District-only information gets no
   generated coordinate. Do not turn an arrest, hospital, police station or discovery
   location into the offence scene without source evidence.
5. Quote exact evidence for every semantic decision. Never invent coordinates, source IDs,
   source hashes, dates or missing source text.
6. Copy `source_sha256` exactly into every decision. A changed or missing hash blocks review.

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
Do not mark archive coverage complete: this pack reports
`channel_scan_complete={str(coverage['channel_scan_complete']).lower()}`,
`missing_bodies={coverage['missing_bodies']}` and `source_errors={coverage['source_errors']}`.
"""


def build_pack(
    *, city: str, db_path: Path, channel: str, output_dir: Path, batch_size: int
) -> tuple[Path, Path, Path]:
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,31}", city):
        raise ValueError("City must be a stable lowercase slug")
    if not 1 <= batch_size <= 200:
        raise ValueError("Batch size must be from 1 to 200")
    rows, coverage = read_checkpoint(db_path)
    if not rows:
        raise ValueError("No verified source bodies are available for a review pack")
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stem = f"CrimeMapsDE-{city}-source-review-input-{stamp}"
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
    readme = review_readme(city, channel, coverage).encode("utf-8")
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
    status.write_text(
        f"""# {city} source review pack status

- Source channel: `{channel}`
- Discovered records in checkpoint: {coverage['discovered']}
- Verified bodies included: {coverage['bodies_in_pack']}
- Missing bodies: {coverage['missing_bodies']}
- Source errors: {coverage['source_errors']}
- Channel scan complete: {coverage['channel_scan_complete']}
- ZIP SHA-256: `{sha256(zip_path.read_bytes())}`

This package is an input for source-first LLM review. It is not a completed city map,
an owner-approved review set or evidence of complete police-report coverage.
""",
        encoding="utf-8",
    )
    return zip_path, external, status


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--channel", required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".runtime/source-review-packs"),
        help="Local output directory; defaults to a Git-ignored runtime path",
    )
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    paths = build_pack(
        city=args.city,
        db_path=args.db,
        channel=args.channel,
        output_dir=args.output_dir,
        batch_size=args.batch_size,
    )
    print(json.dumps({"created": [str(path) for path in paths]}, indent=2))


if __name__ == "__main__":
    main()
