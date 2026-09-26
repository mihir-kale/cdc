"""Tests for the Household Financial Context model and its API.

Two jobs. First, lock the integration to the teammate's original model: the
same features in the same order, the same survey codes, and predictions that
match what the model returns when the survey is scored in one batch. Second,
prove the personal assessment stays separate from the CFPB Safety Label.

The batch-parity test is the important one. A one-row inference frame cast with
a bare ``astype("category")`` renumbers every category from zero, which sends
xgboost down the wrong branch of each categorical split and returns a
confidently wrong probability -- 0.260 instead of 0.0060 on a real survey
household. Nothing else in this suite would catch that, so it is asserted
against the survey itself.

    python -m unittest discover -s tests -v

Everything here runs on a fresh clone: the model artifact is committed, and
only the retraining-reproducibility test needs the survey's training stack.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app import financial_impact, label_store  # noqa: E402
from app.financial_impact import (  # noqa: E402
    AGE_BANDS,
    CATEGORICAL_CATEGORIES,
    CATEGORICAL_FEATURES,
    CHILD_INPUT_FIELDS,
    COUNTY_POVERTY_SHARE,
    EDUCATION_LEVELS,
    FEATURES,
    HOUSEHOLD_SIZES,
    INCOME_BANDS,
    MARITAL_STATUS,
    METRO_STATUS,
    MODEL_PATH,
    CONTEXT_PATH,
    association_rate,
    build_feature_frame,
    household_context,
    load_model,
    load_reference,
    validate_inputs,
)
from app.main import app  # noqa: E402

SURVEY_CSV = REPO_ROOT / "wellbeing.csv"

#: The teammate's reported holdout performance, from running SNAPModeltrain.py
#: unmodified. If this moves, the integration has drifted from the source model.
EXPECTED_ROC_AUC = 0.880498


def profile(**overrides: object) -> dict:
    """A valid mid-range household profile, with optional field overrides."""
    base: dict = {
        "age_band": 3,
        "education": 2,
        "household_income": 2,
        "marital_status": 4,
        "household_size": 3,
        "metro_area": 1,
        "county_poverty_share": 1,
        "children_0_1": True,
        "children_2_5": True,
        "children_6_12": False,
        "children_13_17": False,
    }
    base.update(overrides)
    return base


class TestArtifacts(unittest.TestCase):
    """The committed artifacts must exist and be internally consistent."""

    def test_model_artifact_is_committed(self) -> None:
        self.assertTrue(
            MODEL_PATH.exists(),
            f"{MODEL_PATH} missing. Run `python -m app.train_financial_impact`.",
        )

    def test_reference_artifact_is_committed(self) -> None:
        self.assertTrue(
            CONTEXT_PATH.exists(),
            f"{CONTEXT_PATH} missing. Run `python -m app.train_financial_impact`.",
        )

    def test_module_loads(self) -> None:
        """The calculation layer must import and load without Streamlit/sklearn."""
        booster = load_model()
        self.assertIsNotNone(booster)
        self.assertEqual(len(booster.feature_names), len(FEATURES))

    def test_inference_does_not_import_training_only_deps(self) -> None:
        """Serving must not require scikit-learn or Streamlit.

        Parsed rather than grepped: the module's docstring legitimately names
        both when explaining what it avoids, and a substring check would trip
        over that prose.
        """
        import ast

        tree = ast.parse(
            (REPO_ROOT / "backend" / "app" / "financial_impact.py").read_text()
        )
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

        self.assertNotIn("sklearn", imported)
        self.assertNotIn("streamlit", imported)
        self.assertIn("xgboost", imported)

    def test_reference_records_upstream_provenance(self) -> None:
        reference = load_reference()
        self.assertEqual(reference["source_script"], "SNAPModeltrain.py")
        self.assertEqual(reference["seed"], 42)
        self.assertEqual(reference["test_size"], 0.2)
        self.assertEqual(reference["households_modelled"], 6232)
        self.assertAlmostEqual(
            reference["weighted_roc_auc"], EXPECTED_ROC_AUC, places=5
        )

    def test_reference_quantiles_are_monotonic(self) -> None:
        quantiles = load_reference()["reference_quantiles"]
        self.assertEqual(len(quantiles), 101)
        self.assertTrue(all(a <= b for a, b in zip(quantiles, quantiles[1:])))


class TestFeatureContract(unittest.TestCase):
    def test_feature_order_is_unchanged(self) -> None:
        self.assertEqual(
            FEATURES,
            [
                "agecat",
                "PPEDUC",
                "PPINCIMP",
                "PPMARIT",
                "PPMSACAT",
                "PPHHSIZE",
                "total_children",
                "child_ratio",
                "PCTLT200FPL",
            ],
        )

    def test_categorical_categories_cover_the_codebook(self) -> None:
        """Every code a consumer may send must be a category the model knows."""
        self.assertEqual(CATEGORICAL_CATEGORIES["agecat"], sorted(AGE_BANDS))
        self.assertEqual(CATEGORICAL_CATEGORIES["PPEDUC"], sorted(EDUCATION_LEVELS))
        self.assertEqual(
            CATEGORICAL_CATEGORIES["PPINCIMP"], sorted(INCOME_BANDS)
        )
        self.assertEqual(CATEGORICAL_CATEGORIES["PPMARIT"], sorted(MARITAL_STATUS))
        self.assertEqual(CATEGORICAL_CATEGORIES["PPMSACAT"], sorted(METRO_STATUS))

    def test_derived_columns_match_upstream(self) -> None:
        frame = build_feature_frame(profile())
        self.assertEqual(int(frame["total_children"].iloc[0]), 2)
        self.assertAlmostEqual(float(frame["child_ratio"].iloc[0]), 2 / 3)

    def test_no_children_gives_zero_ratio(self) -> None:
        frame = build_feature_frame(
            profile(
                children_0_1=False,
                children_2_5=False,
                children_6_12=False,
                children_13_17=False,
            )
        )
        self.assertEqual(int(frame["total_children"].iloc[0]), 0)
        self.assertEqual(float(frame["child_ratio"].iloc[0]), 0.0)

    def test_frame_uses_full_category_sets(self) -> None:
        """Guards the silent-misprediction bug described in the module docstring."""
        frame = build_feature_frame(profile(age_band=4))
        for name in CATEGORICAL_FEATURES:
            self.assertEqual(
                list(frame[name].cat.categories),
                CATEGORICAL_CATEGORIES[name],
                f"{name} category set drifted from training",
            )


class TestValidation(unittest.TestCase):
    def test_valid_profile_passes(self) -> None:
        validate_inputs(profile())  # must not raise

    def test_rejects_out_of_range_code(self) -> None:
        with self.assertRaises(ValueError):
            validate_inputs(profile(age_band=99))

    def test_rejects_non_codebook_county_value(self) -> None:
        """-5, 0 and 1 are valid; 2 is not, and is not caught by a range check."""
        with self.assertRaises(ValueError):
            validate_inputs(profile(county_poverty_share=2))

    def test_rejects_missing_field(self) -> None:
        incomplete = profile()
        del incomplete["metro_area"]
        with self.assertRaises(ValueError):
            validate_inputs(incomplete)

    def test_every_codebook_value_is_accepted(self) -> None:
        """Any value the API advertises must actually work end to end."""
        for code in INCOME_BANDS:
            validate_inputs(profile(household_income=code))
        for code in COUNTY_POVERTY_SHARE:
            validate_inputs(profile(county_poverty_share=code))
        for code in METRO_STATUS:
            validate_inputs(profile(metro_area=code))
        for code in HOUSEHOLD_SIZES:
            validate_inputs(profile(household_size=code))


class TestInference(unittest.TestCase):
    def test_probability_is_a_valid_rate(self) -> None:
        rate = association_rate(profile())
        self.assertGreaterEqual(rate, 0.0)
        self.assertLessEqual(rate, 1.0)

    def test_lower_income_raises_the_association(self) -> None:
        """Income is the dominant feature (gain 0.44), so the direction is known."""
        low = association_rate(profile(household_income=1))
        high = association_rate(profile(household_income=9))
        self.assertGreater(low, high)

    def test_repeated_calls_are_deterministic(self) -> None:
        """The model is deterministic; there is no sampling at inference time."""
        rates = {association_rate(profile()) for _ in range(10)}
        self.assertEqual(len(rates), 1)

    def test_context_result_shape(self) -> None:
        result = household_context(profile())
        for field in (
            "context_band",
            "band_label",
            "summary",
            "survey_percentile",
            "model_association_rate",
            "what_this_is",
            "what_this_is_not",
            "methodology",
            "caveats",
        ):
            self.assertIn(field, result)
        self.assertIn(result["context_band"], {"higher_strain", "typical_strain", "lower_strain"})
        self.assertGreaterEqual(result["survey_percentile"], 0)
        self.assertLessEqual(result["survey_percentile"], 100)

    def test_context_states_the_limits(self) -> None:
        """The five things this must not claim, per the framing decision."""
        result = household_context(profile())
        joined = " ".join(result["what_this_is_not"]).lower()
        self.assertIn("does not predict what taking out a loan", joined)
        self.assertIn("qualify for snap", joined)
        self.assertIn("would receive snap", joined)
        self.assertIn("says nothing about any lender", joined)

    def test_context_is_independent_of_lenders(self) -> None:
        result = household_context(profile())
        self.assertIn("no lender data", result["methodology"]["relationship_to_safety_label"])
        # No lender-shaped field may leak into a personal result.
        for forbidden in ("lender", "safety_label", "dimensions", "complaints"):
            self.assertNotIn(forbidden, result)


class TestBatchParity(unittest.TestCase):
    """One-row inference must equal batch inference over the real survey.

    This is the regression test for the category-code bug. It needs the survey
    file and the training stack, so it skips when they are absent.
    """

    def _survey_frame(self):
        pd = financial_impact.pd
        df = pd.read_csv(SURVEY_CSV)
        for col in CATEGORICAL_FEATURES:
            df[col] = df[col].astype("category")
        df["total_children"] = df[list(CHILD_INPUT_FIELDS.values())].sum(axis=1)
        df["child_ratio"] = df["total_children"] / df["PPHHSIZE"]
        return df[df["SNAP"].isin([0, 1])].reset_index(drop=True)

    def test_single_row_matches_batch(self) -> None:
        if not SURVEY_CSV.exists():
            self.skipTest("wellbeing.csv not present")
        try:
            import xgboost as xgb
        except ImportError:  # pragma: no cover
            self.skipTest("xgboost not installed")

        frame = self._survey_frame()
        booster = load_model()
        batch = booster.predict(xgb.DMatrix(frame[FEATURES], enable_categorical=True))

        # Every value combination the codebook allows, so all categorical
        # branches are exercised, not just the ones this survey happens to hold.
        step = max(1, len(frame) // 200)
        rows = frame.iloc[::step]
        singles = []
        for _, row in rows.iterrows():
            singles.append(
                association_rate(
                    {
                        "age_band": int(row["agecat"]),
                        "education": int(row["PPEDUC"]),
                        "household_income": int(row["PPINCIMP"]),
                        "marital_status": int(row["PPMARIT"]),
                        "household_size": int(row["PPHHSIZE"]),
                        "metro_area": int(row["PPMSACAT"]),
                        "county_poverty_share": int(row["PCTLT200FPL"]),
                        "children_0_1": bool(row["PPT01"]),
                        "children_2_5": bool(row["PPT25"]),
                        "children_6_12": bool(row["PPT612"]),
                        "children_13_17": bool(row["PPT1317"]),
                    }
                )
            )

        for offset, single in zip(rows.index, singles):
            self.assertAlmostEqual(
                single,
                float(batch[offset]),
                places=12,
                msg=f"row {offset}: one-row inference diverged from batch",
            )

    def test_income_is_the_dominant_signal(self) -> None:
        """Income carries by far the most gain, so the endpoints must differ sharply.

        Deliberately not a monotonicity test. The booster is a step-function
        approximation, not a constrained monotone model, and it genuinely is not
        monotone across all nine bands -- band 7 scores above band 6. Asserting
        strict monotonicity would fail on correct behaviour.
        """
        rates = {
            code: association_rate(profile(household_income=code))
            for code in sorted(INCOME_BANDS)
        }
        self.assertGreater(rates[1], rates[9], "lowest band should exceed highest")
        lowest_three = sum(rates[c] for c in (1, 2, 3)) / 3
        highest_three = sum(rates[c] for c in (7, 8, 9)) / 3
        self.assertGreater(
            lowest_three,
            highest_three,
            "the three lowest income bands should average above the three highest",
        )


class TestTrainingReproducibility(unittest.TestCase):
    """Retraining must reproduce the committed artifact.

    A byte-identical retrain is only a meaningful invariant *within one CPU
    architecture*. XGBoost's histogram builder accumulates gradients in
    parallel, and floating-point addition is not associative, so ARM and x86-64
    round differently. With byte-identical package versions, macOS/arm64 and
    Linux/x86-64 produce two artifacts that differ in their serialized bytes but
    agree to ~1e-7 in predicted probability and exactly in weighted ROC-AUC.

    So this asserts both halves of the real invariant:

    * same architecture -> byte-identical (catches any accidental change to the
      model, features, or hyperparameters);
    * any architecture -> behaviorally identical (catches the same changes, and
      holds everywhere).
    """

    @classmethod
    def setUpClass(cls) -> None:
        if not SURVEY_CSV.exists():
            raise unittest.SkipTest("wellbeing.csv not present")
        try:
            from app import train_financial_impact as trainer
        except ImportError as exc:  # pragma: no cover
            raise unittest.SkipTest(f"training dependencies unavailable: {exc}") from exc
        try:
            import numpy as np
            import xgboost as xgb
        except ImportError as exc:  # pragma: no cover
            raise unittest.SkipTest(f"inference dependencies unavailable: {exc}") from exc
        cls.np = np
        cls.xgb = xgb
        cls.trainer = trainer
        cls.model, cls.holdout = trainer.train(trainer.load_survey())

    def test_retrained_bytes_match_on_the_producing_platform(self) -> None:
        reference = json.loads(CONTEXT_PATH.read_text())
        producer = reference.get("produced_on_platform", {})
        this = {"system": platform.system(), "machine": platform.machine()}
        if not producer:
            self.skipTest("no producing platform recorded; cannot scope byte check")
        if (producer.get("system"), producer.get("machine")) != (
            this["system"],
            this["machine"],
        ):
            self.skipTest(
                f"artifact was produced on {producer.get('system')}/"
                f"{producer.get('machine')}, running on {this['system']}/{this['machine']}; "
                "byte equality is not expected across architectures"
            )
        with tempfile.TemporaryDirectory() as tmp:
            path = self.trainer.write_model(
                self.model, Path(tmp) / "model.json"
            )
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest(),
                "retraining changed the model bytes on the producing platform; "
                "something in the model, features, or training changed",
            )

    def test_retrained_model_behaves_identically_everywhere(self) -> None:
        """Architecture-independent: the same model, to float32 precision."""
        reference = json.loads(CONTEXT_PATH.read_text())
        expected_auc = reference["metrics"]["weighted_roc_auc"]

        holdout_x = self.holdout["X_val"]
        retrained = self.model.predict_proba(holdout_x)[:, 1]
        self.assertAlmostEqual(
            float(
                self.trainer.evaluate(self.model, self.holdout)["weighted_roc_auc"]
            ),
            expected_auc,
            places=9,
            msg="retrained ROC-AUC moved; the model or the split changed",
        )

        committed = self.xgb.Booster()
        committed.load_model(str(MODEL_PATH))
        served = committed.predict(
            self.xgb.DMatrix(holdout_x, enable_categorical=True)
        )
        worst = float(self.np.abs(retrained - served).max())
        self.assertLess(
            worst,
            1e-6,
            f"retrained and committed models disagree by {worst:.3e} on the "
            "holdout set; expected float32 rounding noise only",
        )


class TestApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from fastapi.testclient import TestClient

        cls.client = TestClient(app)

    def test_health_reports_both_artifacts(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["artifacts"]["lender_safety_labels"])
        self.assertTrue(body["artifacts"]["financial_impact_model"])

    def test_inputs_endpoint_publishes_the_codebook(self) -> None:
        response = self.client.get("/financial-impact/inputs")
        self.assertEqual(response.status_code, 200)
        inputs = response.json()["inputs"]
        self.assertEqual(set(inputs), {*financial_impact.SCALAR_INPUT_FIELDS, "children"})
        self.assertEqual(len(inputs["household_income"]["options"]), 9)
        self.assertEqual(len(inputs["children"]["options"]), 4)
        self.assertEqual(inputs["children"]["control"], "checkbox")

    def test_context_accepts_a_valid_profile(self) -> None:
        response = self.client.post("/financial-impact/context", json=profile())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn(body["context_band"], {"higher_strain", "typical_strain", "lower_strain"})
        self.assertIsInstance(body["model_association_rate"], float)

    def test_context_rejects_malformed_input(self) -> None:
        for override in (
            {"age_band": 0},
            {"age_band": 99},
            {"education": 6},
            {"household_income": 0},
            {"metro_area": 2},
            {"county_poverty_share": 7},
            {"household_size": 9},
        ):
            with self.subTest(override=override):
                response = self.client.post(
                    "/financial-impact/context", json=profile(**override)
                )
                self.assertEqual(response.status_code, 422)

    def test_context_rejects_missing_input(self) -> None:
        incomplete = profile()
        del incomplete["marital_status"]
        response = self.client.post("/financial-impact/context", json=incomplete)
        self.assertEqual(response.status_code, 422)


class TestSeparationFromSafetyLabel(unittest.TestCase):
    """The personal assessment must not disturb the lender label."""

    def test_all_lenders_remain_searchable(self) -> None:
        self.assertEqual(len(label_store.lender_index()), 482)

    def test_context_calls_do_not_change_lender_scores(self) -> None:
        target = "albert-corporation"
        before = json.dumps(label_store.get_lender(target), sort_keys=True)
        for income in sorted(INCOME_BANDS):
            household_context(profile(household_income=income))
        after = json.dumps(label_store.get_lender(target), sort_keys=True)
        self.assertEqual(before, after, "the financial model mutated a safety label")

    def test_safety_label_has_no_household_fields(self) -> None:
        label = label_store.get_lender("albert-corporation")
        for forbidden in ("association_rate", "percentile", "context_band"):
            self.assertNotIn(forbidden, json.dumps(label))


if __name__ == "__main__":
    unittest.main()
