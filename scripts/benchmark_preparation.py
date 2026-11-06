"""Run each business in an isolated process; measure cold/warm preparation and RSS.

PYTHONPATH=src .venv/bin/python scripts/benchmark_preparation.py --train-dir data/train --output-dir data/regression-cache --report data/preparation-benchmark.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--business")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--jobs", type=int, default=1)
    args = parser.parse_args()
    if args.worker:
        from datamate.ingestion import prepare_business

        started = time.monotonic()
        result = prepare_business(
            args.train_dir / "data" / args.business,
            args.output_dir,
            rulebook=args.train_dir / "rulebook.md",
            calendar=args.train_dir / "calendar.csv",
        )
        payload = result.to_dict()
        payload["wall_seconds"] = time.monotonic() - started
        payload["peak_rss_mib"] = (
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        )
        print(json.dumps(payload))
        return
    before = {str(p): digest(p) for p in args.train_dir.rglob("*") if p.is_file()}
    results = []
    businesses = (
        [args.train_dir / "data" / args.business]
        if args.business
        else sorted((args.train_dir / "data").glob("biz_*"))
    )

    def run_business(business):
        record = {"business_id": business.name}
        for mode in ("cold", "warm"):
            command = [
                sys.executable,
                __file__,
                "--worker",
                "--business",
                business.name,
                "--train-dir",
                str(args.train_dir),
                "--output-dir",
                str(args.output_dir),
                "--report",
                str(args.report),
            ]
            run = subprocess.run(
                command, capture_output=True, text=True, env=os.environ, check=False
            )
            if run.returncode:
                record[mode] = {"error": run.stderr.strip()}
                print(business.name, mode, run.stderr.strip(), flush=True)
                break
            payload = json.loads(run.stdout)
            record[mode] = payload
            print(
                business.name,
                mode,
                round(payload["wall_seconds"], 2),
                "s",
                round(payload["peak_rss_mib"], 1),
                "MiB",
                "hit=" + str(payload["cache_hit"]),
                payload["quality_summary"]["issues"],
                flush=True,
            )
        return record

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for completed in as_completed(
            [pool.submit(run_business, b) for b in businesses]
        ):
            results.append(completed.result())
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps({"results": results}, indent=2, ensure_ascii=False)
            )
    unchanged = all(
        Path(p).is_file() and digest(Path(p)) == d for p, d in before.items()
    )
    report = {
        "jobs": args.jobs,
        "source_unchanged": unchanged,
        "source_files_hashed": len(before),
        "results": results,
    }
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    if not unchanged or any(
        "error" in r.get(m, {}) for r in results for m in ("cold", "warm")
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
