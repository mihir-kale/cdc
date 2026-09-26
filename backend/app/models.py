from pydantic import BaseModel, Field


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


# ---------------------------------------------------------------------------
# Household Financial Context
#
# Wholly separate from the Safety Label above. Nothing here reads a lender or
# influences a lender score; the two never appear in the same response.
# ---------------------------------------------------------------------------


class HouseholdProfile(BaseModel):
    """A household described in the CFPB Financial Well-Being Survey's terms.

    Every field is a survey code, validated against the official codebook by
    `app.financial_impact.validate_inputs`. All fields are required on purpose:
    this describes someone's actual household, so it is better to ask than to
    quietly assume a single adult with no children in a metro area.

    This is a description of a household, not a loan. There is deliberately no
    amount, rate, term or payment field.
    """

    age_band: int = Field(ge=1, le=8, description="Age: 1=18-24 ... 8=75+")
    education: int = Field(ge=1, le=5, description="1=less than high school ... 5=graduate")
    household_income: int = Field(ge=1, le=9, description="1=under $20,000 ... 9=$150,000+")
    marital_status: int = Field(ge=1, le=5, description="1=married ... 5=living with partner")
    household_size: int = Field(ge=1, le=5, description="1 ... 5 (5 means 5 or more)")
    metro_area: int = Field(ge=0, le=1, description="0=non-metro, 1=metro")
    county_poverty_share: int = Field(
        ge=-5, le=1, description="-5=county unknown, 0=under 40%, 1=40% or more"
    )
    children_0_1: bool = False
    children_2_5: bool = False
    children_6_12: bool = False
    children_13_17: bool = False


class HouseholdContextMethodology(BaseModel):
    survey: str
    survey_year: int
    households_modelled: int
    weighted_roc_auc: float
    target: str
    source_script: str
    relationship_to_safety_label: str


class HouseholdContext(BaseModel):
    """Where a household profile sits within the survey population.

    `survey_percentile` is the consumer-facing result: a relative position
    among surveyed households. `model_association_rate` is the underlying model
    probability, kept for traceability. It is not phrased as a personal
    forecast anywhere in the interface, because a 2016 survey association is
    easy to over-read as one.
    """

    context_band: str
    band_label: str
    summary: str
    survey_percentile: int
    model_association_rate: float
    what_this_is: str
    what_this_is_not: list[str]
    methodology: HouseholdContextMethodology
    caveats: list[str]


class InputOption(BaseModel):
    """One selectable value. `field` is present only for checkbox groups."""

    code: int
    label: str
    field: str | None = None


class InputField(BaseModel):
    survey_variable: str
    label: str
    control: str
    options: list[InputOption]


class HouseholdInputOptions(BaseModel):
    """The survey codebook, so the UI renders labels instead of hardcoding them."""

    inputs: dict[str, InputField]
    what_this_is: str
    what_this_is_not: list[str]
