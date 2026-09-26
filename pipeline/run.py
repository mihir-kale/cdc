#!/usr/bin/env python
"""Build the lender-level complaint dataset.

    python -m pipeline.run                # full run, reusing cached source
    python -m pipeline.run --reload       # rebuild the cached complaints table
    python -m pipeline.run --source-only  # just fetch and extract the raw CSV

Stages:
  1. ingest    download + extract + load the cleaned `complaints` table
  2. roster    resolve name variants, derive the payday/personal lender list
  3. metrics   counts, categories, trends, response rates -> data/out/*.csv

The loaded table and the raw CSV are both cached, so a second run only redoes
the cheap aggregation steps.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import ingest, lenders as lenders_mod, metrics
from .config import DATA, OUT, PERSONAL_LENDING_PRODUCTS, RAW_CSV

DB_PATH = DATA / "cdc.duckdb"


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def ensure_source(download_it: bool, extract_it: bool) -> Path:
    if download_it:
        ingest.download()
    if extract_it:
        return ingest.extract()
    if not RAW_CSV.exists():
        log("raw CSV missing, extracting")
        return ingest.extract()
    return RAW_CSV


def table_ready(con) -> bool:
    row = con.execute(
        "SELECT count(*) FROM duckdb_tables() WHERE table_name = 'complaints'"
    ).fetchone()
    return bool(row and row[0])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--reload", action="store_true", help="rebuild the cached complaints table"
    )
    ap.add_argument(
        "--no-download", action="store_true", help="use the already-downloaded zip"
    )
    ap.add_argument("--source-only", action="store_true", help="stop after ingest")
    ap.add_argument("--db", type=Path, default=DB_PATH, help="DuckDB file to use")
    args = ap.parse_args(argv)

    t0 = time.time()

    log("[1/3] ingest")
    csv_path = ensure_source(not args.no_download, True)
    log(f"  source: {csv_path} ({human(csv_path.stat().st_size)})")

    con = ingest.connect(args.db)
    ingest.register_functions(con)

    if args.reload or not table_ready(con):
        t = time.time()
        n = ingest.build_complaints(con, csv_path)
        log(f"  loaded {n:,} complaints in {time.time() - t:.0f}s -> {args.db}")
    else:
        n = con.execute("SELECT count(*) FROM complaints").fetchone()[0]
        log(f"  reusing cached table ({n:,} complaints)")

    span = con.execute(
        "SELECT min(date_received)::DATE, max(date_received)::DATE FROM complaints"
    ).fetchone()
    log(f"  date range: {span[0]} .. {span[1]}")

    if args.source_only:
        return 0

    log("[2/3] roster")
    t = time.time()
    roster, key_to_lender = lenders_mod.build_roster(con)
    log(
        f"  {len(roster):,} lenders from "
        f"{len({m for r in roster for m in r['merged_keys']}):,} name keys "
        f"in {time.time() - t:.0f}s"
    )
    metrics.write_roster(roster)
    metrics.build_lender_tables(con, roster, key_to_lender)

    log("[3/3] metrics")
    OUT.mkdir(parents=True, exist_ok=True)
    metrics.lender_summary(con)
    metrics.lender_breakdowns(con)
    metrics.lender_trends(con)
    metrics.lender_responses(con)
    metrics.name_audit(con)
    metrics.complaint_level(con)

    con.close()
    log(f"done in {time.time() - t0:.0f}s -> {OUT}")
    log(f"personal-lending products: {PERSONAL_LENDING_PRODUCTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
