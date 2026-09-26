"""Derive the payday/personal lender roster from the complaint data.

Identification is data-driven: any company filing at least
`MIN_LENDER_COMPLAINTS` complaints under the personal-lending product
categories is treated as a lender. The CFPB taxonomy changed mid-stream, so
those categories are a union, not a single label.

Name variants are then merged in two ways:

  * Corporate-history aliases. "Populus Financial Group, Inc. (F/K/A Ace Cash
    Express)" is unioned with any rows filed as "Ace Cash Express", because the
    annotation names a predecessor of the same filer.
  * Operator overrides from `data/lender_aliases.csv`, for the pairs no
    heuristic can safely merge (e.g. a rebrand that shares no words).

Every merge is recorded, so the output can be audited back to raw names.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from .config import MIN_LENDER_COMPLAINTS, OVERRIDES_PATH, PERSONAL_LENDING_PRODUCTS
from .normalize import apply_overrides, extract_aliases, normalize_company


class UnionFind:
    """Minimal disjoint-set with path compression."""

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, item: str) -> None:
        self.parent.setdefault(item, item)

    def find(self, item: str) -> str:
        self.add(item)
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != root:
            self.parent[item], item = root, self.parent[item]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # Deterministic: the lexicographically smaller key wins, so reruns
            # produce the same lender_id.
            lo, hi = sorted((ra, rb))
            self.parent[hi] = lo

    def groups(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for item in self.parent:
            out.setdefault(self.find(item), []).append(item)
        return out


def load_overrides(path: Path = OVERRIDES_PATH) -> dict[str, str]:
    """Read `source_key,target_key` overrides written by an operator.

    Keys are normalized on read, so the file can be written with whatever
    spelling is convenient. Both key and value must normalize to a non-empty
    string, otherwise the row is rejected.
    """
    if not path.exists():
        return {}
    overrides: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            src = normalize_company((row.get("source") or "").strip())
            dst = normalize_company((row.get("target") or "").strip())
            if src and dst and src != dst:
                overrides[src] = dst
    return overrides


def personal_lending_counts(con) -> dict[str, int]:
    """Complaint counts per company_key within the personal-lending products."""
    placeholders = ", ".join("?" for _ in PERSONAL_LENDING_PRODUCTS)
    rows = con.execute(
        f"""
        SELECT company_key, count(*) AS n
        FROM complaints
        WHERE product IN ({placeholders})
          AND company_key <> ''
        GROUP BY company_key
        """,
        PERSONAL_LENDING_PRODUCTS,
    ).fetchall()
    return {k: n for k, n in rows if k}


def alias_links(con) -> list[tuple[str, str]]:
    """Pairs of company_keys joined by a corporate-history annotation.

    Only emitted when the alias actually resolves to a *different* key that
    also appears in the data, which keeps the union from inventing entities.

    Reads from `company_dim` rather than `complaints`: only distinct filer
    names matter here, and the dimension table is orders of magnitude smaller.
    """
    rows = con.execute(
        """
        SELECT DISTINCT company_key, company
        FROM company_dim
        WHERE company ILIKE '%f/k/a%'
           OR company ILIKE '%d/b/a%'
           OR company ILIKE '%a/k/a%'
           OR company ILIKE '%n/k/a%'
        """
    ).fetchall()

    known = {
        r[0]
        for r in con.execute(
            "SELECT DISTINCT company_key FROM company_dim WHERE company_key <> ''"
        ).fetchall()
    }

    links: list[tuple[str, str]] = []
    for key, company in rows:
        for alias in extract_aliases(company or ""):
            alias_key = normalize_company(alias)
            if alias_key and alias_key != key and alias_key in known:
                links.append((key, alias_key))
    return links


def build_roster(con) -> tuple[list[dict], dict[str, str]]:
    """Return (lender rows, company_key -> lender_id).

    Each lender row carries the metrics needed to audit the decision: how many
    personal-lending complaints qualified it, which raw name spellings were
    merged, and the date span of its personal-lending activity.
    """
    counts = personal_lending_counts(con)
    candidates = {
        k for k, n in counts.items() if n >= MIN_LENDER_COMPLAINTS
    }

    uf = UnionFind()
    for key in counts:
        uf.add(key)

    for a, b in alias_links(con):
        # Only merge inside the candidate set; a predecessor that never filed
        # personal-lending complaints is not itself a lender here.
        if a in candidates and b in candidates:
            uf.union(a, b)

    overrides = load_overrides()
    if overrides:
        for src, dst in overrides.items():
            if src in candidates and dst in candidates:
                uf.union(src, dst)

    # Pick a canonical display name per group: the most frequent raw spelling,
    # tie-broken by the shortest then alphabetical, so runs are reproducible.
    # Aggregated in SQL; doing this in Python would stream all 18M rows.
    names: dict[str, Counter] = {}
    for key, display, n in con.execute(
        """
        SELECT company_key, company_display, count(*)
        FROM complaints
        WHERE company_key <> '' AND company_display <> ''
        GROUP BY company_key, company_display
        """
    ).fetchall():
        names.setdefault(key, Counter())[display] = n

    spans = {
        key: (first, last)
        for key, first, last in con.execute(
            f"""
            SELECT company_key,
                   min(date_received) AS first_seen,
                   max(date_received) AS last_seen
            FROM complaints
            WHERE product IN ({", ".join("?" for _ in PERSONAL_LENDING_PRODUCTS)})
              AND company_key <> ''
            GROUP BY company_key
            """,
            PERSONAL_LENDING_PRODUCTS,
        ).fetchall()
    }

    lenders: list[dict] = []
    key_to_lender: dict[str, str] = {}

    for root, members in sorted(uf.groups().items()):
        if root not in candidates:
            continue

        variants: Counter = Counter()
        personal_total = 0
        for member in members:
            personal_total += counts.get(member, 0)
            variants.update(names.get(member, {}))

        if personal_total < MIN_LENDER_COMPLAINTS:
            continue

        display = sorted(
            variants.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0])
        )[0][0]

        lender_id = min(members)
        span = spans.get(root) or spans.get(lender_id)

        lenders.append(
            {
                "lender_id": lender_id,
                "display_name": display,
                "personal_lending_complaints": personal_total,
                "name_variants": len(variants),
                "merged_keys": sorted(members),
                "name_spellings": sorted(variants),
                "first_personal_complaint": span[0].date().isoformat() if span else None,
                "last_personal_complaint": span[1].date().isoformat() if span else None,
            }
        )
        for member in members:
            key_to_lender[member] = lender_id

    lenders.sort(key=lambda r: -r["personal_lending_complaints"])
    for rank, row in enumerate(lenders, start=1):
        row["rank"] = rank
    return lenders, key_to_lender
