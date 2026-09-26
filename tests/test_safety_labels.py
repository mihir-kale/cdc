"""Tests for the FinePrint Payday Loan Safety Label.

These lock the production score to the values published in the analysis
notebooks, so a change to the scoring code cannot silently move a number a
consumer has already seen.

    python -m unittest discover -s tests -v

Tests that need the git-ignored processed features skip when those are absent,
so this suite still runs on a fresh clone. The committed artifact is always
checked.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.safety_labels import (  # noqa: E402
    DIMENSIONS,
    OUTPUT_JSON,
    build_payload,
    evidence_band,
    load_features,
    method_c_scores,
    peer_rates,
    write_json,
)

# Published in notebooks/cfpb_dimension_scoring.ipynb. Peer reference rates are
# the fitted Beta population medians; the score vector is that notebook's
# validated reference row for Albert Corporation (n = 85).
EXPECTED_PEER_RATES = {
    "withdrawal": 0.068421,
    "fees": 0.207497,
    "unauthorized": 0.095443,
    "credit_rep": 0.040640,
    "servicing": 0.241351,
}

EXPECTED_ALBERT_SCORES = {
    "withdrawal": 0.000000,
    "fees": 56.765869,
    "unauthorized": 99.833773,
    "credit_rep": 99.210020,
    "servicing": 94.740290,
}

FORBIDDEN_KEYS = ("overall", "grade", "rank", "composite", "total_score", "safety_score")


def load_artifact() -> dict:
    if not OUTPUT_JSON.exists():
        raise unittest.SkipTest(
            f"{OUTPUT_JSON} is missing; run `python -m app.safety_labels` from backend/"
        )
    return json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))


class TestEvidenceBands(unittest.TestCase):
    def test_band_boundaries(self) -> None:
        self.assertEqual(evidence_band(0), "Limited evidence")
        self.assertEqual(evidence_band(9), "Limited evidence")
        self.assertEqual(evidence_band(10), "Developing evidence")
        self.assertEqual(evidence_band(19), "Developing evidence")
        self.assertEqual(evidence_band(20), "Moderate evidence")
        self.assertEqual(evidence_band(49), "Moderate evidence")
        self.assertEqual(evidence_band(50), "Stronger evidence")
        self.assertEqual(evidence_band(335), "Stronger evidence")


class TestArtifact(unittest.TestCase):
    """Checks that do not need the git-ignored processed features."""

    def setUp(self) -> None:
        self.artifact = load_artifact()

    def test_dataset_shape(self) -> None:
        self.assertEqual(self.artifact["lender_count"], 482)
        self.assertEqual(len(self.artifact["lenders"]), 482)
        self.assertEqual(self.artifact["total_complaints"], 6024)

    def test_every_lender_has_five_dimensions(self) -> None:
        for lender in self.artifact["lenders"]:
            self.assertEqual(
                set(lender["dimensions"]), set(DIMENSIONS), lender["name"]
            )

    def test_scores_are_in_range(self) -> None:
        for lender in self.artifact["lenders"]:
            for slug, values in lender["dimensions"].items():
                self.assertGreaterEqual(values["score"], 0.0, (lender["name"], slug))
                self.assertLessEqual(values["score"], 100.0, (lender["name"], slug))

    def test_credible_intervals_are_ordered_and_in_range(self) -> None:
        for lender in self.artifact["lenders"]:
            for slug, values in lender["dimensions"].items():
                lo, hi = values["prevalence_lo90"], values["prevalence_hi90"]
                self.assertLessEqual(lo, hi, (lender["name"], slug))
                self.assertGreaterEqual(lo, 0.0, (lender["name"], slug))
                self.assertLessEqual(hi, 1.0, (lender["name"], slug))

    def test_evidence_matches_complaint_count(self) -> None:
        for lender in self.artifact["lenders"]:
            self.assertEqual(
                lender["evidence"], evidence_band(lender["n_complaints"]), lender["name"]
            )

    def test_lender_ids_are_unique(self) -> None:
        ids = [lender["id"] for lender in self.artifact["lenders"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_no_overall_score_or_grade(self) -> None:
        """The label must not collapse the five overlapping dimensions."""
        blob = json.dumps(self.artifact).lower()
        for key in FORBIDDEN_KEYS:
            self.assertNotIn(f'"{key}"', blob, f"artifact exposes {key}")

    def test_peer_rates_match_the_notebook(self) -> None:
        for slug, expected in EXPECTED_PEER_RATES.items():
            self.assertAlmostEqual(
                self.artifact["dimensions"][slug]["peer_rate"], expected, places=5, msg=slug
            )

    def test_methodology_disclosures_present(self) -> None:
        text = " ".join(
            [self.artifact["methodology"]["summary"]]
            + self.artifact["methodology"]["caveats"]
        ).lower()
        self.assertIn("shrinkage", text)
        self.assertIn("do not necessarily indicate verified wrongdoing", text)
        self.assertIn("not penalized simply for having more complaints", text)
        self.assertIn("not the probability that a borrower will experience harm", text)
        self.assertIn("more favorable", self.artifact["methodology"]["direction"].lower())


class TestMethodC(unittest.TestCase):
    """Reproduces the validated formula against the processed features."""

    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.features = load_features()
        except (FileNotFoundError, ValueError) as exc:
            raise unittest.SkipTest(f"processed features unavailable: {exc}") from exc

    def test_peer_rates_match_the_notebook(self) -> None:
        for slug, expected in EXPECTED_PEER_RATES.items():
            self.assertAlmostEqual(peer_rates(self.features)[slug], expected, places=5, msg=slug)

    def test_albert_reference_row(self) -> None:
        """The exact vector published in cfpb_dimension_scoring.ipynb."""
        mask = (self.features["canonical_company"] == "Albert Corporation").to_numpy()
        self.assertEqual(int(mask.sum()), 1, "reference lender missing from features")
        self.assertEqual(int(self.features.loc[mask, "n_complaints"].iloc[0]), 85)

        for slug, expected in EXPECTED_ALBERT_SCORES.items():
            got = float(method_c_scores(self.features, slug)[mask][0])
            self.assertAlmostEqual(got, expected, places=5, msg=slug)

    def test_direction_is_decreasing_in_prevalence(self) -> None:
        """Higher complaint prevalence must give a lower score, in every dimension."""
        for slug in DIMENSIONS:
            scores = method_c_scores(self.features, slug)
            prevalence = self.features[f"post_{slug}"].to_numpy(float)
            order = prevalence.argsort()
            # Compare the extremes, which is assumption-free.
            self.assertGreater(
                scores[order[0]],
                scores[order[-1]],
                f"{slug}: lowest-prevalence lender must score above the highest",
            )

    def test_low_volume_lenders_are_shrunk_toward_the_middle(self) -> None:
        """Empirical-Bayes shrinkage must compress the low-volume band."""
        n = self.features["n_complaints"].to_numpy(float)
        for slug in DIMENSIONS:
            scores = method_c_scores(self.features, slug)
            thin, thick = scores[n < 10], scores[n >= 50]

            def iqr(values):
                return float(
                    sorted(values)[int(0.75 * len(values))] - sorted(values)[int(0.25 * len(values))]
                )

            self.assertLess(
                iqr(thin), iqr(thick), f"{slug}: low-volume band is not compressed"
            )

    def test_regenerating_reproduces_the_committed_artifact(self) -> None:
        """The committed JSON must be exactly what the script produces."""
        committed = load_artifact()
        rebuilt = build_payload(self.features)
        self.assertEqual(
            json.dumps(rebuilt, separators=(",", ":")),
            json.dumps(committed, separators=(",", ":")),
            "committed artifact is stale; re-run `python -m app.safety_labels`",
        )

    def test_write_json_is_deterministic(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            a = write_json(build_payload(self.features), Path(tmp) / "a.json")
            b = write_json(build_payload(self.features), Path(tmp) / "b.json")
            self.assertEqual(a.read_bytes(), b.read_bytes())


if __name__ == "__main__":
    unittest.main()
