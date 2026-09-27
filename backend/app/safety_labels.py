"""Build the FinePrint Payday Loan Safety Label dataset.

This module is the production home of the score that was selected and validated
in ``notebooks/cfpb_dimension_scoring.ipynb``. It is deliberately small: it
reproduces one formula and nothing else. All modelling choices -- the empirical
Bayes priors, the peer reference, the choice of Method C over the percentile and
robust-z alternatives -- were made and verified in the notebooks and are not
re-derived here.

Method C, for lender ``i`` and dimension ``c``::

    Score_ic = 100 * BetaCDF(theta_peer_c | x_ic + alpha_c, n_i - x_ic + beta_c)

``theta_peer_c`` is the median of the fitted Beta population for that dimension,
which is the peer reference rate. Because the reference comes from the fitted
model rather than from the observed sample, the score does not move when the set
of lenders changes; that invariance was one of the reasons C was selected.

Run it to regenerate the application artifact::

    python -m app.safety_labels

Input : data/processed/payday_shrunk_features.csv (git-ignored, 482 lenders)
Output: app/generated/lender_safety_labels.json (small, committed, served)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import beta as beta_dist

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

FEATURES_CSV = REPO_ROOT / "data" / "processed" / "payday_shrunk_features.csv"
OUTPUT_JSON = Path(__file__).resolve().parent / "generated" / "lender_safety_labels.json"

# The five complaint dimensions, keyed by the column suffix used in the
# processed feature file.
DIMENSIONS: dict[str, str] = {
    "withdrawal": "withdrawal_and_payment_control",
    "fees": "fees_and_costs",
    "unauthorized": "unauthorized_or_unrequested_loan",
    "credit_rep": "credit_reporting",
    "servicing": "servicing_and_payment_handling",
}

# Consumer-facing names. Kept next to the methodology so the label wording and
# the score definition cannot drift apart.
DIMENSION_LABELS: dict[str, str] = {
    "withdrawal": "Withdrawal & Payment Control",
    "fees": "Fees & Costs",
    "unauthorized": "Unauthorized / Unrequested Loans",
    "credit_rep": "Credit Reporting",
    "servicing": "Servicing & Payment Handling",
}

# Short consumer-readable explanation of each dimension, derived from the CFPB
# issue labels assigned to it in data/processed/issue_taxonomy.csv.
DIMENSION_SUMMARIES: dict[str, str] = {
    "withdrawal": (
        "Complaints about difficulty stopping withdrawals from a bank account, "
        "or money taken on an unexpected date or for an unexpected amount."
    ),
    "fees": (
        "Complaints about fees or interest the consumer reported they did not "
        "expect, including charges for add-on products or services."
    ),
    "unauthorized": (
        "Complaints in which the consumer reported receiving a loan they did "
        "not apply for."
    ),
    "credit_rep": (
        "Complaints about credit-report information, its accuracy, or disputes "
        "involving the lender. Responsibility may lie with the furnisher, the "
        "credit-reporting agency, or the dispute process, so a complaint here "
        "does not by itself indicate lender misconduct."
    ),
    "servicing": (
        "Complaints about payment processing, account servicing, payoff, and "
        "getting in touch with the lender or its servicer."
    ),
}

# Evidence bands. These describe how much complaint data supports the scores.
# They are explicitly NOT a judgement of the lender's quality.
EVIDENCE_BANDS: list[tuple[int, int, str]] = [
    (50, 10**9, "Stronger evidence"),
    (20, 50, "Moderate evidence"),
    (10, 20, "Developing evidence"),
    (0, 10, "Limited evidence"),
]


def evidence_band(n_complaints: int) -> str:
    """Label how much complaint evidence supports a lender's scores."""
    for low, high, label in EVIDENCE_BANDS:
        if low <= n_complaints < high:
            return label
    raise ValueError(f"complaint count out of range: {n_complaints}")


# ---------------------------------------------------------------------------
# Method C
# ---------------------------------------------------------------------------


def peer_rates(features: pd.DataFrame) -> dict[str, float]:
    """Peer reference rate per dimension: the fitted Beta population median."""
    rates: dict[str, float] = {}
    for slug in DIMENSIONS:
        alpha = float(features[f"prior_alpha_{slug}"].iloc[0])
        beta = float(features[f"prior_beta_{slug}"].iloc[0])
        rates[slug] = float(beta_dist.median(alpha, beta))
    return rates


def method_c_scores(features: pd.DataFrame, slug: str) -> np.ndarray:
    """The validated Method C score for one dimension, one value per lender.

    Score = 100 * BetaCDF(peer_rate | x + alpha, n - x + beta)

    Higher prevalence of the complaint type lowers the score, and a thin
    complaint history is pulled toward the peer rate by the prior rather than
    producing an extreme estimate.
    """
    alpha = float(features[f"prior_alpha_{slug}"].iloc[0])
    beta = float(features[f"prior_beta_{slug}"].iloc[0])
    reference = float(beta_dist.median(alpha, beta))

    n = features["n_complaints"].to_numpy(float)
    x = features[f"n_{slug}"].to_numpy(float)
    return 100.0 * beta_dist.cdf(reference, x + alpha, n - x + beta)


def build_records(
    features: pd.DataFrame,
    issues: dict[str, dict[str, list[tuple[str, int]]]] | None = None,
) -> list[dict]:
    """Build one Safety Label record per canonical payday lender.

    ``issues`` is the observed CFPB issue composition. It is presentation data:
    it is not an input to any score, prior, peer rate or comparison, and
    omitting it leaves the methodology-bearing fields byte-identical.
    """
    issues = issues or {}
    references = peer_rates(features)
    scores = {slug: method_c_scores(features, slug) for slug in DIMENSIONS}
    n_all = features["n_complaints"].to_numpy(int)

    records: list[dict] = []
    for row_idx, row in features.iterrows():
        n_complaints = int(row["n_complaints"])
        company = str(row["canonical_company"])
        buckets = issues.get(company, {})
        dimensions: dict[str, dict] = {}

        for slug in DIMENSIONS:
            lo90 = float(row[f"post_lo90_{slug}"])
            hi90 = float(row[f"post_hi90_{slug}"])
            reference = references[slug]

            # The 90% interval spanning the peer rate means the data cannot separate
            # this lender from a typical peer on this dimension. This is the same
            # test the scoring notebook used to check calibration, and the wording
            # is resolved here so the UI never has to interpret a statistic.
            if lo90 > reference:
                comparison = "more"
            elif hi90 < reference:
                comparison = "fewer"
            else:
                comparison = "similar"

            dimension_count = int(row[f"n_{slug}"])
            entry = {
                "score": round(float(scores[slug][row_idx]), 1),
                "complaints": dimension_count,
                "prevalence": round(float(row[f"post_{slug}"]), 5),
                "prevalence_lo90": round(lo90, 5),
                "prevalence_hi90": round(hi90, 5),
                "comparison": comparison,
            }
            if issues:
                # Observed share of this lender's own payday complaints. This is
                # a composition of complaints, not a rate per customer.
                entry["share"] = (
                    round(dimension_count / n_complaints, 5) if n_complaints else 0.0
                )
                entry["issues"] = [list(pair) for pair in buckets.get(slug, [])]
            dimensions[slug] = entry

        record = {
            "id": str(row_idx),
            "name": company,
            "n_complaints": n_complaints,
            "evidence": evidence_band(n_complaints),
            "dimensions": dimensions,
        }
        if issues:
            other_count = int(row.get("n_outside_dims", 0))
            record["other"] = {
                "label": OTHER_LABEL,
                "summary": OTHER_SUMMARY,
                "complaints": other_count,
                "share": round(other_count / n_complaints, 5) if n_complaints else 0.0,
                "issues": [list(pair) for pair in buckets.get(OTHER_DIMENSION, [])],
            }
        records.append(record)

    return records


def dimension_metadata(features: pd.DataFrame) -> dict[str, dict]:
    """Dimension label, explanation and peer rate, emitted once per dimension.

    Keeping this out of the per-lender records is what keeps the artifact small:
    repeating five explanations 482 times costs more than the scores do.
    """
    references = peer_rates(features)
    return {
        slug: {
            "label": DIMENSION_LABELS[slug],
            "summary": DIMENSION_SUMMARIES[slug],
            "peer_rate": round(references[slug], 5),
            "consumers_reported": CONSUMER_REPORTED[slug],
            "what_to_inspect": WATCH_FOR[slug],
        }
        for slug in DIMENSIONS
    }


def build_payload(
    features: pd.DataFrame,
    issues: dict[str, dict[str, list[tuple[str, int]]]] | None = None,
    taxonomy: pd.DataFrame | None = None,
) -> dict:
    """Assemble the full artifact, including the metadata the UI discloses."""
    records = build_records(features, issues)
    payload = {
        "schema_version": 1,
        "method": "Method C (empirical-Bayes Beta-Binomial posterior, peer-referenced)",
        "methodology": {
            "direction": (
                "Higher scores indicate a more favorable CFPB complaint profile "
                "relative to modeled payday-loan peers."
            ),
            "summary": (
                "FinePrint analyzes CFPB consumer complaints for payday loans. "
                "Each dimension compares the pattern of complaints associated "
                "with a lender against modeled payday-loan peers. Statistical "
                "shrinkage reduces extreme estimates when relatively little "
                "complaint data is available."
            ),
            "caveats": [
                # Each of these is asserted by test_methodology_disclosures_present.
                # They are consumer-facing guardrails, not decoration: tightening
                # the wording is fine, dropping the substance is not.
                "CFPB complaints are consumer-submitted reports and do not "
                "necessarily indicate verified wrongdoing.",
                "Complaint volume is used to communicate evidence strength; a "
                "lender is not penalized simply for having more complaints "
                "because FinePrint does not currently have lender-level customer "
                "or loan-volume denominators.",
                "A score describes the volume of consumer complaints relative to "
                "modeled peers. It is not the probability that a borrower will "
                "experience harm.",
            ],
            "evidence_bands": [
                {"min_complaints": low, "label": label}
                for low, _high, label in sorted(EVIDENCE_BANDS)
            ],
        },
        "dimensions": dimension_metadata(features),
        "lender_count": len(records),
        "total_complaints": int(features["n_complaints"].sum()),
        "lenders": records,
    }
    if issues is not None:
        payload["schema_version"] = 2
        payload["issues"] = issue_metadata(
            taxonomy if taxonomy is not None else load_taxonomy()
        )
        payload["complaint_share_note"] = (
            "Shares are of the CFPB payday-loan complaints associated with a "
            "lender in this dataset. They are not a rate per customer: this "
            "dataset has no lender-level count of customers, loans or "
            "transaction volume, so no customer-level complaint rate can be "
            "computed."
        )
    return payload



# ---------------------------------------------------------------------------
# Observed complaint composition: the underlying CFPB issue taxonomy
# ---------------------------------------------------------------------------
#
# Added after Method C was validated. Nothing here feeds the score, the peer
# reference, the priors or the comparison field; this is observed counts only,
# so the product can lead with what consumers actually reported and keep the
# modelling as context.
#
# The mapping is never reconstructed in the UI. Issue labels, their dimension
# assignment and their counts are resolved here, offline, and written into the
# artifact; the browser only reads the result.

ISSUES_CSV = REPO_ROOT / "data" / "processed" / "lender_subproduct_features.csv"
TAXONOMY_CSV = REPO_ROOT / "data" / "processed" / "issue_taxonomy.csv"

# The sub-product the label is built on. The feature file holds every CFPB
# sub-product, so restricting to this one is what makes the issue counts line up
# with the payday complaint totals in the scoring features.
PAYDAY_SUBPRODUCT = "Payday loan"

# The bucket for issues the taxonomy assigns to a category that is not one of the
# five scored dimensions: borrower financial distress, collections and
# repossession, disclosures and marketing, and other-or-unclear. Together these
# account for exactly the complaints outside the five dimensions, which the test
# suite asserts against n_outside_dims.
OTHER_DIMENSION = "other"

OTHER_LABEL = "Other reported issues"
OTHER_SUMMARY = (
    "Complaints in categories FinePrint does not score separately, including "
    "borrower financial distress, collections and repossession, disclosures and "
    "marketing, and issues that were too unclear to categorise."
)

# What a consumer can actually inspect, per dimension. Deliberately phrased as
# things to check rather than things the lender does, because a complaint is an
# allegation and not a finding.
WATCH_FOR: dict[str, str] = {
    "fees": (
        "Check the APR and fee disclosures, including origination fees, late "
        "fees and any charges for add-on products or services."
    ),
    "withdrawal": (
        "Check the authorisation for automatic withdrawals, the dates and "
        "amounts taken, and how to cancel or revoke that authorisation."
    ),
    "servicing": (
        "Check how payments are credited, what happens if a payment is late or "
        "short, how to reach the lender, and how payoff is handled."
    ),
    "unauthorized": (
        "Check your application and authorisation records, and monitor account "
        "activity for loans you do not recognise."
    ),
    "credit_rep": (
        "Check what is reported to credit bureaus, and how to dispute an "
        "inaccurate entry."
    ),
}

# Plain-language restatement of each dimension, in the "consumers reported"
# voice. The existing DIMENSION_SUMMARIES stay as the methodological
# description; these are the consumer-facing ones.
CONSUMER_REPORTED: dict[str, str] = {
    "fees": "Consumers reported fees or interest they did not expect.",
    "withdrawal": (
        "Consumers reported problems stopping withdrawals from a bank account, "
        "or money being withdrawn on an unexpected date or for an unexpected "
        "amount."
    ),
    "unauthorized": (
        "Consumers reported receiving loans they said they did not apply for."
    ),
    "credit_rep": (
        "Complaints involved information reported to credit bureaus, or "
        "problems disputing that information."
    ),
    "servicing": (
        "Complaints involved making payments, getting payments credited "
        "correctly, contacting the lender, or managing the loan."
    ),
}

# Maps a taxonomy category onto a scored dimension slug, or onto the other
# bucket. Derived from DIMENSIONS so the two cannot drift.
_CATEGORY_TO_DIMENSION: dict[str, str] = {v: k for k, v in DIMENSIONS.items()}


def load_taxonomy(csv_path: Path = TAXONOMY_CSV) -> pd.DataFrame:
    """The validated issue taxonomy: CFPB label to dimension and consumer wording."""
    taxonomy = pd.read_csv(csv_path)
    taxonomy["dimension"] = taxonomy["proposed_category"].map(_CATEGORY_TO_DIMENSION)
    taxonomy["dimension"] = taxonomy["dimension"].fillna(OTHER_DIMENSION)
    return taxonomy


def load_issue_counts(
    taxonomy: pd.DataFrame,
    features: pd.DataFrame,
    csv_path: Path = ISSUES_CSV,
) -> dict[str, dict[str, list[tuple[str, int]]]]:
    """Observed complaint counts per lender, per dimension, per CFPB issue.

    Returns ``{lender_name: {dimension: [(issue_key, count), ...]}}``. Only
    non-zero counts are kept, and each dimension's list is ordered by count so
    the UI can present the most-reported issue first without sorting.

    The dimension totals produced here are asserted in the test suite to equal
    the scoring features' own ``n_<slug>`` columns, so this rollup cannot quietly
    diverge from the validated pipeline.
    """
    raw = pd.read_csv(csv_path)
    payday = raw[raw["Sub-product"] == PAYDAY_SUBPRODUCT]
    count_columns = [c for c in raw.columns if c.startswith("cnt__")]

    key_to_dimension = dict(zip(taxonomy["issue_key"], taxonomy["dimension"]))
    per_company = payday.groupby("canonical_company")[count_columns].sum()

    wanted = set(features["canonical_company"])
    result: dict[str, dict[str, list[tuple[str, int]]]] = {}
    for company, row in per_company.iterrows():
        if company not in wanted:
            continue
        buckets: dict[str, list[tuple[str, int]]] = {}
        for column, value in row.items():
            count = int(value)
            if count <= 0:
                continue
            key = column.replace("cnt__", "")
            dimension = key_to_dimension.get(key)
            if dimension is None:  # pragma: no cover - taxonomy is closed
                continue
            buckets.setdefault(dimension, []).append((key, count))
        for dimension, pairs in buckets.items():
            pairs.sort(key=lambda pair: (-pair[1], pair[0]))
        result[str(company)] = buckets
    return result


def issue_metadata(taxonomy: pd.DataFrame) -> dict[str, dict]:
    """Issue key to label, dimension and conduct signal, emitted once.

    Per-lender records carry only ``[key, count]`` pairs, so the labels are not
    repeated 482 times. This is the same reason dimension explanations live at
    the top level rather than inside every record.
    """
    return {
        str(row["issue_key"]): {
            "label": str(row["canonical_issue"]),
            "dimension": str(row["dimension"]),
            "conduct_signal": str(row["conduct_signal"]),
        }
        for _, row in taxonomy.iterrows()
    }

def load_features(csv_path: Path = FEATURES_CSV) -> pd.DataFrame:
    """Read the processed CFPB features and sanity-check the assumptions."""
    if not csv_path.exists():
        raise FileNotFoundError(
            f"{csv_path} not found. The processed CFPB features are "
            "git-ignored; regenerate them with notebooks/cfpb_shrinkage.ipynb."
        )

    features = pd.read_csv(csv_path)
    required = {"canonical_company", "n_complaints"} | {
        f"{prefix}_{slug}" for slug in DIMENSIONS for prefix in ("n", "post", "post_lo90", "post_hi90", "prior_alpha", "prior_beta")
    }
    missing = required - set(features.columns)
    if missing:
        raise ValueError(f"feature file is missing columns: {sorted(missing)}")
    return features


def write_json(payload: dict, output_path: Path = OUTPUT_JSON) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path, default=FEATURES_CSV)
    parser.add_argument("--output", type=Path, default=OUTPUT_JSON)
    parser.add_argument("--issues", type=Path, default=ISSUES_CSV)
    parser.add_argument("--taxonomy", type=Path, default=TAXONOMY_CSV)
    args = parser.parse_args()

    features = load_features(args.features)

    # Observed complaint composition. Additive only: if the processed issue
    # features are missing the artifact is still built, just without the
    # per-issue breakdown.
    issues = None
    taxonomy = None
    if args.issues.exists() and args.taxonomy.exists():
        taxonomy = load_taxonomy(args.taxonomy)
        issues = load_issue_counts(taxonomy, features, args.issues)

    payload = build_payload(features, issues, taxonomy)
    path = write_json(payload, args.output)

    size_kb = path.stat().st_size / 1024
    print(f"wrote {path} ({size_kb:.0f} KB)")
    print(f"  lenders        {payload['lender_count']}")
    print(f"  complaints     {payload['total_complaints']}")
    print(f"  dimensions     {len(DIMENSIONS)}")
    for slug in DIMENSIONS:
        rate = peer_rates(features)[slug]
        print(f"  {slug:<14} peer reference rate {rate:.4f}")


if __name__ == "__main__":
    main()
