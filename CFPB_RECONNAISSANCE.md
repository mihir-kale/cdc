# CFPB Dataset Reconnaissance — FinePrint Lender Scoring Workstream

**Prepared for:** lender evaluation / scoring methodology design
**Date:** 2026-09-26
**Repo state examined:** branch `main`, HEAD `a95253b`, working tree clean, 1 commit ahead of `origin/main`
**Primary dataset:** `data/raw/paydayComplaints.csv`
**Status:** exploratory only. No score, model, weighting, or classification was implemented.

> This document is a factual description of the repository and the CFPB data as they
> exist today. Every number below was computed directly from the current CSV. Nothing
> here assigns severity, rank, or quality to any lender.

---

## Table of contents

- [A. Current Repo State](#a-current-repo-state)
- [B. CFPB Dataset Inventory](#b-cfpb-dataset-inventory)
- [C. Primary Dataset Profile](#c-primary-dataset-profile)
- [D. Product Composition](#d-product-composition)
- [E. Company Coverage](#e-company-coverage)
- [F. Consumer Issue Data](#f-consumer-issue-data)
- [G. Company Behavior Data](#g-company-behavior-data)
- [H. Geography](#h-geography)
- [I. Text / NLP Availability](#i-text--nlp-availability)
- [J. Available Denominators](#j-available-denominators)
- [K. Existing Teammate Work](#k-existing-teammate-work)
- [L. Candidate Signals](#l-candidate-signals)
- [M. Signals That Look Weak or Misleading](#m-signals-that-look-weak-or-misleading)
- [N. Major Methodological Risks](#n-major-methodological-risks)
- [O. Recommended Next Decision](#o-recommended-next-decision)
- [P. Useful Raw Tables](#p-useful-raw-tables)

---

# A. Current Repo State

**Branch `main`, HEAD `a95253b`, working tree clean, 1 commit ahead of `origin/main`. Nothing pushed.**

31 tracked files. **There is no analytics, scoring, feature-engineering, or lender-classification code anywhere in the current tree.**

| Area | State |
|---|---|
| `backend/app/main.py` | FastAPI. 4 routes: `/`, `/health`, `/lenders`, `/lenders/{id}`. CORS for `localhost:3000`. No analytics. |
| `backend/app/data.py` | **3 hardcoded fake lenders.** All `complaint_count=0`. `apr_range` values are invented strings (`"391% - 1,500%"`, `"150% - 300%"`, `"8% - 36%"`). Docstring: *"Replace this module with real lender data once the CFPB ingestion work starts."* |
| `backend/app/models.py` | Pydantic `Lender` with `id, name, states, product, apr_range, complaint_count`. |
| `notebooks/exploration.ipynb` | 4 cells: markdown header, `import pandas/numpy/sklearn` + version prints, markdown with a **commented-out** `read_csv`, and `RAW_DIR`/`PROCESSED_DIR` string assignment. Zero analysis. |
| `notebooks/amishi_cfpb_exploration.ipynb` | 5 cells: imports, `read_csv`, `Product.unique()`, `info()`, `Company.unique()`. Exploration only — no transformation, no grouping, no output files. |
| `data/raw/` | `paydayComplaints.csv` (gitignored) + `README.md` (provenance) + `.gitkeep` |
| `data/processed/` | `.gitkeep` only — **empty** |

**Recoverable prior work — `pipeline/` was deleted in `a95253b` but lives in `53f6208` ("Add CFPB complaint data pipeline", 1,345 lines, authored by Mihir Kale):**

| File | Lines | What it did |
|---|---|---|
| `pipeline/normalize.py` | 154 | Company-name cleaning; lifted `(F/K/A X)` into aliases; stripped entity suffixes and generic wrapper words; handled the literal `"None"` null |
| `pipeline/lenders.py` | 232 | Union-find lender roster; `MIN_LENDER_COMPLAINTS = 5`; merged corporate-history + operator-override aliases |
| `pipeline/metrics.py` | 301 | Per-lender DuckDB SQL: response rate, timely rate, median latency, trends |
| `pipeline/config.py` | 104 | `PERSONAL_LENDING_PRODUCTS` union across CFPB taxonomy changes; `ENTITY_SUFFIXES`; `GENERIC_WORDS`; bulk-download URL |
| `pipeline/ingest.py` / `run.py` | 238/124 | Download, unzip, DuckDB load, orchestration |
| `tests/test_normalize.py` | 183 | Unit tests for normalization |
| `lender_aliases.csv` | **1 line** | **Header only** (`source,target,reason`) — the operator override table was never populated |

This is real, tested, documented methodology — currently **not in the tree**.

---

# B. CFPB Dataset Inventory

**Exactly one dataset exists. There is no second file, no database, no derived output.**

| Path | Type | Size | Rows | Cols | State |
|---|---|---|---|---|---|
| `data/raw/paydayComplaints.csv` | CSV, header row, RFC4180-quoted | 10,575,153 B (10.1 MB) | 38,375 | 15 | **Raw CFPB export, unfiltered by this team.** Gitignored; untracked since `a95253b`; blob still in `bc64848`. |

`data/processed/` is empty. `data/out/` (10 derived CSVs from the old pipeline) was deleted. No Parquet, DuckDB, SQLite, JSON, or Excel file exists anywhere in the worktree or in git history.

**Relationship:** none — there is nothing to relate it to. The old pipeline's derived tables (`lender_roster.csv`, `lender_summary`, etc.) were computed from a **different, much larger source** (`complaints.csv`, 5.46 GB, the full national CCDB bulk file, since deleted), not from this 10 MB extract. **This CSV's relationship to that pipeline's inputs is undocumented and unverifiable.**

---

# C. Primary Dataset Profile

**38,375 rows × 15 columns. Zero duplicate rows. Zero duplicate Complaint IDs. `Complaint ID` is a unique `int64` (38,375/38,375).** Missingness is genuine null — there are **no literal `"None"` strings** anywhere (relevant, because the deleted `normalize.py` had to special-case them, so this extract is cleaner than the bulk file it was built for).

| # | Column | dtype | Missing | % | Unique |
|---|---|---|---|---|---|
| 0 | `Date received` | str | 0 | 0.0% | 38,339 |
| 1 | `Product` | str | 0 | 0.0% | **1** |
| 2 | `Sub-product` | str | 0 | 0.0% | 8 |
| 3 | `Issue` | str | 0 | 0.0% | 33 |
| 4 | `Sub-issue` | str | 34,104 | **88.9%** | 23 |
| 5 | `Company public response` | str | 30,825 | **80.3%** | 9 |
| 6 | `Company` | str | 0 | 0.0% | 1,162 |
| 7 | `State` | str | 77 | 0.20% | 59 |
| 8 | `ZIP code` | str | 17 | 0.04% | 9,204 |
| 9 | `Tags` | str | 31,236 | **81.4%** | 3 |
| 10 | `Submitted via` | str | 0 | 0.0% | 4 |
| 11 | `Date sent to company` | str | 0 | 0.0% | 38,228 |
| 12 | `Company response to consumer` | str | **0** | **0.0%** | 5 |
| 13 | `Timely response?` | str | **0** | **0.0%** | 2 |
| 14 | `Complaint ID` | int64 | 0 | 0.0% | 38,375 |

**Time coverage:** `2023-08-25T00:45:25Z` → `2026-09-25T17:44:12Z` (1,127 days). **No month with zero complaints.** Both endpoints are partial periods.

| Year | Complaints | Note |
|---|---|---|
| 2023 | 2,559 | partial — starts Aug 25 |
| 2024 | 9,036 | full |
| 2025 | 13,137 | full |
| 2026 | 13,643 | partial — ends Sep 25 |

Volume is **strongly growing**: 1,516/month in 2026 vs 924/month in 2025 (+64%). No anomalous spikes; steady ramp.

**Warning — `Date sent to company` is not a human response time.** Median latency is **20.0 minutes**; **80.5% of complaints were "sent to company" within 1 hour**, 86.9% within 1 day, and only 6.0% exceed 15 days. This is an automated routing timestamp. The deleted `metrics.py` computed a `median(date_diff(...))` latency metric that would have been measuring this artifact.

---

# D. Product Composition

**`Product` has exactly one distinct value — all 38,375 rows are `Payday loan, title loan, personal loan, or advance loan`.** It carries zero information and cannot be used as a filter. Confirmed still constant.

**`Sub-product` is the only usable product axis — 8 values:**

| Sub-product | Complaints | % | Companies | States |
|---|---|---|---|---|
| Installment loan | 21,835 | **56.90%** | 805 | 58 |
| Personal line of credit | 6,712 | 17.49% | 508 | 56 |
| **Payday loan** | **6,024** | **15.70%** | 483 | 55 |
| Title loan | 2,488 | 6.48% | 211 | 52 |
| Other advances of future income | 731 | 1.90% | 235 | 47 |
| Earned wage access | 396 | 1.03% | 93 | 46 |
| Pawn loan | 127 | 0.33% | 53 | 32 |
| Tax refund anticipation loan or check | 62 | 0.16% | 31 | 24 |

**Only 15.7% of this dataset is actual payday product.** 56.9% is installment lending, which is a structurally different credit product (amortizing, longer term, lower APR). The dataset is a poor proxy for "the payday lending market."

**Mix shifts materially over time** — the dataset is not a stationary sample:

| Sub-product | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|
| Installment loan | 48.69% | 53.13% | 54.71% | **63.04%** |
| Personal line of credit | 23.64% | 21.36% | 17.41% | **13.85%** |
| Payday loan | 16.06% | 15.01% | 17.33% | 14.51% |
| Title loan | 9.07% | 7.40% | 6.77% | **5.12%** |

---

# E. Company Coverage

**1,162 distinct company strings. Heavily long-tailed.**

| Percentile | Complaints/company |
|---|---|
| p10 | 1 |
| p25 | 1 |
| **p50 (median)** | **2** |
| p75 | 9 |
| p90 | 75.4 |
| p95 | 163.85 |
| p99 | 488.16 |
| max | 3,257 |
| **mean** | **33.02** |

Mean (33.0) is **16× the median (2.0)** — extreme skew.

| Threshold | Companies | % of companies | Complaints covered | % of rows |
|---|---|---|---|---|
| ≥ 5 | 417 | 35.9% | 37,101 | 96.7% |
| ≥ 10 | 285 | 24.5% | 36,241 | 94.4% |
| ≥ 20 | 216 | 18.6% | 35,296 | 92.0% |
| ≥ 30 | 176 | 15.1% | 34,342 | 89.5% |
| ≥ 50 | 140 | 12.0% | 32,920 | 85.8% |
| ≥ 100 | 89 | 7.7% | 29,096 | 75.8% |
| ≥ 250 | 31 | 2.7% | 19,529 | 50.9% |
| ≥ 500 | 12 | 1.0% | 13,121 | 34.2% |
| ≥ 1000 | 5 | 0.4% | 8,918 | 23.2% |

**434 companies (37.3%) have exactly one complaint.** 745 companies have <5, contributing only 1,274 rows (3.3%).

**Top 10 (24.1% of all rows):** Affirm Holdings 3,257 (8.49%) · OneMain Finance 2,281 (5.94%) · CCF Intermediate Holdings 1,149 (2.99%) · Paramount GR Holdings 1,132 (2.95%) · ENOVA INTERNATIONAL 1,099 (2.86%) · Klarna AB 805 (2.10%) · Truist 597 (1.56%) · Synchrony 595 (1.55%) · Upstart 578 (1.51%) · Upgrade 572 (1.49%). **Cumulative top 50 = 61.05%.**

**This is a BNPL/installment dataset, not a payday dataset.** Affirm and Klarna are buy-now-pay-later; the top of the distribution is banks and credit unions. Of the 140 companies with ≥50 complaints, all operate in **at least 3** sub-products (breadth distribution: 3→15, 4→40, 5→37, 6→35, 7→7, 8→6). No company is product-exclusive.

### Alias / fragmentation findings (identification only — nothing fixed)

**Actual fragmentation in this file is far milder than the deleted pipeline assumed:**

- **One** case-only duplicate: `FIRST TECHNOLOGY FEDERAL CREDIT UNION` (51) and `First Technology Federal Credit Union` (24) — same lender split across 2 rows, 75 total.
- **One** `F/K/A` marker: `Populus Financial Group, Inc. (F/K/A Ace Cash Express)` (98 rows). There is **no** separate `Ace Cash Express` row to merge with.
- **31** `D/B/A`/`DBA` names (e.g. `Ningo Lending LLC dba Spotloan` 266, `Uetsa Tsakits, Inc. d/b/a MaxLend` 99, `MoneySpot USA LLC DBA Sunshine Loans` 44). **None** has a matching standalone brand row.
- The families the deleted `normalize.py` was built for are **largely absent**: `ENOVA` appears as exactly one spelling (the `Elevate Financial` variant is not here); `CURO` only as `CURO Intermediate Holdings` (22); no `PAYDAY STAR`, `MONEY MART`, `ADVANCE AMERICA` (only `Advance America, Cash Advance Centers, Inc.` 177), `LENDUP`, `CHECK 'N GO`.

**Warning — naive string matching is actively dangerous here.** A shared-token heuristic produced these false-positive "alias" pairs: `Affirm Holdings, Inc` ~ `Upstart Holdings, Inc.` (shared `HOLDINGS, INC`); `TRUIST FINANCIAL CORPORATION` ~ `FIFTH THIRD FINANCIAL CORPORATION`; `NAVY FEDERAL CREDIT UNION` ~ `PENTAGON FEDERAL CREDIT UNION`; `Solar Mosaic LLC` ~ `SOLAR SERVICING HOLDINGS LLC`. A substring search for `rise` matched `Enterprise` and `Sunrise`. The deleted pipeline's documented conservatism was justified.

---

# F. Consumer Issue Data

**`Issue`: 33 values, 0% missing.** Complete distribution:

| Issue | Count | % | Companies | Sub-issues present |
|---|---|---|---|---|
| Charged fees or interest you didn't expect | 9,225 | 24.04% | 547 | 0 |
| Problem when making payments | 5,349 | 13.94% | 422 | 0 |
| Struggling to pay your loan | 4,145 | 10.80% | 467 | 0 |
| Getting the loan | 3,401 | 8.86% | 359 | 0 |
| Problem with additional add-on products or services | 2,967 | 7.73% | 289 | 0 |
| Problem with the payoff process at the end of the loan | 2,887 | 7.52% | 395 | 0 |
| Incorrect information on your report | 2,596 | 6.76% | 326 | 2,596 |
| Getting a line of credit | 1,258 | 3.28% | 237 | 0 |
| Problem with a company's investigation into an existing problem | 905 | 2.36% | 183 | 905 |
| Received a loan you didn't apply for | 682 | 1.78% | 203 | 0 |
| Can't stop withdrawals from your bank account | 619 | 1.61% | 116 | 0 |
| Can't contact lender or servicer | 542 | 1.41% | 200 | 0 |
| Improper use of your report | 540 | 1.41% | 158 | 540 |
| Vehicle was repossessed or sold the vehicle | 376 | 0.98% | 58 | 0 |
| Issues with repayment | 374 | 0.97% | 137 | 0 |
| Loan payment wasn't credited to your account | 372 | 0.97% | 137 | 0 |
| Money was taken from your bank account on the wrong day or for the wrong amount | 345 | 0.90% | 95 | 0 |
| Was approved for a loan, but didn't receive the money | 258 | 0.67% | 109 | 0 |
| Confusing or misleading advertising or marketing | 215 | 0.56% | 111 | 0 |
| Confusing or missing disclosures | 210 | 0.55% | 109 | 0 |
| Problems receiving the advance | 198 | 0.52% | 83 | 0 |
| Unexpected fees | 173 | 0.45% | 86 | 0 |
| Credit monitoring or identity theft protection services | 170 | 0.44% | 88 | 170 |
| Problem with cash advance | 142 | 0.37% | 72 | 0 |
| Credit limit changed | 94 | 0.24% | 44 | 0 |
| Vehicle was damaged or destroyed the vehicle | 94 | 0.24% | 23 | 0 |
| Problem with fraud alerts or security freezes | 74 | 0.19% | 44 | 0 |
| Was approved for a loan, but didn't receive money | 61 | 0.16% | 17 | 0 |
| Unable to get your credit report or credit score | 60 | 0.16% | 42 | 60 |
| Property was sold | 18 | 0.05% | 6 | 0 |
| Lost or stolen refund | 14 | 0.04% | 11 | 0 |
| Property was damaged or destroyed property | 6 | 0.02% | 4 | 0 |
| Problem with customer service | 5 | 0.01% | 4 | 0 |

**Warning — `Sub-issue` is nearly worthless for this workstream.** It is 88.9% null, and it is populated for **only 5 of 33 Issues — all credit-reporting related** (2,596 + 905 + 540 + 170 + 60 = 4,271). Every one of the 23 `Sub-issue` values maps to **exactly one** parent Issue. It adds granularity precisely where it is least relevant (credit-reporting disputes) and **zero** granularity for the top 6 Issues, which are 73% of rows.

### Consumer-harm concepts the actual categories support

Verified against real values, no inference:

| Concept | Supported? | Evidence |
|---|---|---|
| Unexpected fees | **Yes** | `Charged fees or interest you didn't expect` (9,225), `Unexpected fees` (173), `Problem with additional add-on products or services` (2,967) |
| Payment problems | **Yes** | `Problem when making payments` (5,349), `Issues with repayment` (374), `Money was taken... on the wrong day or for the wrong amount` (345), `Loan payment wasn't credited` (372), `Problem with the payoff process` (2,887) |
| Unauthorized withdrawals | **Yes** | `Can't stop withdrawals from your bank account` (619) |
| Misleading information | **Yes** | `Confusing or misleading advertising or marketing` (215), `Confusing or missing disclosures` (210), `Was approved for a loan, but didn't receive the money` (258) |
| Inability to repay | **Yes** | `Struggling to pay your loan` (4,145) |
| Servicing problems | **Yes** | `Can't contact lender or servicer` (542), `Problem with customer service` (5), `Problem with a company's investigation into an existing problem` (905) |
| Collections | **Partial/ambiguous** | No dedicated collections category. Closest: `Vehicle was repossessed or sold` (376), `Property was sold` (18), `Received a loan you didn't apply for` (682) |
| Fraud | **Weak** | No fraud category. Closest: `Information belongs to someone else` (713, a *Sub-issue*), `Problem with fraud alerts or security freezes` (74, about the consumer's own freeze) |
| Identity theft | **Weak** | `Credit monitoring or identity theft protection services` (170) is about *selling* ID-theft services, not identity theft victimization |

---

# G. Company Behavior Data

### `Company response to consumer` — 0% missing, 5 values

| Value | Count | % | Companies |
|---|---|---|---|
| Closed with explanation | 34,598 | 90.16% | 993 |
| Closed with non-monetary relief | 1,423 | 3.71% | 147 |
| Closed with monetary relief | 1,261 | 3.29% | 160 |
| In progress | 558 | 1.45% | 91 |
| Untimely response | 535 | 1.39% | 176 |

**Discrimination: moderate at the top, wide at the tail.** Across the 140 companies with ≥50 complaints, monetary-relief rate ranges **0% to 42.59%**, median 0.73%. **63 of 140 companies have exactly 0% monetary relief.** Top: Atlanticus Services 42.59% (n=54), Bread Financial 29.52% (n=227), American First Finance 24.32% (n=148). Bottom (all exactly 0%): Credit Fresh Holdings (291), Dave Operating (320), Regional Management (210), Post Lake Lending (98), Prosper Marketplace (190), Crow Creek Sioux Tribe (159).

**Warning — `In progress` (558 rows) is entirely 2026, all dated 2026-03-18 or later.** This is pure right-censoring: recent complaints have not been resolved yet. Any "resolution rate" computed over the full window is biased downward, and the bias is concentrated in 2026.

### `Timely response?` — 0% missing, Yes/No

**Overall: Yes 36,643 (95.49%), No 1,732 (4.51%).**

Crosstab reveals `Untimely response` (535) implies `Timely = No` always. So `Timely = No` (1,732) = 535 explicit "Untimely response" + **1,157 complaints the company answered late but still marked "Closed with explanation."**

**Warning — this field is heavily ceiling-compressed and weak for most lenders.** Across the 140 companies with ≥50 complaints:

| Stat | Value |
|---|---|
| min | 0.00% |
| p25 | 97.22% |
| **median** | **99.80%** |
| p75 | 100.00% |
| max | 100.00% |
| Companies at exactly 100% | **66 of 140 (47%)** |
| Companies at ≤50% | 2 |

So: 15 companies are at a perfect 100% (OneMain 2,281; Navy Federal 396; Citibank 204; PayPal 234; Capital One 102; Equifax 144…), and the distribution is crushed against 100%. **It does not discriminate among the majority of lenders.** It does carry real signal in the extreme tail: `Mobiloans, LLC` **0.00%** timely (n=91), `Giggle Finance Inc.` 10.00% (n=50), `Westcreek Financial` 52.02% (n=173), `Crow Creek Sioux Tribe` 54.09% (n=159), `TMX Finance LLC` 54.17% (n=96). Treat it as a *flag for a small set*, not a continuous score input.

### `Company public response` — 80.33% missing (30,825), 9 values

| Value | Count | % | Companies |
|---|---|---|---|
| *(null)* | 30,825 | 80.33% | 981 |
| Responded but chooses not to provide a public response | 5,067 | 13.20% | 164 |
| Believes it acted appropriately as authorized by contract or law | 1,672 | 4.36% | 166 |
| Complaint gave opportunity to answer consumer's questions | 304 | 0.79% | 41 |
| Disputes the facts presented | 186 | 0.48% | 68 |
| Result of a misunderstanding | 94 | 0.24% | 61 |
| Result of an isolated error | 86 | 0.22% | 25 |
| Caused principally by third party | 81 | 0.21% | 35 |
| Opportunity for improvement | 42 | 0.11% | 26 |
| Can't verify or dispute the facts | 18 | 0.05% | 13 |

**Discrimination: low.** Only 164 companies have any public response at all, and the 4 rarest categories have ≤41 companies. Meaningful per-lender rates would rest on single-digit counts.

### `Submitted via` — 0% missing, 4 values

Web 35,068 (91.38%, 1,096 companies) · Phone 1,974 (5.14%, 327) · Referral 939 (2.45%, 208) · Postal mail 394 (1.03%, 145).

### `Tags` — 81.4% missing, 3 values

*(null)* 31,236 (81.40%) · `Servicemember` 4,177 (10.88%, 436 companies) · `Older American` 2,253 (5.87%, 342) · `Older American, Servicemember` 709 (1.85%, 166).

---

# H. Geography

**`State`: 77 missing (0.20%), 59 distinct values.**

**Warning — 28 rows carry non-state codes:** `AE` 14, `AP` 6, `UNITED STATES MINOR OUTLYING ISLANDS` 3, `GU` 2, `MP` 1, `AS` 1, `VI` 1. `PR` (74) is a US territory but not a state. All are military/diplomatic/postal codes, not data-entry errors — but they will silently become "regions" in any groupby.

Top: TX 4,513 (11.76%, 426 companies) · CA 4,220 (11.00%) · FL 3,920 (10.21%) · GA 2,132 (5.56%) · NY 1,544 (4.02%) · OH 1,304 (3.40%) · **NC 1,244 (3.24%, 237 companies)** · IL 1,193 (3.11%) · PA 1,149 (2.99%) · **SC 902 (2.35%, 186 companies)**.

**NC + SC = 2,146 rows (5.59%), 302 companies.** Only **23 companies have ≥20 Carolina complaints; only 5 have ≥50.** NC/SC sub-product mix skews even further to installment (59.09%) than the national sample (56.90%), with payday at 11.88% vs 15.70% nationally.

**Coverage does differ substantially by lender — this is measurable.** 34 companies appear in exactly one state (21 NC-only, 13 SC-only). `STATE EMPLOYEES' CREDIT UNION` has 35 complaints, **100% in NC/SC**, single state. `Regional Management Corporation` has 21.0% of its volume in NC/SC vs 5–8% for the large nationals. Conversely OneMain (51 states), MoneyLion (48), Upstart (47), Truist (48) are national.

**Warning — `ZIP code` is unusable for precise geography.** 9,204 distinct, 17 missing, all non-null exactly 5 characters — but **6,357 rows (16.6%) are X-masked**: 403 are fully `XXXXX`, 5,954 partial like `903XX`/`152XX`. **Zero rows have a clean 5-digit ZIP.** Masking is uneven across states: **SC 20.7%**, TX 13.4%, NC 12.9%, FL 12.1%, CA 8.7%. Any ZIP- or county-level analysis would be both incomplete and biased against small-population states — South Carolina, among the least populous states, is masked most.

---

# I. Text / NLP Availability

**We do not possess complaint-level natural-language text. NLP is not currently possible.**

Definitive evidence:

1. The dataset has **15 columns and none is `Consumer complaint narrative`** — the field the real CFPB schema carries.
2. The **longest string value anywhere in the entire dataset is 119 characters**, and it is a category label: `"Company believes complaint caused principally by actions of third party outside the control or direction of the company"`.
3. Max length per column: `Product` 55, `Sub-issue` 85, `Issue` 79, `Company` 61, `Company public response` 119, `ZIP code` 5, `Timely response?` 3. All categorical or codes.
4. Repo-wide search of tracked files found no narrative/complaint-text field, no text corpus, no Reddit scrape. `.env.example` reserves `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` but **no Reddit code, data, or integration exists**.

Sentiment/NLP work would require obtaining a source that carries narratives (the CFPB bulk file does, or Reddit) — that is a data-acquisition decision, not something the current repo supports.

---

# J. Available Denominators

> **We currently do not have an exposure denominator for complaint counts.**

**Nothing in the repo or the dataset provides customer counts, loan originations, loan volume, transaction volume, market share, revenue, assets, or borrower counts.** Verified by inspecting all 15 columns and grepping every tracked file plus the deleted pipeline in history.

Every column is one of: a complaint attribute, a date, a categorical, a geography code, or the complaint's own unique ID. `Complaint ID` is 38,375/38,375 unique, so it carries no aggregation information.

The only exposure-adjacent strings in the repo are the **invented** `apr_range` values on the 3 fake lenders in `backend/app/data.py` (`"391% - 1,500%"`, `"150% - 300%"`, `"8% - 36%"`), all with `complaint_count=0`. These are placeholders with no data behind them.

**Consequence: every count-based quantity in this dataset is a raw count, not a rate.** Affirm's 3,257 complaints and `Regional Management Corporation`'s 210 are not comparable — nothing tells us their relative size. Complaint *rates* are not computable without an external denominator source (FDIC call reports, CFPB lending volume, or lender-reported figures), none of which is present.

---

# K. Existing Teammate Work

### Actual implementation: **none**

Nothing in the current tree filters, classifies, groups, aggregates, scores, or exports lender data. The backend serves 3 hardcoded fakes. The notebooks are 5-cell and 4-cell scratchpads whose only executed outputs are `Product.unique()` and `Company.unique()`.

Amishi's commit `bc64848` ("j") contributed **only the dataset** — the notebook in it was 3 cells of exploration and could not run (it imported an uninstalled `matplotlib`, called `complaints.info` without parentheses, and read the CSV by a path that broke once moved). It contained **no analysis, no findings, no assumptions.**

### Exploratory / scratch: two notebooks, zero results

Neither notebook writes a file, defines a function, or produces a table worth preserving. There are no plots or results to keep.

### Deleted-but-recoverable methodology — the most valuable prior work

`53f6208` contains a **1,345-line, unit-tested** pipeline whose design notes are directly relevant to this workstream and are **not in the current tree**:

- `config.py` documents that **the CFPB renamed the personal-lending categories mid-stream**, so a single `product='Payday loan'` filter captures only the 2013–2017 slice. It defines `PERSONAL_LENDING_PRODUCTS` as a **union**: `["Payday loan", "Payday loan, title loan, or personal loan", "Payday loan, title loan, personal loan, or advance loan", "Consumer Loan"]`. It states, verified against the live API on 2026-09-26, that `"Personal loan"` **returns 0 rows and has never existed as a product.** *This dataset contains only the last of those four values.*
- `lenders.py` sets `MIN_LENDER_COMPLAINTS = 5` and documents why: *"Guards against one-off complainants and against mis-bucketed rows."*
- `metrics.py` documents the response-rate semantics: null response = *unanswered*, not *untimely*, so response rate is over all complaints and timely rate over responded only. **This assumption does not hold in the current file** — `Company response to consumer` and `Timely response?` are both 0% missing here and there is no `Unanswered` category. The dataset changed under that code.
- `normalize.py` documents the deliberate conservatism: *"Under-normalizing leaves one lender split across two rows; over-normalizing silently merges two real lenders... mis-attributing complaints is worse than leaving a lender split across two keys."*

**Recommendation: restore `pipeline/` from `53f6208` before writing new code** — it is a tested foundation, and its caveats are already correct. But its `PERSONAL_LENDING_PRODUCTS` and response-nullability assumptions must be re-validated against this extract.

---

# L. Candidate Signals

Observed only. **No weights assigned.**

| # | Signal | Source | Measures | Why useful | Limitation |
|---|---|---|---|---|---|
| 1 | Monetary-relief rate | `Company response to consumer` | Share of complaints closed with money returned | Outcome-closest thing to "consumer got made whole"; 0–42.6% spread across 140 companies | Resolution is voluntary and self-reported; 63/140 large companies at exactly 0%; no dollar amounts; heavily confounded by loan size |
| 2 | Non-monetary-relief rate | `Company response to consumer` | Closed with non-cash adjustment | Second-tier remedy, 147 companies | Overlaps #1; tiny counts for most |
| 3 | Untimely rate | `Timely response?`, `Company response` | Share not answered on time | Direct service-quality proxy; 0–54% spread in the tail | **Ceiling-compressed**: median 99.8%, 66/140 at exactly 100%. Only informative for a small tail |
| 4 | Untimely-response count | `Company response to consumer` = `Untimely response` | Explicitly flagged late responses, 535 rows / 176 companies | Unambiguous, not derived | Sparse per lender; overlaps #3 |
| 5 | Dispute rate | `Company public response` | Share where company disputes facts (186 rows) / "can't verify" (18) | Signals adversarial posture | 80.3% null; only 68 companies dispute; sub-single-digit counts for most |
| 6 | Issue-mix vector (33-dim) | `Issue` | Distribution of problem types per lender | Only field with genuine, well-populated, lender-varying semantic content | Requires an external taxonomy decision; "Struggling to pay" may reflect borrower economics not lender conduct |
| 7 | Sub-product specialization | `Sub-product` | Which of 8 products a lender operates in | Installment-only vs multi-product may differ structurally | All 140 large companies span ≥3 products; no clean segmentation exists |
| 8 | Unresolved rate | `Company response to consumer` = `In progress` | Complaints not yet closed | Open-problem indicator | **Right-censored** — all 558 rows are 2026-03-18 or later. Not a behavioral signal |
| 9 | Single-state operation | `State` | Count of states a lender appears in | 34 lenders are single-state — regional operators with plausibly higher local accountability | Only 34 companies; absent for most |
| 10 | Servicemember / Older American tagging | `Tags` | Protected-population complaint share | 7,139 tagged rows; potentially high-harm population | 81.4% null; tag application is inconsistent across filers; 2 values only |
| 11 | Fee/interest complaint share | `Issue` ∈ {Charged fees…, Unexpected fees, add-on products} | 12,365 rows (32.2%) | Highest-volume, most consumer-salient harm class | Complaint ≠ proven violation; overlaps #1 |
| 12 | Phone-channel share | `Submitted via` = Phone | 1,974 rows / 327 companies | Proxy for service-channel friction | Channel choice is consumer-side, not lender-side |
| 13 | Cross-product consistency | `Sub-product` × `Issue` | Whether a lender's complaint profile is uniform across products | Would separate product-specific from firm-wide problems | Very few companies have enough volume in enough products |

**Not yet usable as signals:** `Product` (constant), `Sub-issue` (88.9% null, credit-reporting only), `ZIP code` (16.6% X-masked), `Date sent to company` (routing artifact), `Complaint ID` (unique key), `Date received` (exposure proxy only).

---

# M. Signals That Look Weak or Misleading

| Field | Why to avoid |
|---|---|
| **`Product`** | Exactly one value. Any "product" feature built on it is constant and will silently produce zero-variance output. |
| **`Sub-issue`** | 88.9% null and confined to 5 credit-reporting Issues. Using it means ~89% of rows are imputed and the 6 highest-volume Issues get no detail. Worse than not using it — it biases attention toward credit bureaus. |
| **`Date sent to company` / latency** | Median 20 minutes, 80.5% within 1 hour. This is automated routing, not responsiveness. The deleted `metrics.py` computed a median-latency metric on exactly this artifact. |
| **Raw complaint count as "badness"** | Mean 33.0 vs median 2.0 per company. Pure size proxy. OneMain (2,281) and `Regional Management` (210) differ by ~11× in complaints and nothing tells us their relative exposure. **This is the single most dangerous misuse available in this dataset.** |
| **`Timely response?` as a continuous score** | Median 99.8%, 47% of large companies at exactly 100%. Averaging it produces a distribution crushed at the ceiling; it ranks almost nobody. |
| **`ZIP code`** | 16.6% X-masked, **zero** clean values, and masking is anti-correlated with population size (SC worst at 20.7%). County/ZIP features would be both broken and biased. |
| **`Tags`** | 81.4% null, 3 values, and filers apply tags inconsistently — absence is not evidence of no protected population served. |
| **`Company public response`** | 80.3% null; the interpretable categories have 13–68 companies. Per-lender rates would rest on single-digit numerators. |
| **Naive company-name aliasing** | Reproducibly produced false merges (`Affirm`~`Upstart`, `Navy Federal`~`Pentagon Federal`, `Truist`~`Fifth Third`). Substring search for `rise` matched `Enterprise`. |
| **`In progress` as a complaint-quality signal** | 100% of the 558 rows fall in the final 6 months. Pure censoring. |
| **The 3 fake lenders' `apr_range`** | Invented strings with `complaint_count=0`. If they reach a scoring model they will corrupt it. |

---

# N. Major Methodological Risks

1. **No denominator — the dominant risk.** Nothing permits a rate. Every count conflates lender size with lender quality. Any "X complaints" or "complaints per borrower" framing is invalid today. This constrains the entire design, not just one feature.

2. **Product-type mixing.** 56.9% installment, 15.7% payday, plus title/payback/EWA/pawn. These have different economics, different APR regimes, and different complaint propensities. A single score across them compares unlike things. This dataset is mostly *not* the product FinePrint is named for.

3. **Temporal non-stationarity.** Complaint volume grew 64% month-over-month (924→1,516). Sub-product mix shifted hard (installment 48.7%→63.0%, personal LOC 23.6%→13.9%, title 9.1%→5.1%). `Getting a line of credit` fell 6.2%→2.0%. Complaint-mix percentages computed over the full window are averages over a moving composition.

4. **Right-censoring at the end.** All 558 `In progress` rows postdate 2026-03-18. Any resolution/relief rate over the full window is biased low, and the bias concentrates in the most recent period — which is also the largest period.

5. **Extreme lender sparsity.** Median 2 complaints/company; 434 companies with exactly 1; 37.3% of companies are singletons. Per-lender rate estimates for anything under ~30 complaints are statistically meaningless. Only 89 companies clear 100 complaints; only 31 clear 250.

6. **Selection bias — who complains.** CFPB complaints are self-selected, self-reported, and represent a fraction of actual problems. No information exists on a lender's total customer base, so we cannot distinguish "this lender harms many people" from "this lender has many customers and a similar rate."

7. **Complaint ≠ verified outcome.** CFPB records the *allegation*. `Company response` and `Company public response` are the *lender's* account of the same event, and are self-reported and optional (80.3% null on public response). Monetary relief is not an admission of fault.

8. **Headline dominance by non-payday firms.** Affirm (8.49%), OneMain (5.94%), Klarna (2.10%) are BNPL/installment/bank. A frequency-driven model will rank BNPL and credit unions at the top and may never surface the installment/payday lenders a consumer is actually deciding between.

9. **Geographic bias in the record itself.** X-masking is worst in small-population states (SC 20.7% vs CA 8.7%), and `AE`/`AP`/`GU`/`MP`/`AS`/`VI`/minor-outlying-islands (28 rows) are not states. Any regional feature inherits this.

10. **Undocumented provenance.** The export filter and retrieval date are recorded as *Unknown / needs documentation*. We do not know what upstream filter produced this file, so we cannot rule out that the selection itself biases toward certain lenders or issue types.

11. **Company identity is string-based.** One confirmed split (`First Technology Federal Credit Union`, 51+24). No lender registry, no entity resolution, no parent-subsidiary rollup. A lender operating under several names scores as several lenders.

12. **The prior pipeline was built for a different input.** `PERSONAL_LENDING_PRODUCTS` assumes a 4-value union; this file has 1. `metrics.py` assumes null response = unanswered; here response is 0% null. Reusing that code without re-validating will produce silently wrong results.

---

# O. Recommended Next Decision

**These are decisions for the team. None have been made, and no implementation has been started.**

1. **What is the unit of evaluation?** Options: (a) all 1,162 company strings; (b) the 140 with ≥50 complaints; (c) the 31 with ≥250; (d) the 483 appearing in `Sub-product = Payday loan`. This choice sets the entire sample size and interacts directly with risk #5.

2. **How will the missing denominator be handled?** Either (a) accept that only *complaint mix and response behavior* can be ranked, never rates, and scope claims accordingly; (b) commission an external denominator (FDIC/CFPB volume data) — a new data-acquisition workstream; or (c) use complaint counts only as *filters/thresholds*, never as the score. This is the single largest determinant of what the score is allowed to claim.

3. **What is the product scope?** Score across all 8 sub-products (dominated by installment), restrict to `Sub-product = Payday loan` (6,024 rows, 483 companies, median 2 — very sparse), or score per sub-product with separate models (most companies lack volume for this).

4. **Is company identity string-based, or is a lender registry built?** Given the confirmed `First Technology` split and 31 DBA names, and given that one typo creates a phantom new lender, decide whether to restore `pipeline/normalize.py` or accept raw strings.

5. **What claim will the label make?** "This lender has a high rate of unresolved complaints" (needs a denominator) vs "this lender's complaints most often involve unexpected fees and are rarely resolved with relief" (works on what we have, but is a mix-and-process description, not a rate).

---

# P. Useful Raw Tables

## P.1 Sample-size ladder (the core constraint)

| Threshold | Companies | % companies | % of all complaints |
|---|---|---|---|
| any | 1,162 | 100% | 100% |
| ≥5 | 417 | 35.9% | 96.7% |
| ≥10 | 285 | 24.5% | 94.4% |
| ≥20 | 216 | 18.6% | 92.0% |
| ≥30 | 176 | 15.1% | 89.5% |
| ≥50 | 140 | 12.0% | 85.8% |
| ≥100 | 89 | 7.7% | 75.8% |
| ≥250 | 31 | 2.7% | 50.9% |
| ≥500 | 12 | 1.0% | 34.2% |
| ≥1000 | 5 | 0.4% | 23.2% |

## P.2 Cross-tab: response behavior × timeliness

| Company response | Timely=No | Timely=Yes | Total |
|---|---|---|---|
| Closed with explanation | 1,157 | 33,441 | 34,598 |
| Closed with monetary relief | 28 | 1,233 | 1,261 |
| Closed with non-monetary relief | 12 | 1,411 | 1,423 |
| In progress | 0 | 558 | 558 |
| Untimely response | 535 | 0 | 535 |
| **Total** | **1,732** | **36,643** | **38,375** |

## P.3 Payday-only slice (6,024 rows, 483 companies, median 2 / mean 12.5)

| Issue | Count | % of payday | Companies |
|---|---|---|---|
| Charged fees or interest you didn't expect | 1,783 | 29.60% | 220 |
| Struggling to pay your loan | 1,066 | 17.70% | 225 |
| Can't stop withdrawals from your bank account | 605 | 10.04% | 112 |
| Received a loan you didn't apply for | 586 | 9.73% | 182 |
| Can't contact lender or servicer | 391 | 6.49% | 150 |
| Problem with the payoff process | 373 | 6.19% | 132 |
| Money taken on wrong day/amount | 316 | 5.25% | 87 |
| Loan payment not credited | 252 | 4.18% | 111 |
| Approved but didn't receive money | 248 | 4.12% | 105 |

Top payday lenders: CCF Intermediate 335 (5.56%) · Dave Operating 251 (4.17%) · ENOVA 228 (3.78%) · WLCC 198 (3.29%) · Rosebud Economic 195 (3.24%) · Uprova Credit 175 (2.91%) · Wolf River 161 (2.67%) · Ningo/Spotloan 149 (2.47%) · MoneyLion 145 (2.41%) · Opportunity Financial 133 (2.21%). Only **70** payday companies reach ≥20 complaints.

## P.4 Behavior spread, 140 companies with ≥50 complaints

| Metric | min | p25 | median | p75 | max |
|---|---|---|---|---|---|
| Timely-response % | 0.00 | 97.22 | **99.80** | 100.00 | 100.00 |
| Monetary-relief % | 0.00 | 0.00 | **0.73** | — | 42.59 |

66/140 at exactly 100% timely · 63/140 at exactly 0% monetary relief · 2/140 at ≤50% timely.

## P.5 Carolinas (NC + SC = 2,146 rows, 5.59%, 302 companies)

| Company | Carolina complaints | % of Carolina | Total all states | Carolina share | States |
|---|---|---|---|---|---|
| Affirm Holdings, Inc | 166 | 7.74% | 3,257 | 5.1% | 52 |
| OneMain Finance Corporation | 161 | 7.50% | 2,281 | 7.1% | 51 |
| Paramount GR Holdings, LLC | 63 | 2.94% | 1,132 | 5.6% | 43 |
| ENOVA INTERNATIONAL, INC. | 57 | 2.66% | 1,099 | 5.2% | 44 |
| CCF Intermediate Holdings LLC | 51 | 2.38% | 1,149 | 4.4% | 39 |
| Regional Management Corporation | 44 | 2.05% | 210 | **21.0%** | 20 |
| Klarna AB | 43 | 2.00% | 805 | 5.3% | 44 |
| Upstart Holdings, Inc. | 39 | 1.82% | 578 | 6.7% | 47 |
| TRUIST FINANCIAL CORPORATION | 38 | 1.77% | 597 | 6.4% | 48 |
| STATE EMPLOYEES' CREDIT UNION | 35 | 1.63% | 35 | **100.0%** | 1 |

NC 1,244 (237 companies) · SC 902 (186 companies). Only 23 companies ≥20 Carolina complaints, 5 ≥50. 34 companies are single-state (21 NC-only, 13 SC-only).

## P.6 Data-quality defect counts

| Defect | Count | % |
|---|---|---|
| `Product` constant → zero information | 38,375 | 100% |
| `Sub-issue` null | 34,104 | 88.9% |
| `Tags` null | 31,236 | 81.4% |
| `Company public response` null | 30,825 | 80.3% |
| `ZIP code` X-masked | 6,357 | 16.6% |
| `State` non-state codes | 28 | 0.07% |
| `State` null | 77 | 0.20% |
| `ZIP code` null | 17 | 0.04% |
| Duplicate rows / duplicate Complaint IDs | **0** | 0% |
| `In progress` (right-censored, all post-2026-03-18) | 558 | 1.45% |
| Companies with exactly 1 complaint | 434 companies | 37.3% |

---

## Summary judgement

The data is clean but not informative by itself. Zero duplicates, zero ID collisions, no null-key rows, full 33-month coverage — and simultaneously no denominator, no narrative, constant `Product`, a `Sub-issue` field that is 89% empty and topically misplaced, ZIPs 100% masked, and a lender distribution where the median company has 2 complaints.

The binding constraints on any scoring methodology are the **missing denominator** (risk #1) and the **product mismatch** (only 15.7% payday) — not data hygiene.
