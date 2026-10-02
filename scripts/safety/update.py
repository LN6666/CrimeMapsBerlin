"""One non-LLM refresh entrypoint for manual use and OS scheduling."""

import argparse
import fcntl
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from crimemapsberlin.collector import sync

ROOT = Path(__file__).resolve().parents[2]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--full", action="store_true")
    p.add_argument("--limit", type=int, default=250)
    args = p.parse_args()
    runtime = ROOT / ".runtime/safety"
    runtime.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    with (runtime / "police.sqlite.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another collector is running; skipped overlap")
            return
        status_path = runtime / "update-status.json"
        try:
            result = sync(runtime / "police.sqlite", now.year, args.full or now.weekday() == 6, args.limit)
        except Exception as exc:
            status_path.write_text(
                json.dumps(dict(updated_at=now.isoformat(), publication="blocked", error=str(exc)), indent=2)
            )
            raise
        status = dict(updated_at=now.isoformat(), **result)
        if result["failed"] or result["errors"] or result["pending"]:
            status["publication"] = "blocked"
            status_path.write_text(json.dumps(status, indent=2))
            raise SystemExit("Source failures or pending bodies: previous map retained")
        raw = ROOT / "data/raw/safety"
        provenance = raw / "berlin-pois.source.json"
        version = (
            json.loads(provenance.read_text()).get("extraction_version") if provenance.exists() else None
        )
        if version != 2 or not all((raw / f"{name}.json").exists() for name in ("localities", "addresses")):
            # One-time local index upgrade, reusing the existing verified PBF; no remote/LLM calls.
            subprocess.run(
                [sys.executable, str(ROOT / "scripts/safety/extract_pbf.py")], cwd=ROOT, check=True
            )
        try:
            manifest_path = ROOT / "web/public/safety/manifest.json"
            prior_generation = (
                json.loads(manifest_path.read_text())["generation"]
                if manifest_path.exists() else None
            )
            subprocess.run([sys.executable, str(ROOT / "scripts/safety/build.py")], cwd=ROOT, check=True)
        except subprocess.CalledProcessError:
            status["publication"] = "blocked"
            status_path.write_text(json.dumps(status, indent=2))
            raise
        status["generation"] = json.loads(manifest_path.read_text())["generation"]
        status["publication"] = (
            "unchanged" if status["generation"] == prior_generation else "published"
        )
        status_path.write_text(json.dumps(status, indent=2))
        print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
