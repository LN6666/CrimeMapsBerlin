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
        result = sync(runtime / "police.sqlite", now.year, args.full or now.weekday() == 6, args.limit)
        # Source failure is visible, but successfully ingested records may still be published.
        subprocess.run([sys.executable, str(ROOT / "scripts/safety/build.py")], cwd=ROOT, check=True)
        status = dict(updated_at=now.isoformat(), **result)
        (runtime / "update-status.json").write_text(json.dumps(status, indent=2))
        print(json.dumps(status, indent=2))
        if result["failed"]:
            raise SystemExit(2)


if __name__ == "__main__":
    main()
