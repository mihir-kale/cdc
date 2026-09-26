from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app import label_store
from app.models import LenderSummary, SafetyLabel

app = FastAPI(
    title="FinePrint API",
    description="Backend for the FinePrint payday lender safety label.",
    version="0.2.0",
)

# The Next.js dev server runs on port 3000 and the API on port 8000.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "FinePrint API",
        "version": "0.2.0",
        "docs": "/docs",
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
