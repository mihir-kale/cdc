"""Per-lender metrics: counts, categories, trends, and response rates.

Every query is scoped to the resolved lender roster, and because the roster
merges name variants, results are reported per `lender_id` rather than per raw
`company_key`.

Response-rate definitions, since the upstream columns are easy to misread:

  * A company only populates "Company response to consumer" and "Timely
    response?" when it actually responded. Rows with a null response are
    *unanswered*, not "untimely", so the response rate is reported over all
    complaints and the timely rate over responded complaints only.
  * "Timely response?" is Yes/No, and only present for a subset of responses.
"""

from __future__ import annotations

from pathlib import Path

from .config import OUT, PERSONAL_LENDING_PRODUCTS

# Categories treated as "the company responded at all".
RESPONSE_PRESENT = "company_response IS NOT NULL"

TIMELY_YES = "UPPER(trim(timely_response)) = 'YES'"
TIMELY_NO = "UPPER(trim(timely_response)) = 'NO'"


def sql_list(values: list[str]) -> str:
    """Render a Python list as a SQL literal list.

    DuckDB's `?` parameters are positional and cannot be reused across
    clauses, and these product names are trusted constants from config, so
    inlining is simpler than threading parameters through every query.
    """
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


PERSONAL = sql_list(PERSONAL_LENDING_PRODUCTS)


def write_csv(con, query: str, path: Path) -> int:
    """Run a query and write the result to CSV. Returns the row count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rel = path.as_posix()
    con.execute(f"COPY ({query}) TO '{rel}' (HEADER, DELIMITER ',')")
    return con.execute(f"SELECT count(*) FROM read_csv_auto('{rel}')").fetchone()[0]


def lender_summary(con) -> None:
    """One row per lender: the headline dataset."""
    query = f"""
    WITH base AS (
        SELECT c.*, m.lender_id, l.display_name
        FROM complaints c
        JOIN lender_map m USING (company_key)
        JOIN lenders   l ON m.lender_id = l.lender_id
    ),
    personal AS (
        SELECT lender_id, count(*) AS n
        FROM base WHERE product IN ({PERSONAL})
        GROUP BY lender_id
    ),
    resp AS (
        SELECT
            lender_id,
            count(*) FILTER ({RESPONSE_PRESENT}) AS responded,
            count(*) FILTER ({TIMELY_YES})        AS timely_yes,
            count(*) FILTER ({TIMELY_NO})         AS timely_no,
            median(date_diff('day', date_received, date_sent_to_company))
                FILTER (WHERE date_sent_to_company IS NOT NULL) AS median_days_to_reply
        FROM base
        GROUP BY lender_id
    )
    SELECT
        b.lender_id,
        b.display_name,
        count(*)                                            AS total_complaints,
        any_value(pr.n)                                     AS personal_lending_complaints,
        round(100.0 * count(*) FILTER (WHERE b.product IN ({PERSONAL}))
              / nullif(count(*), 0), 1)                     AS pct_personal_lending,
        min(b.date_received)::DATE                          AS first_complaint,
        max(b.date_received)::DATE                          AS last_complaint,
        count(DISTINCT b.state)                             AS states,
        count(DISTINCT b.product)                           AS products,
        count(DISTINCT b.issue)                             AS issues,
        count(*) FILTER (WHERE b.company_public_response IS NOT NULL)
                                                           AS with_public_response,
        count(*) FILTER ({RESPONSE_PRESENT})                AS responded,
        round(100.0 * count(*) FILTER ({RESPONSE_PRESENT})
              / nullif(count(*), 0), 1)                     AS response_rate_pct,
        count(*) FILTER ({TIMELY_NO})                       AS untimely,
        count(*) FILTER ({TIMELY_YES})                      AS timely,
        r.median_days_to_reply                              AS median_days_to_reply
    FROM base b
    LEFT JOIN personal pr USING (lender_id)
    LEFT JOIN resp     r  USING (lender_id)
    GROUP BY b.lender_id, b.display_name, r.median_days_to_reply
    ORDER BY total_complaints DESC
    """
    rows = write_csv(con, query, OUT / "lenders.csv")
    print(f"  lenders.csv              {rows:>7,} rows")


def lender_breakdowns(con) -> None:
    """Long-format category breakdowns: product, issue, state, submitted via."""
    for field, label in (
        ("product", "lender_product"),
        ("issue", "lender_issue"),
        ("state", "lender_state"),
        ("submitted_via", "lender_submitted_via"),
    ):
        query = f"""
        SELECT
            m.lender_id,
            '{field}'                AS dimension,
            c.{field}                AS value,
            count(*)                 AS complaints,
            round(100.0 * count(*) / sum(count(*)) OVER (PARTITION BY m.lender_id), 1)
                                     AS pct_of_lender,
            count(*) FILTER (WHERE c.product IN ({PERSONAL})) AS personal_lending_complaints
        FROM complaints c
        JOIN lender_map m USING (company_key)
        WHERE c.{field} IS NOT NULL
        GROUP BY m.lender_id, c.{field}
        ORDER BY m.lender_id, complaints DESC
        """
        rows = write_csv(con, query, OUT / f"{label}.csv")
        print(f"  {label + '.csv':<25} {rows:>7,} rows")


def lender_trends(con) -> None:
    """Monthly complaint counts, for spotting volume changes over time."""
    query = f"""
    SELECT
        m.lender_id,
        c.year_month,
        min(c.year)                AS year,
        count(*)                   AS complaints,
        count(*) FILTER (WHERE c.product IN ({PERSONAL})) AS personal_lending_complaints,
        count(*) FILTER ({RESPONSE_PRESENT})       AS responded,
        count(*) FILTER ({TIMELY_NO})              AS untimely
    FROM complaints c
    JOIN lender_map m USING (company_key)
    GROUP BY m.lender_id, c.year_month
    ORDER BY m.lender_id, c.year_month
    """
    rows = write_csv(con, query, OUT / "lender_monthly.csv")
    print(f"  lender_monthly.csv       {rows:>7,} rows")


def lender_responses(con) -> None:
    """Distribution of the company's response to the consumer."""
    query = """
    SELECT
        m.lender_id,
        coalesce(c.company_response, '(no response)')  AS company_response,
        upper(trim(coalesce(c.timely_response, 'n/a'))) AS timely_response,
        count(*)                                       AS complaints,
        round(100.0 * count(*) / sum(count(*)) OVER (PARTITION BY m.lender_id), 1)
                                                       AS pct_of_lender
    FROM complaints c
    JOIN lender_map m USING (company_key)
    GROUP BY m.lender_id, 2, 3
    ORDER BY m.lender_id, complaints DESC
    """
    rows = write_csv(con, query, OUT / "lender_responses.csv")
    print(f"  lender_responses.csv     {rows:>7,} rows")


def name_audit(con) -> None:
    """Which raw spellings were merged into each lender. The audit trail."""
    query = f"""
    SELECT
        m.lender_id,
        c.company_key,
        any_value(c.company_display)        AS example_name,
        count(*)                            AS complaints,
        count(*) FILTER (WHERE c.product IN ({PERSONAL})) AS personal_lending_complaints,
        min(c.date_received)::DATE          AS first_seen,
        max(c.date_received)::DATE          AS last_seen
    FROM complaints c
    JOIN lender_map m USING (company_key)
    GROUP BY m.lender_id, c.company_key
    ORDER BY m.lender_id, complaints DESC
    """
    rows = write_csv(con, query, OUT / "lender_name_audit.csv")
    print(f"  lender_name_audit.csv    {rows:>7,} rows")


def complaint_level(con) -> None:
    """Complaint-level slice for every matched lender, in all products."""
    path = OUT / "lender_complaints.csv"
    rel = path.as_posix()
    con.execute(
        f"""
        COPY (
            SELECT
                c.complaint_id,
                m.lender_id,
                c.company_key,
                c.company,
                c.date_received,
                c.date_sent_to_company,
                c.product,
                c.sub_product,
                c.issue,
                c.sub_issue,
                c.state,
                c.zip_code,
                c.submitted_via,
                c.company_response,
                c.company_public_response,
                c.timely_response,
                c.tags,
                c.year,
                c.month,
                c.year_month
            FROM complaints c
            JOIN lender_map m USING (company_key)
            ORDER BY m.lender_id, c.date_received
        ) TO '{rel}' (HEADER, DELIMITER ',')
        """
    )
    n = con.execute(f"SELECT count(*) FROM read_csv_auto('{rel}')").fetchone()[0]
    print(f"  lender_complaints.csv    {n:>7,} rows")


def build_lender_tables(con, lenders: list[dict], key_to_lender: dict[str, str]) -> None:
    """Materialize the two tables the metric queries join against.

    `lenders` is one row per resolved lender (identity + provenance).
    `lender_map` resolves a raw company_key to its lender, so every complaint
    row can be attributed after name variants have been merged.
    """
    con.execute("DROP TABLE IF EXISTS lenders")
    con.execute("DROP TABLE IF EXISTS lender_map")
    con.execute(
        """
        CREATE TABLE lenders (
            lender_id                   VARCHAR,
            display_name                VARCHAR,
            rank                        INTEGER,
            personal_lending_complaints BIGINT,
            name_variants               INTEGER,
            first_personal_complaint    DATE,
            last_personal_complaint     DATE
        )
        """
    )
    con.executemany(
        "INSERT INTO lenders VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                r["lender_id"],
                r["display_name"],
                r["rank"],
                r["personal_lending_complaints"],
                r["name_variants"],
                r["first_personal_complaint"],
                r["last_personal_complaint"],
            )
            for r in lenders
        ],
    )

    con.execute("CREATE TABLE lender_map (company_key VARCHAR, lender_id VARCHAR)")
    pairs = [(k, v) for k, v in key_to_lender.items()]
    for i in range(0, len(pairs), 1000):
        con.executemany("INSERT INTO lender_map VALUES (?, ?)", pairs[i : i + 1000])

    stored = con.execute("SELECT count(*) FROM lender_map").fetchone()[0]
    print(f"  lender tables             {len(lenders):>7,} lenders, {stored:,} keys")


def write_roster(lenders: list[dict], path: Path | None = None) -> None:
    """The roster itself, with merge provenance, for review."""
    import csv

    path = path or (OUT / "lender_roster.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "rank",
        "lender_id",
        "display_name",
        "personal_lending_complaints",
        "name_variants",
        "merged_keys",
        "name_spellings",
        "first_personal_complaint",
        "last_personal_complaint",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for row in lenders:
            out = dict(row)
            out["merged_keys"] = " | ".join(row["merged_keys"])
            out["name_spellings"] = " | ".join(row["name_spellings"])
            w.writerow({k: out.get(k) for k in fields})
    print(f"  lender_roster.csv        {len(lenders):>7,} rows")
