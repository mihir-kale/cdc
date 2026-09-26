# Raw data

Source datasets, exactly as downloaded. **Contents are git-ignored** — they are
too large to version. Keep a record of provenance here instead, and commit that
record rather than the data.

## paydayComplaints.csv

Consumer complaints exported from the
[CFPB Consumer Complaint Database](https://www.consumerfinance.gov/data-research/consumer-complaints/).

### Known properties

Measured directly from the file on 2026-09-26:

| Property     | Value                                             |
| ------------ | ------------------------------------------------- |
| Rows         | 38,375                                            |
| Columns      | 15                                                |
| Date range   | 2023-08-25 through 2026-09-25 (`Date received`)   |
| Unique companies | 1,162                                         |
| File size    | 10,575,153 bytes (10.5 MB)                        |

Columns: `Date received`, `Product`, `Sub-product`, `Issue`, `Sub-issue`,
`Company public response`, `Company`, `State`, `ZIP code`, `Tags`,
`Submitted via`, `Date sent to company`, `Company response to consumer`,
`Timely response?`, `Complaint ID`.

### Caveats

- **`Product` is constant.** Every row is
  `Payday loan, title loan, personal loan, or advance loan`. It carries no
  information and cannot be used to filter. Use `Sub-product` instead.
- **`State` is not clean.** It contains non-state codes — `AE`, `AP`,
  `GU`, `MP`, `AS`, `VI`, and `UNITED STATES MINOR OUTLYING ISLANTS` — plus 77
  null values, across 64 distinct values.
- **Sparse columns.** `Sub-issue` is 89% null, `Tags` 81%, and
  `Company public response` 80%.
- **Predominantly BNPL/installment, not payday.** The most frequent companies
  are Affirm (3,257), OneMain Finance (2,281), CCF Intermediate Holdings (1,149),
  Paramount GR Holdings (1,132), ENOVA International (1,099), and Klarna (805).

### Provenance gaps

- Original export/filter methodology: **Unknown / needs documentation**
- Retrieval date: **Unknown / needs documentation**
- Source URL or API query used: **Unknown / needs documentation**

The file was contributed to commit `bc64848` without a documented derivation.
The three items above should be filled in by whoever produced the extract.

### Recovering the file

This dataset is intentionally not in git, so a fresh clone will not have it. It
is recoverable from commit `bc64848`:

```bash
git show bc64848:paydayComplaints.csv > data/raw/paydayComplaints.csv
```

The blob remains in history because the history is not being rewritten. Do not
commit the recovered copy.
