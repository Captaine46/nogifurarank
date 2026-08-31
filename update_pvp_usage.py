"""One-click orchestrator for a resumable NogiFura PVP usage update."""

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo


PROJECT_DIR = Path(__file__).resolve().parent


def collectorIsRunning() -> bool:
    if os.name != "nt":
        return False
    command = (
        "$running = @(Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -match '^python(w)?\\.exe$' -and "
        "$_.CommandLine -match 'nogifura_pvp_usage\\.py' }); "
        "if ($running.Count -gt 0) { exit 1 } else { exit 0 }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            cwd=PROJECT_DIR,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return result.returncode == 1


def buildSteps(
    snapshot: str,
    workers: int,
    personalWorkers: int,
    requestDelay: float,
) -> List[Tuple[str, List[str]]]:
    snapshotDir = Path("pvp_usage_output") / snapshot
    return [
        (
            "member-card release-date index",
            ["nogifura_card_release_index.py"],
        ),
        (
            "40-channel PVP usage snapshot",
            [
                "nogifura_pvp_usage.py",
                "--snapshot-name",
                snapshot,
                "--channels",
                "1-40",
                "--top",
                "20",
                "--personal-top",
                "100",
                "--workers",
                str(workers),
                "--personal-workers",
                str(personalWorkers),
                "--request-delay",
                str(requestDelay),
                "--skip-detail",
                "--fetch-personal-ranking",
            ],
        ),
        (
            "TOP50, monthly comparison, and recent-card X images",
            [
                "nogifura_pvp_x_cards.py",
                "--snapshot-dir",
                str(snapshotDir),
                "--top",
                "50",
            ],
        ),
    ]


def parseArgs(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch and build the complete NogiFura PVP usage report"
    )
    parser.add_argument(
        "snapshot",
        nargs="?",
        default=datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y%m%d"),
        help="snapshot folder name (default: today in Japan, YYYYMMDD)",
    )
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--personal-workers", type=int, default=1)
    parser.add_argument("--request-delay", type=float, default=0.8)
    parser.add_argument("--no-open", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parseArgs(argv)
    if (
        args.workers < 1
        or args.personal_workers < 1
        or args.request_delay < 0
    ):
        print("[ERROR] workers must be positive and request-delay cannot be negative")
        return 2
    if not args.snapshot or any(char in args.snapshot for char in '<>:"/\\|?*'):
        print("[ERROR] invalid snapshot name")
        return 2
    if collectorIsRunning():
        print("[BUSY] A PVP usage update is already running.")
        print("Run this launcher again after the current update finishes.")
        return 2

    print("=" * 60)
    print(" Nogifura PVP usage one-click update")
    print(f" Snapshot: {args.snapshot}")
    print("=" * 60)
    steps = buildSteps(
        args.snapshot,
        args.workers,
        args.personal_workers,
        args.request_delay,
    )
    for number, (label, command) in enumerate(steps, start=1):
        print(f"\n[{number}/{len(steps)}] {label}", flush=True)
        try:
            result = subprocess.run(
                [sys.executable, "-u", *command],
                cwd=PROJECT_DIR,
                check=False,
            )
        except OSError as exc:
            print(f"[ERROR] could not start {command[0]}: {exc}")
            return 1
        if result.returncode != 0:
            if number == 2 and result.returncode == 3:
                print("[INCOMPLETE] Some responses are missing.")
                print("Run this launcher again with the same date to resume.")
                return 3
            print(f"[ERROR] {command[0]} exited with code {result.returncode}")
            return result.returncode or 1

    snapshotDir = PROJECT_DIR / "pvp_usage_output" / args.snapshot
    reportPath = snapshotDir / "report.html"
    print(f"\n[DONE] {reportPath}")
    print(f"[DONE] {snapshotDir / 'x_cards'}")
    if not args.no_open and os.name == "nt" and reportPath.is_file():
        os.startfile(str(reportPath))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
