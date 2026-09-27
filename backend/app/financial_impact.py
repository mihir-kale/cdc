"""Household Financial Context -- inference for the teammate SNAP model.

This module owns the reusable calculation layer for the personal side of
FinePrint. It has no Streamlit dependency, no scikit-learn dependency, and no
dependency on the CFPB Safety Label code path. The running service only loads a
pre-trained XGBoost booster that ``app.train_financial_impact`` wrote offline.

Provenance
----------
The model is Amishi's ``SNAPModeltrain.py``, integrated unchanged. It is a
gradient-boosted classifier over nine household variables from the CFPB National
Financial Well-Being Survey public-use file (``wellbeing.csv``) that estimates
the survey's ``SNAP`` item, "Any household member received SNAP benefits".
Weighted holdout ROC-AUC 0.8805. Features, hyperparameters, the 80/20 split,
the survey weights and ``random_state=42`` are all exactly as written upstream.

Two environment bugs had to be worked around; both are recorded here so the
structural difference between this module and the original training script is
not mistaken for a redesign.

1. ``np.NaN`` removal. xgboost 2.0.3's ``pandas_cat_null`` calls ``np.NaN``,
   which NumPy deleted in 2.0, so the original script dies on any modern NumPy
   with ``AttributeError: np.NaN was removed in the NumPy 2.0 release``. Fixed by
   pinning ``numpy<2`` rather than by editing the model.

2. sklearn's 1.6 tag-system change broke model serialization in both
   directions. On scikit-learn 1.6.x ``XGBClassifier.save_model`` succeeds but
   ``load_model`` raises ``'super' object has no attribute '__sklearn_tags__'``;
   on scikit-learn 1.9.x ``save_model`` itself raises ``_estimator_type
   undefined``. The fix is to bypass the sklearn estimator wrapper entirely:
   training exports ``model.get_booster().save_model(...)`` and inference uses
   ``xgboost.Booster`` plus ``xgboost.DMatrix``. That path is bit-identical to
   ``predict_proba`` (max abs difference 0.0, verified across two different
   environment stacks) and it means the deployed service does not need
   scikit-learn installed at all.

Interpretation
--------------
The model associates household characteristics with SNAP receipt in a 2016
survey. It does not forecast what a loan will do to anyone, does not estimate
SNAP eligibility, and says nothing about any lender. The API therefore returns
the raw model probability for traceability, but the consumer-facing result is a
*relative* position within the survey population, described as a financial-strain
proxy. This module is entirely separate from the CFPB Safety Label and never
reads or writes lender scores.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xgboost as xgb

# ---------------------------------------------------------------------------
# Artifact locations
# ---------------------------------------------------------------------------

GENERATED_DIR = Path(__file__).resolve().parent / "generated"
MODEL_PATH = GENERATED_DIR / "financial_impact_model.json"
CONTEXT_PATH = GENERATED_DIR / "financial_impact_context.json"

_MISSING_MODEL_MESSAGE = (
    "The household financial context model has not been built. Run "
    "`python -m app.train_financial_impact` from backend/ to train it from "
    "wellbeing.csv and write "
    f"{MODEL_PATH}."
)

_MISSING_CONTEXT_MESSAGE = (
    "The household financial context reference data has not been built. Run "
    "`python -m app.train_financial_impact` from backend/ to regenerate "
    f"{CONTEXT_PATH}."
)

# ---------------------------------------------------------------------------
# Feature contract
#
# Order is load-bearing: it must match training exactly, because the booster
# consumes an unlabelled matrix in this order.
# ---------------------------------------------------------------------------

CATEGORICAL_FEATURES = ["agecat", "PPEDUC", "PPINCIMP", "PPMARIT", "PPMSACAT"]
NUMERIC_FEATURES = ["PPHHSIZE", "total_children", "child_ratio", "PCTLT200FPL"]
FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES

#: The four child-presence columns, in the order the survey declares them.
CHILD_FEATURES = ["PPT01", "PPT25", "PPT612", "PPT1317"]
CHILD_AGE_LABELS = {
    "PPT01": "Children age 0-1",
    "PPT25": "Children age 2-5",
    "PPT612": "Children age 6-12",
    "PPT1317": "Children age 13-17",
}

#: API field name -> survey column, so the wire format reads as plain language
#: while the model still receives the survey's own variables.
CHILD_INPUT_FIELDS = {
    "children_0_1": "PPT01",
    "children_2_5": "PPT25",
    "children_6_12": "PPT612",
    "children_13_17": "PPT1317",
}

#: The complete category set for each categorical feature, in the order xgboost
#: saw them at training time. Defined just below the codebook, which supplies
#: the values.
#:
#: This is load-bearing and easy to get wrong. A one-row inference frame cast
#: with a bare ``astype("category")`` derives its categories from that single
#: row, so a household aged 45-54 would be sent as category code 0 instead of
#: code 3. XGBoost would then evaluate the wrong branch of every categorical
#: split and return a confidently wrong number -- measured at 0.260 instead of
#: 0.0060 for a real survey household before this was fixed. Declaring the full
#: category set keeps the codes aligned with training.

#: The single-value inputs, API name -> survey column.
SCALAR_INPUT_FIELDS = {
    "age_band": "agecat",
    "education": "PPEDUC",
    "household_income": "PPINCIMP",
    "marital_status": "PPMARIT",
    "metro_area": "PPMSACAT",
    "household_size": "PPHHSIZE",
    "county_poverty_share": "PCTLT200FPL",
}

# ---------------------------------------------------------------------------
# Codebook
#
# Value labels transcribed from the official CFPB NFWBS public-use file
# codebook (September 2017), section 3 "Data Dictionary". They are the single
# source of truth for both the API contract and the UI copy, so the two cannot
# drift. Codes are the survey's own, not renumbered.
# ---------------------------------------------------------------------------

AGE_BANDS: dict[int, str] = {
    1: "18-24",
    2: "25-34",
    3: "35-44",
    4: "45-54",
    5: "55-61",
    6: "62-69",
    7: "70-74",
    8: "75 or older",
}

EDUCATION_LEVELS: dict[int, str] = {
    1: "Less than high school",
    2: "High school",
    3: "Some college or associate degree",
    4: "Bachelor's degree",
    5: "Graduate or professional degree",
}

INCOME_BANDS: dict[int, str] = {
    1: "Less than $20,000",
    2: "$20,000 to $29,999",
    3: "$30,000 to $39,999",
    4: "$40,000 to $49,999",
    5: "$50,000 to $59,999",
    6: "$60,000 to $74,999",
    7: "$75,000 to $99,999",
    8: "$100,000 to $149,999",
    9: "$150,000 or more",
}

MARITAL_STATUS: dict[int, str] = {
    1: "Married",
    2: "Widowed",
    3: "Divorced or separated",
    4: "Never married",
    5: "Living with partner",
}

HOUSEHOLD_SIZES: dict[int, str] = {
    1: "1 person",
    2: "2 people",
    3: "3 people",
    4: "4 people",
    5: "5 or more people",
}

METRO_STATUS: dict[int, str] = {0: "Non-metro area", 1: "Metro area"}

COUNTY_POVERTY_SHARE: dict[int, str] = {
    -5: "County not known",
    0: "Fewer than 40% of county below 200% of poverty",
    1: "40% or more of county below 200% of poverty",
}

#: The complete category set for each categorical feature, in the order xgboost
#: saw them at training time.
#:
#: This is load-bearing and easy to get wrong. A one-row inference frame cast
#: with a bare ``astype("category")`` derives its categories from that single
#: row, so a household aged 45-54 would be sent as category code 0 instead of
#: code 3. XGBoost would then evaluate the wrong branch of every categorical
#: split and return a confidently wrong number -- measured at 0.260 instead of
#: 0.0060 for a real survey household before this was fixed. Declaring the full
#: category set keeps the codes aligned with training.
CATEGORICAL_CATEGORIES: dict[str, list[int]] = {
    "agecat": sorted(AGE_BANDS),
    "PPEDUC": sorted(EDUCATION_LEVELS),
    "PPINCIMP": sorted(INCOME_BANDS),
    "PPMARIT": sorted(MARITAL_STATUS),
    "PPMSACAT": sorted(METRO_STATUS),
}

#: Options the API publishes so the frontend renders labels from the codebook
#: rather than hardcoding them in TypeScript. Single-choice fields carry a
#: ``control`` of "select"; the children group is a checkbox set.
INPUT_OPTIONS: dict[str, dict[str, Any]] = {
    "age_band": {
        "survey_variable": "agecat",
        "label": "Age",
        "control": "select",
        "options": [{"code": c, "label": v} for c, v in AGE_BANDS.items()],
    },
    "education": {
        "survey_variable": "PPEDUC",
        "label": "Highest level of education",
        "control": "select",
        "options": [{"code": c, "label": v} for c, v in EDUCATION_LEVELS.items()],
    },
    "household_income": {
        "survey_variable": "PPINCIMP",
        "label": "Household income",
        "control": "select",
        "options": [{"code": c, "label": v} for c, v in INCOME_BANDS.items()],
    },
    "marital_status": {
        "survey_variable": "PPMARIT",
        "label": "Marital status",
        "control": "select",
        "options": [{"code": c, "label": v} for c, v in MARITAL_STATUS.items()],
    },
    "household_size": {
        "survey_variable": "PPHHSIZE",
        "label": "People in your household",
        "control": "select",
        "options": [{"code": c, "label": v} for c, v in HOUSEHOLD_SIZES.items()],
    },
    "metro_area": {
        "survey_variable": "PPMSACAT",
        "label": "Where you live",
        "control": "select",
        "options": [{"code": c, "label": v} for c, v in METRO_STATUS.items()],
    },
    "county_poverty_share": {
        "survey_variable": "PCTLT200FPL",
        "label": "Poverty in your county",
        "control": "select",
        "options": [{"code": c, "label": v} for c, v in COUNTY_POVERTY_SHARE.items()],
    },
    "children": {
        "survey_variable": " / ".join(CHILD_FEATURES),
        "label": "Children in your household",
        # A checkbox group rather than a single choice: each entry names the API
        # field to set true, so the UI can render one toggle per age band.
        "control": "checkbox",
        "options": [
            {"code": 1, "label": CHILD_AGE_LABELS[column], "field": field}
            for field, column in CHILD_INPUT_FIELDS.items()
        ],
    },
}

#: Plain-language statement of what the model is and is not. Surfaced verbatim in
#: the API and the UI.
WHAT_THIS_IS = (
    "This is a pattern found in survey data, not a prediction about you. Among "
    "6,394 households in the 2016 CFPB National Financial Well-Being Survey, "
    "certain household characteristics were associated with at least one person "
    "receiving SNAP food benefits. We use that association as a rough proxy for "
    "how stretched a household's finances are."
)

WHAT_THIS_IS_NOT = [
    "It does not predict what taking out a loan would do to your finances.",
    "It does not estimate whether you would qualify for SNAP.",
    "It does not predict that you personally would receive SNAP.",
    "It says nothing about any lender, and it does not change any CFPB Safety Label score.",
]

# ---------------------------------------------------------------------------
# Artifact loading
# ---------------------------------------------------------------------------

_booster: xgb.Booster | None = None
_reference: dict[str, Any] | None = None


def load_model(path: Path = MODEL_PATH) -> xgb.Booster:
    """Load and cache the pre-trained booster. No scikit-learn involved."""
    global _booster
    if _booster is None:
        if not path.exists():
            raise FileNotFoundError(_MISSING_MODEL_MESSAGE)
        booster = xgb.Booster()
        booster.load_model(str(path))
        _booster = booster
    return _booster


def load_reference(path: Path = CONTEXT_PATH) -> dict[str, Any]:
    """Load and cache the codebook metadata and survey reference distribution."""
    global _reference
    if _reference is None:
        if not path.exists():
            raise FileNotFoundError(_MISSING_CONTEXT_MESSAGE)
        _reference = json.loads(path.read_text(encoding="utf-8"))
    return _reference


def model_artifact_loaded() -> bool:
    """Cheap liveness probe for the health endpoint. Does not run inference."""
    try:
        load_model()
        load_reference()
    except FileNotFoundError:
        return False
    return True


def reset_cache() -> None:
    """Drop cached artifacts. Used by tests."""
    global _booster, _reference
    _booster = None
    _reference = None


# ---------------------------------------------------------------------------
# Feature construction
# ---------------------------------------------------------------------------


def build_feature_frame(inputs: dict[str, Any]) -> pd.DataFrame:
    """Turn validated consumer inputs into the nine-column model matrix.

    ``inputs`` uses the API's plain-language field names. ``total_children`` and
    ``child_ratio`` are derived exactly as upstream does it, so the feature
    engineering is unchanged.
    """
    child_flags = [
        1 if inputs.get(field) else 0 for field in CHILD_INPUT_FIELDS
    ]
    total_children = sum(child_flags)
    household_size = int(inputs["household_size"])

    row: dict[str, Any] = {
        "agecat": int(inputs["age_band"]),
        "PPEDUC": int(inputs["education"]),
        "PPINCIMP": int(inputs["household_income"]),
        "PPMARIT": int(inputs["marital_status"]),
        "PPMSACAT": int(inputs["metro_area"]),
        "PPHHSIZE": household_size,
        "total_children": total_children,
        "child_ratio": float(total_children / household_size),
        "PCTLT200FPL": int(inputs["county_poverty_share"]),
    }
    frame = pd.DataFrame({name: [row[name]] for name in FEATURES})
    # Cast with the full codebook category set. A bare astype("category") on a
    # one-row frame would renumber every category from zero and silently route
    # the prediction through the wrong branches. See
    # CATEGORICAL_CATEGORIES.
    for name in CATEGORICAL_FEATURES:
        frame[name] = pd.Categorical(
            frame[name], categories=CATEGORICAL_CATEGORIES[name]
        )
    return frame


def association_rate(inputs: dict[str, Any]) -> float:
    """The model's own probability for this household profile.

    Preserved verbatim for traceability. This number is a model association
    measured against a 2016 survey, and on its own it is easy to over-read as a
    personal forecast, so :func:`household_context` frames it comparatively
    rather than presenting it as the headline.
    """
    frame = build_feature_frame(inputs)
    booster = load_model()
    matrix = xgb.DMatrix(frame, enable_categorical=True)
    return float(booster.predict(matrix)[0])


# ---------------------------------------------------------------------------
# Relative position within the survey population
# ---------------------------------------------------------------------------

#: Share of survey households at or below a given association rate.
_QUANTILE_FIELD = "reference_quantiles"


def _survey_percentile(rate: float, reference: dict[str, Any]) -> int:
    """Where this profile sits among the 6,232 modelled survey households.

    Uses the 0-100 quantile table produced offline, so the raw survey never
    ships with the service.
    """
    quantiles: list[float] = reference[_QUANTILE_FIELD]
    below = sum(1 for q in quantiles if q <= rate)
    return int(round(100.0 * below / len(quantiles)))


def _context_band(percentile: int) -> str:
    """Split into thirds of the survey distribution, not absolute thresholds."""
    if percentile >= 67:
        return "higher_strain"
    if percentile <= 33:
        return "lower_strain"
    return "typical_strain"


_BAND_LABELS = {
    "higher_strain": "Higher financial strain than most surveyed households",
    "typical_strain": "Typical financial strain among surveyed households",
    "lower_strain": "Lower financial strain than most surveyed households",
}

_BAND_SUMMARIES = {
    "higher_strain": (
        "Households with a profile like yours lined up with SNAP receipt more "
        "often than most of the surveyed households. Food assistance use is one "
        "signal of a tight budget, and tight budgets are where high-cost "
        "short-term credit does the most damage."
    ),
    "typical_strain": (
        "Households with a profile like yours lined up with SNAP receipt about "
        "as often as the middle of the surveyed households."
    ),
    "lower_strain": (
        "Households with a profile like yours lined up with SNAP receipt less "
        "often than most of the surveyed households. That is a relative "
        "comparison within one survey, not a sign that money is easy."
    ),
}


def household_context(inputs: dict[str, Any]) -> dict[str, Any]:
    """Assess a household profile against the survey population.

    Deliberately independent of the lender Safety Label: it takes no lender
    argument and returns nothing about lenders.
    """
    reference = load_reference()
    rate = association_rate(inputs)
    percentile = _survey_percentile(rate, reference)
    band = _context_band(percentile)

    return {
        "context_band": band,
        "band_label": _BAND_LABELS[band],
        "summary": _BAND_SUMMARIES[band],
        "survey_percentile": percentile,
        "model_association_rate": round(rate, 4),
        "what_this_is": WHAT_THIS_IS,
        "what_this_is_not": list(WHAT_THIS_IS_NOT),
        "methodology": {
            "survey": reference["survey"],
            "survey_year": reference["survey_year"],
            "households_modelled": reference["households_modelled"],
            "weighted_roc_auc": reference["weighted_roc_auc"],
            "target": reference["target"],
            "source_script": reference["source_script"],
            "relationship_to_safety_label": (
                "Independent. This assessment uses no lender data and has no "
                "effect on the CFPB Safety Label."
            ),
        },
        "caveats": list(reference["caveats"]),
    }


# The survey codebook, in one place, so a caller can enumerate the required
# fields without duplicating the list that validate_inputs enforces.
CODEBOOK_FIELDS: dict[str, Any] = {
    "age_band": AGE_BANDS,
    "education": EDUCATION_LEVELS,
    "household_income": INCOME_BANDS,
    "marital_status": MARITAL_STATUS,
    "household_size": HOUSEHOLD_SIZES,
    "metro_area": METRO_STATUS,
    "county_poverty_share": COUNTY_POVERTY_SHARE,
}


def validate_inputs(inputs: dict[str, Any]) -> None:
    """Reject codes that are not in the survey codebook.

    Raises ``ValueError`` naming the offending field, which FastAPI surfaces as
    a 422. Keeping the allowed values next to the labels means a codebook change
    cannot leave the API accepting codes the model was never trained on.
    """
    for field, codes in CODEBOOK_FIELDS.items():
        if field not in inputs:
            raise ValueError(f"'{field}' is required")
        try:
            value = int(inputs[field])
        except (TypeError, ValueError):
            raise ValueError(f"'{field}' must be an integer survey code") from None
        if value not in codes:
            raise ValueError(
                f"'{field}' must be one of {sorted(codes)}; got {value}"
            )
    for field in CHILD_INPUT_FIELDS:
        if not isinstance(inputs.get(field, False), bool):
            raise ValueError(f"'{field}' must be true or false")


def input_options() -> dict[str, Any]:
    """The codebook option lists, so the UI never hardcodes survey labels."""
    return {
        "inputs": INPUT_OPTIONS,
        "what_this_is": WHAT_THIS_IS,
        "what_this_is_not": list(WHAT_THIS_IS_NOT),
    }
