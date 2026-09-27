"""Install/remove a user-level macOS timer. No Codex/LLM is involved."""

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LABEL = "org.crimemapsberlin.update"
DEST = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["install", "remove", "show"])
    args = p.parse_args()
    job = dict(
        Label=LABEL,
        ProgramArguments=[str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/safety/update.py")],
        WorkingDirectory=str(ROOT),
        EnvironmentVariables={"PYTHONPATH": str(ROOT / "src")},
        StartCalendarInterval={"Hour": 7, "Minute": 15},
        RunAtLoad=False,
        StandardOutPath=str(ROOT / ".runtime/safety/scheduled.log"),
        StandardErrorPath=str(ROOT / ".runtime/safety/scheduled-error.log"),
        ProcessType="Background",
        LowPriorityIO=True,
    )
    if args.action == "show":
        print(plistlib.dumps(job).decode())
        return
    if sys.platform != "darwin":
        raise SystemExit("Use cron/systemd on Linux; see docs/UPDATES.md")
    target = f"gui/{os.getuid()}"
    if args.action == "remove":
        subprocess.run(["launchctl", "bootout", target + "/" + LABEL], check=False)
        DEST.unlink(missing_ok=True)
        return
    if not (ROOT / ".venv/bin/python").exists():
        raise SystemExit("Run uv sync first")
    DEST.parent.mkdir(parents=True, exist_ok=True)
    (ROOT / ".runtime/safety").mkdir(parents=True, exist_ok=True)
    if DEST.exists():
        subprocess.run(["launchctl", "bootout", target + "/" + LABEL], check=False)
    DEST.write_bytes(plistlib.dumps(job))
    subprocess.run(["launchctl", "bootstrap", target, str(DEST)], check=True)
    print(f"Installed {DEST}: daily 07:15 local time, no immediate run")


if __name__ == "__main__":
    main()
