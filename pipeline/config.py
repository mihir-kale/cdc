"""Pipeline configuration: paths, product families, and normalization rules."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
OUT = DATA / "out"

# Operator-curated merge table. Version controlled on purpose: it is an input to
# the pipeline, not an output of it.
OVERRIDES_PATH = ROOT / "lender_aliases.csv"

RAW_ZIP = RAW / "complaints.csv.zip"
RAW_CSV = RAW / "complaints.csv"

# Cached bulk download. Refreshed daily upstream; ~348 MB compressed.
BULK_URL = "https://files.consumerfinance.gov/ccdb/complaints.csv.zip"

# Lighter alternative: the search endpoint exports an entire filtered set in one
# request when format=csv is set, ignoring frm/size. Only covers one product
# slice at a time, so the bulk file is the default ingest.
SEARCH_URL = (
    "https://www.consumerfinance.gov/data-research/consumer-complaints/"
    "search/api/v1/"
)

# ---------------------------------------------------------------------------
# Product taxonomy
# ---------------------------------------------------------------------------
# The CFPB renamed the personal-lending categories partway through the data's
# history, so a single `product = 'Payday loan'` filter captures only the
# 2013-2017 slice. Verified against the live API 2026-09-26: "Personal loan"
# returns 0 rows and has never existed as a product.
#
# Any company filing under one of these is treated as a personal lender.
PERSONAL_LENDING_PRODUCTS = [
    "Payday loan",
    "Payday loan, title loan, or personal loan",
    "Payday loan, title loan, personal loan, or advance loan",
    "Consumer Loan",
]

# A company needs at least this many complaints under the products above before
# it is called a lender. Guards against one-off complainants and against
# mis-bucketed rows.
MIN_LENDER_COMPLAINTS = 5

# ---------------------------------------------------------------------------
# Company name normalization
# ---------------------------------------------------------------------------
# Legal/entity suffixes carrying no identity information. "Enova International,
# Inc." and "ENOVA INTERNATIONAL" are the same filer.
ENTITY_SUFFIXES = {
    "INC", "INCORPORATED", "LLC", "L L C", "LP", "L P", "LLP", "L L P",
    "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LIMITED", "PLC", "PC",
    "PA", "THE", "AND", "DBA", "D/B/A", "A/K/A", "F/K/A", "N/K/A",
}

# Generic corporate-wrapper words. Stripping these merges holding companies
# around the same brand, e.g. "CURO Group Holdings" -> "CURO INTERMEDIATE".
# Only dropped when other words remain.
#
# Deliberately conservative: geographic and national words (AMERICA, NATIONAL,
# USA) are kept, because dropping them collapses genuinely distinct filers
# ("CASH AMERICA" -> "CASH") and mis-attributing complaints is worse than
# leaving a lender split across two keys.
GENERIC_WORDS = {
    "GROUP", "HOLDINGS", "HOLDING", "INTERNATIONAL", "INTL", "GLOBAL",
    "SERVICES", "SERVICE", "FINANCIAL", "FINANCE", "FINANCING", "ENTERPRISES",
    "ENTERPRISE", "CORPORATE", "CORP", "SYSTEMS", "SOLUTIONS", "PARTNERS",
    "PARTNERSHIP", "NETWORK", "COMPANY", "CO",
}

# Matches corporate-history parentheticals and suffixes, e.g.
#   "Populus Financial Group, Inc. (F/K/A Ace Cash Express)"
#   "Big Picture Loans, LLC (F/K/A)"
# These name a *different* entity, so they are captured separately as aliases
# rather than discarded outright.
HISTORY_RE = r"\((?:f/k/a|d/b/a|a/k/a|n/k/a)[^)]*\)"

# Earliest complaint date considered, as YYYY-MM-DD. None means all history.
DEFAULT_START_DATE = None

# Fields the pipeline cares about. Order matches the upstream CSV header.
SOURCE_COLUMNS = [
    "Date received",
    "Product",
    "Sub-product",
    "Issue",
    "Sub-issue",
    "Company public response",
    "Company",
    "State",
    "ZIP code",
    "Tags",
    "Submitted via",
    "Date sent to company",
    "Company response to consumer",
    "Timely response?",
    "Complaint ID",
]
