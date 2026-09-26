"""Ingest: fetch the bulk complaint file and load it into DuckDB.

The upstream CSV is ~18M rows and uses the literal string "None" for nulls,
redacts some ZIP codes as "XXXXX", and has grown extra columns over the years.
Loading is streamed by DuckDB, so peak memory stays flat regardless of size.
"""

from __future__ import annotations

import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

import duckdb

from .config import BULK_URL, OUT, RAW, RAW_CSV, RAW_ZIP
from .normalize import normalize_company, tidy_display

# Upstream header name -> internal column name. Anything not listed here is
# ignored, so upstream adding columns will not break the load.
COLUMN_MAP = {
    "Complaint ID": "complaint_id",
    "Date received": "date_received",
    "Date sent to company": "date_sent_to_company",
    "Product": "product",
    "Sub-product": "sub_product",
    "Issue": "issue",
    "Sub-issue": "sub_issue",
    "Company": "company",
    "Company response to consumer": "company_response",
    "Company public response": "company_public_response",
    "State": "state",
    "ZIP code": "zip_code",
    "Tags": "tags",
    "Submitted via": "submitted_via",
    "Timely response?": "timely_response",
    "Consumer disputed?": "consumer_disputed",
    "Consumer consent provided?": "consumer_consent_provided",
}

# Type overrides. Everything else is inferred as VARCHAR.
TYPE_MAP = {
    "complaint_id": "BIGINT",
    "date_received": "TIMESTAMP",
    "date_sent_to_company": "TIMESTAMP",
}


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def download(force: bool = False) -> Path:
    """Fetch the bulk zip if absent. Cached on disk between runs."""
    if RAW_ZIP.exists() and not force:
        return RAW_ZIP

    RAW.mkdir(parents=True, exist_ok=True)
    tmp = RAW_ZIP.with_suffix(".zip.part")
    print(f"downloading {BULK_URL}", file=sys.stderr)

    req = urllib.request.Request(BULK_URL, headers={"User-Agent": "cdc-pipeline/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        last = 0.0
        while chunk := resp.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            now = done / total if total else 0
            if now - last >= 0.05:
                last = now
                pct = f"{now * 100:5.1f}%" if total else "  ?  "
                print(
                    f"\r  {pct}  {human(done)}{'' if not total else f' / {human(total)}'}",
                    end="",
                    file=sys.stderr,
                    flush=True,
                )
    print(file=sys.stderr)
    tmp.replace(RAW_ZIP)
    return RAW_ZIP


def extract(force: bool = False) -> Path:
    """Unzip the bulk archive. The CSV is several GB uncompressed."""
    if RAW_CSV.exists() and not force:
        return RAW_CSV

    RAW.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(RAW_ZIP) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise RuntimeError(f"no CSV inside {RAW_ZIP}")
        # Archive holds a single file at the root.
        member = min(names, key=lambda n: n.count("/"))
        print(f"extracting {member} -> {RAW_CSV}", file=sys.stderr)
        with zf.open(member) as src, RAW_CSV.open("wb") as dst:
            shutil.copyfileobj(src, dst, length=1 << 22)
    return RAW_CSV


def csv_header(path: Path) -> list[str]:
    """Read just the header line to discover the real column layout."""
    with path.open("r", encoding="utf-8-sig", errors="replace") as fh:
        import csv

        for row in csv.reader(fh):
            return [c.strip() for c in row]
    return []


def connect(db_path: Path | str | None = None) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection. None means an in-memory database."""
    OUT.mkdir(parents=True, exist_ok=True)
    target = ":memory:" if db_path is None else str(db_path)
    con = duckdb.connect(target)
    con.execute("PRAGMA threads=4")
    con.execute("SET enable_progress_bar = false")
    return con


def register_functions(con: duckdb.DuckDBPyConnection) -> None:
    """Expose the Python normalizer to SQL so there is one implementation."""

    def _key(company: str | None) -> str:
        return normalize_company(company)

    def _display(company: str | None) -> str:
        return tidy_display(company)

    con.create_function(
        "company_key", _key, [duckdb.sqltype("VARCHAR")], duckdb.sqltype("VARCHAR")
    )
    con.create_function(
        "company_display",
        _display,
        [duckdb.sqltype("VARCHAR")],
        duckdb.sqltype("VARCHAR"),
    )


def available_columns(path: Path) -> dict[str, str]:
    """Map internal names to the upstream header names actually present."""
    header = csv_header(path)
    found: dict[str, str] = {}
    for upstream, internal in COLUMN_MAP.items():
        if upstream in header:
            found[internal] = upstream
    missing = sorted(set(COLUMN_MAP.values()) - set(found))
    if missing:
        print(f"  note: columns absent upstream, skipped: {', '.join(missing)}",
              file=sys.stderr)
    return found


def build_complaints(con: duckdb.DuckDBPyConnection, path: Path) -> int:
    """Materialize the cleaned `complaints` table. Returns the row count.

    Name normalization runs over the *distinct* company values, not per row.
    The source has ~18M rows but only a few thousand unique filers, so calling
    the Python normalizer 36M times is the difference between minutes and
    tens of minutes. A small company dimension table is built first and joined
    back on.
    """
    cols = available_columns(path)
    if "company" not in cols or "date_received" not in cols:
        raise RuntimeError("source CSV is missing Company or Date received")

    selects: list[str] = []
    for internal in sorted(cols):
        upstream = cols[internal]
        cast = TYPE_MAP.get(internal, "VARCHAR")
        # Force everything through VARCHAR first: auto-detection may already
        # have typed a column as DATE or BIGINT, which trim() rejects. This
        # also normalizes both null encodings the sources use (empty field in
        # the bulk CSV, the literal "None" in the search-endpoint export).
        cleaned = f"NULLIF(NULLIF(trim(CAST(\"{upstream}\" AS VARCHAR)), ''), 'None')"
        selects.append(f"{cleaned} AS \"{internal}\"" if cast == "VARCHAR"
                       else f"CAST({cleaned} AS {cast}) AS \"{internal}\"")

    raw = (
        f"read_csv('{path.as_posix()}', "
        "header=true, nullstr='None', ignore_errors=true, "
        "sample_size=200000, auto_detect=true)"
    )
    column_list = ", ".join(selects)

    con.execute("DROP TABLE IF EXISTS complaints")
    con.execute("DROP TABLE IF EXISTS company_dim")
    con.execute("DROP TABLE IF EXISTS raw_complaints")

    # 1. Staged load, no derived columns.
    con.execute(
        f"""
        CREATE TABLE raw_complaints AS
        SELECT {column_list}
        FROM {raw}
        WHERE company IS NOT NULL
          AND date_received IS NOT NULL
        """
    )

    # 2. Company dimension: one row per distinct filer, normalized in Python.
    con.execute(
        """
        CREATE TABLE company_dim AS
        SELECT company,
               company_key(company)     AS company_key,
               company_display(company) AS company_display
        FROM (SELECT DISTINCT company FROM raw_complaints)
        """
    )

    # 3. Join the dimension back on and derive the time columns.
    con.execute(
        """
        CREATE TABLE complaints AS
        SELECT
            r.*,
            d.company_key,
            d.company_display,
            EXTRACT(year  FROM r.date_received)::INTEGER AS year,
            EXTRACT(month FROM r.date_received)::INTEGER AS month,
            strftime(r.date_received, '%Y-%m')          AS year_month
        FROM raw_complaints r
        JOIN company_dim d ON r.company = d.company
        """
    )

    con.execute("DROP TABLE raw_complaints")
    return con.execute("SELECT count(*) FROM complaints").fetchone()[0]
