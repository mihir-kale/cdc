from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.data import LENDERS
from app.models import Lender

app = FastAPI(
    title="FinePrint API",
    description="Backend for the FinePrint payday lender comparison tool.",
    version="0.1.0",
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
        "version": "0.1.0",
        "docs": "/docs",
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/lenders", response_model=list[Lender])
def list_lenders() -> list[Lender]:
    return LENDERS


@app.get("/lenders/{lender_id}", response_model=Lender)
def get_lender(lender_id: str) -> Lender:
    for lender in LENDERS:
        if lender.id == lender_id:
            return lender
    raise HTTPException(status_code=404, detail=f"Lender '{lender_id}' not found")
