import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import financial_impact, label_store
from app.models import (
    HouseholdContext,
    HouseholdInputOptions,
    HouseholdProfile,
    LenderSummary,
    SafetyLabel,
)

app = FastAPI(
    title="FinePrint API",
    description=(
        "Backend for FinePrint: the CFPB lender Safety Label and the household "
        "financial context assessment. The two are independent."
    ),
    version="0.3.0",
)

# Comma-separated list of allowed browser origins. Defaults to the local Next.js
# dev server so `uvicorn app.main:app` works with no configuration; set
# FINEPRINT_ALLOWED_ORIGINS to the deployed frontend origin in production.
_allowed_origins = [
    origin.strip()
    for origin in os.environ.get("FINEPRINT_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
] or [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "FinePrint API",
        "version": "0.3.0",
        "docs": "/docs",
    }


@app.get("/health")
def health() -> dict[str, object]:
    """Liveness plus a cheap check that both committed artifacts are readable.

    Loads the artifacts but never runs inference or retrains anything, so this
    stays fast enough for a platform health check.
    """
    safety_label_loaded = True
    try:
        label_store.load_artifact()
    except FileNotFoundError:
        safety_label_loaded = False

    context_loaded = financial_impact.model_artifact_loaded()

    healthy = safety_label_loaded and context_loaded
    payload: dict[str, object] = {
        "status": "ok" if healthy else "degraded",
        "artifacts": {
            "lender_safety_labels": safety_label_loaded,
            "financial_impact_model": context_loaded,
        },
    }
    if not healthy:
        # Surfaced as 503 so a platform restarts or alerts rather than serving
        # a half-working app.
        raise HTTPException(status_code=503, detail=payload)
    return payload


@app.get("/dataset")
def dataset() -> dict[str, object]:
    """Dataset size and the methodology text the UI discloses."""
    return label_store.dataset_summary()


@app.get("/lenders", response_model=list[LenderSummary])
def list_lenders() -> list[dict[str, object]]:
    """Every canonical payday lender, for search.

    Returns all lenders including low-volume ones; nothing is filtered out for
    having few complaints.
    """
    return label_store.lender_index()


@app.get("/lenders/{lender_id}", response_model=SafetyLabel)
def get_lender(lender_id: str) -> dict[str, object]:
    lender = label_store.get_lender(lender_id)
    if lender is None:
        raise HTTPException(status_code=404, detail=f"Lender '{lender_id}' not found")
    return lender


# ---------------------------------------------------------------------------
# Household Financial Context
#
# A separate question from the Safety Label above: not "is this lender risky"
# but "what does a household like mine look like in survey terms". No lender
# identifier is accepted here, and no CFPB score is read or returned.
# ---------------------------------------------------------------------------


@app.get("/financial-impact/inputs", response_model=HouseholdInputOptions)
def financial_impact_inputs() -> dict[str, object]:
    """Survey codebook for the household inputs, so the UI needs no hardcoded labels."""
    return financial_impact.input_options()


@app.post("/financial-impact/context", response_model=HouseholdContext)
def household_context(profile: HouseholdProfile) -> dict[str, object]:
    """Place a household profile within the survey population.

    Returns a relative position, not a personal forecast: the result says where
    households with these answers lined up in a 2016 survey, and is not a
    prediction that the person asking will receive SNAP benefits or that a loan
    will affect them in any way.
    """
    inputs = profile.model_dump()
    try:
        financial_impact.validate_inputs(inputs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        return financial_impact.household_context(inputs)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
