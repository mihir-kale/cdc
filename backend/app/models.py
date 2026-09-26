from pydantic import BaseModel


class Evidence(BaseModel):
    """How much complaint data supports a lender's scores.

    This is a statement about data volume, not about the lender's quality.
    """

    label: str
    n_complaints: int


class LenderSummary(BaseModel):
    """Search-result row. Deliberately excludes the scores so the index stays small."""

    id: str
    name: str
    n_complaints: int
    evidence: str


class DimensionScore(BaseModel):
    """One dimension of the safety label for one lender.

    `score` is the Method C value on 0-100. The `prevalence` fields are the
    posterior complaint rate and its 90% credible interval, kept alongside the
    score so the interface can be honest about uncertainty.
    """

    label: str
    summary: str
    peer_rate: float
    score: float
    complaints: int
    prevalence: float
    prevalence_lo90: float
    prevalence_hi90: float
    comparison: str


class Methodology(BaseModel):
    direction: str
    summary: str
    caveats: list[str]
    evidence_bands: list[dict[str, object]]


class SafetyLabel(BaseModel):
    """FinePrint Payday Loan Safety Label for a single lender.

    There is deliberately no overall score, grade or rank: the five dimensions
    overlap, and combining them would hide that.
    """

    id: str
    name: str
    n_complaints: int
    evidence: str
    method: str
    methodology: Methodology
    dimensions: dict[str, DimensionScore]
