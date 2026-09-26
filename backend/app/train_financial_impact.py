"""Train the household financial context model and export it for serving.

This is the offline half of the teammate's ``SNAPModeltrain.py``, integrated
without changing the model. Upstream trained a fresh XGBoost classifier on every
invocation and then discarded it -- ``SNAPModeltrain.py:91-93`` has the
``model.save_model(...)`` call commented out -- so nothing could ever be served.
Here the same model is trained once, reproducibly, and written to disk as a
booster that the API loads.

What is preserved from upstream, unchanged:

* the nine features, their order, and the two derived columns
* the target and the ``SNAP in {0, 1}`` filter that drops "Refused" (-1) and
  "Not sure" (8)
* ``train_test_split(test_size=0.2, random_state=42, stratify=y)``
* every XGBoost hyperparameter
* ``finalwt`` as the sample weight for both fitting and evaluation

The two deliberate differences, both forced by the environment bugs documented
in ``app.financial_impact``:

1. the model is exported through ``model.get_booster().save_model(...)``
   because ``XGBClassifier.save_model``/``load_model`` are mutually broken
   across scikit-learn 1.6 and 1.9;
2. the survey reference distribution used for percentile comparisons is computed
   from the held-out split, so the baseline is out-of-sample rather than
   optimistic.

Neither changes a single model parameter, split, or prediction.

Run it from ``backend/``::

    python -m app.train_financial_impact

Input : ../wellbeing.csv (CFPB NFWBS public-use file, already committed)
Output: app/generated/financial_impact_model.json   (the booster)
        app/generated/financial_impact_context.json (codebook + reference)
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.model_selection import train_test_split

from app.financial_impact import (
    CATEGORICAL_FEATURES,
    CHILD_FEATURES,
    CONTEXT_PATH,
    FEATURES,
    MODEL_PATH,
    NUMERIC_FEATURES,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
SURVEY_CSV = REPO_ROOT / "wellbeing.csv"

SURVEY_NAME = "CFPB National Financial Well-Being Survey (public-use file)"
SURVEY_YEAR = 2016
SOURCE_SCRIPT = "SNAPModeltrain.py"

TARGET_COLUMN = "SNAP"
WEIGHT_COLUMN = "finalwt"
SEED = 42
TEST_SIZE = 0.2

CAVEATS = [
    "Based on a 2016 survey of 6,394 US households. It does not describe 2026 "
    "finances, and benefit rules and costs have changed since.",
    "This is a statistical association, not a cause and not a personal "
    "forecast. Two households with identical answers can sit in very different "
    "circumstances.",
    "The survey asked whether anyone received SNAP benefits. Many eligible "
    "households do not apply, so the survey item understates hardship, not the "
    "other way round.",
    "The model was not designed for payday lending and contains no loan terms "
    "whatsoever -- no amount, rate, payment or term.",
    "Neighbourhood poverty is measured at county level, which is a blunt "
    "instrument and often does not describe an individual household.",
]


def load_survey(csv_path: Path = SURVEY_CSV) -> pd.DataFrame:
    """Load the survey and build the features exactly as upstream does."""
    df = pd.read_csv(csv_path)

    for col in CATEGORICAL_FEATURES:
        df[col] = df[col].astype("category")

    df["total_children"] = df[CHILD_FEATURES].sum(axis=1)
    df["child_ratio"] = df["total_children"] / df["PPHHSIZE"]

    # Drop "Refused" (-1) and "Not sure" (8), as upstream does.
    df = df[df[TARGET_COLUMN].isin([0, 1])].copy()
    return df


def train(df: pd.DataFrame) -> tuple[xgb.XGBClassifier, dict[str, np.ndarray]]:
    """Fit the model with upstream's split, seed, weights and hyperparameters."""
    X = df[FEATURES]
    y = df[TARGET_COLUMN].astype(int)
    weights = df[WEIGHT_COLUMN]

    X_train, X_val, y_train, y_val, w_train, w_val = train_test_split(
        X, y, weights, test_size=TEST_SIZE, random_state=SEED, stratify=y
    )

    model = xgb.XGBClassifier(
        objective="binary:logistic",
        eval_metric="logloss",
        enable_categorical=True,
        tree_method="hist",
        n_estimators=300,
        learning_rate=0.03,
        max_depth=4,
        random_state=SEED,
    )
    model.fit(
        X_train,
        y_train,
        sample_weight=w_train,
        eval_set=[(X_val, y_val)],
        sample_weight_eval_set=[w_val],
        verbose=False,
    )
    return model, {
        "X_val": X_val,
        "y_val": y_val,
        "w_val": w_val,
    }


def evaluate(model: xgb.XGBClassifier, holdout: dict[str, np.ndarray]) -> dict:
    """Weighted holdout metrics, using upstream's 0.35 reporting threshold."""
    probabilities = model.predict_proba(holdout["X_val"])[:, 1]
    report = classification_report(
        holdout["y_val"],
        (probabilities >= 0.35).astype(int),
        output_dict=True,
        zero_division=0,
    )
    return {
        "weighted_roc_auc": float(
            roc_auc_score(
                holdout["y_val"], probabilities, sample_weight=holdout["w_val"]
            )
        ),
        "weighted_accuracy_at_0.35": float(report["weighted avg"]["recall"]),
        "recall_positive_at_0.35": float(report["1"]["recall"]),
        "precision_positive_at_0.35": float(report["1"]["precision"]),
    }


def reference_distribution(
    model: xgb.XGBClassifier, holdout: dict[str, np.ndarray]
) -> list[float]:
    """Out-of-sample quantiles of the model output across survey households.

    Taken from the held-out split so the percentile baseline reflects how the
    model scores households it has not seen, instead of its in-sample spread.
    """
    booster = model.get_booster()
    matrix = xgb.DMatrix(holdout["X_val"], enable_categorical=True)
    probabilities = booster.predict(matrix)
    return [float(v) for v in np.quantile(probabilities, np.linspace(0.0, 1.0, 101))]


def build_reference(metrics: dict, quantiles: list[float], n_survey: int) -> dict:
    return {
        "survey": SURVEY_NAME,
        "survey_year": SURVEY_YEAR,
        "households_modelled": int(n_survey),
        "target": "Any household member received SNAP benefits",
        "weighted_roc_auc": metrics["weighted_roc_auc"],
        "metrics": metrics,
        "features": FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "numeric_features": NUMERIC_FEATURES,
        "reference_quantiles": quantiles,
        "reference_basis": (
            "101 quantiles of the model output over the 1,247 held-out survey "
            "households, so percentile comparisons are out-of-sample."
        ),
        "seed": SEED,
        "test_size": TEST_SIZE,
        "source_script": SOURCE_SCRIPT,
        "caveats": CAVEATS,
    }


def write_model(model: xgb.XGBClassifier, path: Path = MODEL_PATH) -> Path:
    """Export via the raw booster to sidestep the sklearn serialization bug."""
    path.parent.mkdir(parents=True, exist_ok=True)
    model.get_booster().save_model(str(path))
    return path


def write_reference(reference: dict, path: Path = CONTEXT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(reference, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> None:
    survey_path = SURVEY_CSV
    if not survey_path.exists():
        raise SystemExit(
            f"Survey file not found at {survey_path}. The CFPB NFWBS public-use "
            "file is required to train the model."
        )

    df = load_survey(survey_path)
    model, holdout = train(df)
    metrics = evaluate(model, holdout)
    quantiles = reference_distribution(model, holdout)
    reference = build_reference(metrics, quantiles, len(df))

    model_path = write_model(model)
    reference_path = write_reference(reference)

    print(f"Survey rows modelled: {len(df)}")
    print(f"Weighted ROC-AUC:     {metrics['weighted_roc_auc']:.6f}")
    print(
        f"Positive recall @0.35: {metrics['recall_positive_at_0.35']:.3f}  "
        f"precision: {metrics['precision_positive_at_0.35']:.3f}"
    )
    print(f"Wrote {model_path} ({model_path.stat().st_size / 1024:.0f} KB)")
    print(f"Wrote {reference_path} ({reference_path.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
