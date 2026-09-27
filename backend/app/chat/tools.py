"""The closed toolset the assistant is allowed to reach.

Four tools, wrapping the four things the product can actually compute. The
assistant has no other capability: it cannot read files, run code, or query the
complaint dataset directly. That constraint is the security boundary, and it is
also what makes the answers trustworthy, because every number in a reply came out
of one of these functions.

Each tool returns a dict with a ``tool`` name and an ``ok`` flag. Failures are
returned, not raised, so a bad argument becomes a message the model can explain
rather than a 500.

Provenance matters here more than usual. Every tool result carries
``allowed_claims``: the specific statements the assistant is permitted to make
from it. The output guard checks the reply against exactly that list, which is
what stops "this lender looks safer than most" appearing in a reply whose only
evidence was a complaint count.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from app import financial_impact, label_store
from app.payoff import estimate_payoff

TOOL_LENDER = "get_lender_complaints"
TOOL_HOUSEHOLD = "get_household_context"
TOOL_PAYOFF = "estimate_payoff"
TOOL_METHOD = "get_methodology"
TOOL_LOOKUP = "find_lenders"

# The verbatim refusals, so the wording lives in one place and is testable.
# Each one names what the product can do instead, because a bare "no" is a dead
# end for the user.
REFUSALS: dict[str, str] = {
    "lender_verdict": (
        "I can't say whether a lender is safe. What I can show is what consumers "
        "reported to the CFPB about that lender, and how that compares with "
        "modeled payday-loan peers. Those are complaint patterns, not a verdict "
        "on the lender."
    ),
    "lender_ranking": (
        "I can't rank the lenders. Complaint volume mostly reflects how many "
        "complaints a lender generated, and FinePrint has no customer or "
        "loan-volume denominators, so a lender with more complaints is not "
        "necessarily a worse lender. I can compare two specific lenders' "
        "complaint patterns if you tell me which."
    ),
    "financial_advice": (
        "I can't give financial advice, including whether you should borrow. "
        "I can calculate what a specific loan would cost, and I can show where a "
        "household profile sits in survey data, but the decision is yours."
    ),
    "out_of_domain": (
        "I can only answer questions about this analysis: what consumers reported "
        "about a payday lender, what the peer comparisons and evidence levels "
        "mean, what a loan would cost to repay, and where a household profile "
        "sits in the survey data."
    ),
}


# Declared here, registered with the guard on import, so the refusal wording the
# scope gate returns is exempt from the guard's own patterns.
from app.chat import guard as _guard  # noqa: E402

_guard.register_system_texts(set(REFUSALS.values()) | {
    _guard.RANKING_REFUSAL,
    _guard.VERDICT_REFUSAL,
    _guard.SCORE_REFUSAL,
    "I don't have a figure for that in the data I retrieved, so I would "
    "rather not guess. Ask me about a specific lender's complaint pattern, a "
    "loan's payoff, or what the peer comparison means.",
})


def _result(tool: str, payload: dict[str, Any], claims: list[str]) -> dict[str, Any]:
    return {
        "tool": tool,
        "ok": True,
        "claims": claims,
        "data": payload,
    }


def _error(tool: str, message: str) -> dict[str, Any]:
    return {"tool": tool, "ok": False, "error": message, "claims": [], "data": {}}


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------


# Legal and entity suffixes carry no identifying information, and dropping them
# is what lets "Uprova Credit, LLC" be found inside the sentence "Uprova Credit
# complaints", where the full name is not a substring.
_ENTITY_SUFFIXES = {
    "llc", "l l c", "inc", "incorporated", "corp", "corporation", "co",
    "company", "ltd", "limited", "llp", "lp", "plc", "pc", "the", "and",
}
_PUNCT = re.compile(r"[^a-z0-9\s]+")
_WS = re.compile(r"\s+")


def normalise_name(name: str) -> str:
    """Lowercase, strip punctuation, drop trailing entity suffixes."""
    cleaned = _WS.sub(" ", _PUNCT.sub(" ", (name or "").lower())).strip()
    tokens = [t for t in cleaned.split() if t and t not in _ENTITY_SUFFIXES]
    return " ".join(tokens)


def find_lenders(query: str = "", limit: int = 8) -> dict[str, Any]:
    """Look up lender ids by name. The only way to resolve a name to an id."""
    try:
        index = label_store.lender_index()
    except (FileNotFoundError, ValueError) as exc:
        return _error(TOOL_LOOKUP, f"complaint data unavailable: {exc}")

    needle = (query or "").strip().lower()
    hits = [r for r in index if needle in r["name"].lower()] if needle else []
    hits.sort(key=lambda r: (not r["name"].lower().startswith(needle), r["name"]))
    shown = [
        {
            "id": r["id"],
            "name": r["name"],
            "n_complaints": r["n_complaints"],
            "evidence": r["evidence"],
        }
        for r in hits[: max(1, min(int(limit), 25))]
    ]
    return _result(
        TOOL_LOOKUP,
        {"query": query, "match_count": len(hits), "lenders": shown},
        [
            f"{len(hits)} lender name(s) match {query!r}."
            if needle
            else "No name filter was applied.",
        ],
    )


def match_lenders_in_text(text: str, limit: int = 6) -> list[dict[str, Any]]:
    """Find lenders named anywhere in a free-text message.

    Matching runs from the dataset towards the message, not the other way round.
    The obvious approach, testing whether the message is a substring of a lender
    name, fails for every question phrased as a sentence: "Uprova Credit
    complaints" is not a substring of "Uprova Credit, LLC". Testing whether the
    *name* is a substring of the message works for both a bare name and a
    sentence, which is the case that actually occurs.

    Longest name wins, so "Advance America" is preferred over a shorter lender
    whose name happens to appear inside it.
    """
    try:
        index = label_store.lender_index()
    except (FileNotFoundError, ValueError):
        return []
    haystack = " ".join(_PUNCT.sub(" ", (text or "").lower()).split())
    if not haystack:
        return []

    scored: list[tuple[int, dict[str, Any]]] = []
    for row in index:
        norm = normalise_name(row["name"])
        # A one- or two-character name would match almost any sentence.
        if len(norm) < 4:
            continue
        # Try the full normalised name, then its leading two tokens. Real names
        # are long: "Advance America, Cash Advance Centers, Inc." normalises to
        # "advance america cash advance centers", which no one types, but
        # "Advance America" is how it is referred to. Matching is on word
        # boundaries so "advance" does not fire inside "advanced".
        head = " ".join(norm.split()[:2])
        for key in (norm, head):
            if len(key) < 4:
                continue
            if re.search(rf"\b{re.escape(key)}\b", haystack):
                scored.append((len(key), row))
                break
    scored.sort(key=lambda pair: (-pair[0], pair[1]["name"]))
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "n_complaints": r["n_complaints"],
            "evidence": r["evidence"],
        }
        for _, r in scored[:limit]
    ]


def get_lender_complaints(lender_id: str) -> dict[str, Any]:
    """Observed complaint mix for one lender, plus evidence and peer context."""
    try:
        label = label_store.get_lender(str(lender_id))
    except (FileNotFoundError, ValueError) as exc:
        return _error(TOOL_LENDER, f"complaint data unavailable: {exc}")
    if label is None:
        return _error(TOOL_LENDER, f"no lender with id {lender_id!r}")

    dims = label.get("dimensions", {})
    other = label.get("other", {})
    scored = [
        {
            "category": d.get("label", slug),
            "complaints": int(d.get("complaints", 0)),
            "share": round(float(d.get("share", 0.0)) * 100, 1),
            "peer_comparison": d.get("comparison", "similar"),
            "issues": [
                {"issue": i, "complaints": int(n)} for i, n in d.get("issues", [])
            ],
        }
        for slug, d in dims.items()
    ]
    scored.sort(key=lambda r: r["complaints"], reverse=True)
    other_row = {
        "category": other.get("label", "Other reported issues"),
        "complaints": int(other.get("complaints", 0)),
        "share": round(float(other.get("share", 0.0)) * 100, 1),
        "peer_comparison": "not modelled",
        "issues": [{"issue": i, "complaints": int(n)} for i, n in other.get("issues", [])],
    }

    guidance = [
        {
            "category": d.get("label", slug),
            "consumers_reported": d.get("consumers_reported", ""),
            "what_to_check": d.get("what_to_inspect", ""),
        }
        for slug, d in dims.items()
    ]

    return _result(
        TOOL_LENDER,
        {
            "id": label["id"],
            "name": label["name"],
            "n_complaints": label["n_complaints"],
            "evidence": label["evidence"],
            "denominator_note": label.get("complaint_share_note", ""),
            "categories": scored,
            "other": other_row,
            "guidance": guidance,
        },
        [
            f"{label['name']} has {label['n_complaints']} payday-loan complaints "
            f"in this dataset, which is {label['evidence'].lower()}.",
            "Shares are of this lender's complaints in the dataset and are not a "
            "rate per customer.",
        ],
    )


def get_household_context(profile: dict[str, Any] | None = None, **fields: Any) -> dict[str, Any]:
    """Survey-association context band for a household profile.

    Accepts the survey codes either as a ``profile`` dict or as keyword fields,
    because a model emits the flat form. Every code is validated against the
    codebook before scoring, so an invented code is refused rather than silently
    coerced.

    This is an association with national survey patterns, not an eligibility
    determination and not a prediction about any individual. The distinction is
    carried in the payload as ``what_this_is`` / ``what_this_is_not`` so the
    assistant describes it correctly without having to remember to.
    """
    inputs: dict[str, Any] = dict(profile or {})
    inputs.update(fields)
    if not inputs:
        return _error(
            TOOL_HOUSEHOLD,
            "a household profile is required: "
            f"{sorted(financial_impact.CODEBOOK_FIELDS)}",
        )

    try:
        financial_impact.validate_inputs(inputs)
        result = financial_impact.household_context(inputs)
    except (KeyError, ValueError) as exc:
        return _error(TOOL_HOUSEHOLD, f"invalid household profile: {exc}")

    return _result(
        TOOL_HOUSEHOLD,
        {
            "context_band": result.get("context_band"),
            "band_label": result.get("band_label"),
            "survey_percentile": result.get("survey_percentile"),
            "model_association_rate": result.get("model_association_rate"),
            "summary": result.get("summary"),
            "what_this_is": result.get("what_this_is"),
            "what_this_is_not": result.get("what_this_is_not", []),
        },
        [
            f"This profile sits in the {result.get('band_label')} band, at the "
            f"{result.get('survey_percentile')}th percentile of the survey "
            "reference distribution.",
            "This is a survey association. It does not predict what taking out a "
            "loan would do, and it does not estimate SNAP eligibility.",
        ],
    )


def estimate_payoff_tool(
    principal: float, apr: float, payment: float
) -> dict[str, Any]:
    """Standard amortisation estimate, including the debt-trap refusal."""
    try:
        r = estimate_payoff(float(principal), float(apr), float(payment))
    except (TypeError, ValueError) as exc:
        return _error(TOOL_PAYOFF, f"invalid loan figures: {exc}")

    if r.status == "invalid_payment":
        return _error(TOOL_PAYOFF, "the monthly payment must be greater than zero")

    if r.status == "interest_not_covered":
        return {
            "tool": TOOL_PAYOFF,
            "ok": True,
            # A refusal, not an estimate. No payoff time is reported, and the
            # guard forbids the assistant from inventing one.
            "refused": True,
            "claims": [
                f"At ${r.payment:,.2f} a month the payment does not cover the "
                f"${r.monthly_interest:,.2f} of interest accruing each month, so "
                "the balance grows rather than shrinking."
            ],
            "data": r.to_dict(),
        }

    return _result(
        TOOL_PAYOFF,
        r.to_dict(),
        [
            f"At ${r.payment:,.2f} a month this loan takes {r.months} months "
            f"(about {r.years} years) to repay.",
            f"Total interest is ${r.total_interest:,.2f}, which is "
            f"{r.interest_share:.1f}% of everything paid.",
        ],
    )


def get_methodology() -> dict[str, Any]:
    """Method, disclosures and caveats. The source for "how does this work"."""
    try:
        summary = label_store.dataset_summary()
    except (FileNotFoundError, ValueError) as exc:
        return _error(TOOL_METHOD, f"methodology unavailable: {exc}")

    return _result(
        TOOL_METHOD,
        {
            "method": summary.get("method"),
            "methodology": summary.get("methodology"),
            "lender_count": summary.get("lender_count"),
            "total_complaints": summary.get("total_complaints"),
        },
        [
            f"The method is {summary.get('method')}.",
            "FinePrint publishes no overall lender score and does not rank lenders.",
        ],
    )


TOOLS: dict[str, Callable[..., dict[str, Any]]] = {
    TOOL_LOOKUP: find_lenders,
    TOOL_LENDER: get_lender_complaints,
    TOOL_HOUSEHOLD: get_household_context,
    TOOL_PAYOFF: estimate_payoff_tool,
    TOOL_METHOD: get_methodology,
}

# Sent to the model so it knows what it may call. The assistant's capabilities
# are exactly this list; there is no other path to the data.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": TOOL_LOOKUP,
        "description": "Find lender ids by name. Use this first when a name is given.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Part of a lender name"},
                "limit": {"type": "integer", "description": "Max results, default 8"},
            },
        },
    },
    {
        "name": TOOL_LENDER,
        "description": "Observed CFPB complaint mix, evidence level and peer "
        "comparison for one lender id.",
        "parameters": {
            "type": "object",
            "properties": {"lender_id": {"type": "string"}},
            "required": ["lender_id"],
        },
    },
    {
        "name": TOOL_HOUSEHOLD,
        "description": "Survey-association context band for a household profile.",
        "parameters": {
            "type": "object",
            "properties": {
                "age_band": {"type": "integer"},
                "education": {"type": "integer"},
                "household_income": {"type": "integer"},
                "marital_status": {"type": "integer"},
                "household_size": {"type": "integer"},
                "metro_area": {"type": "integer"},
                "county_poverty_share": {"type": "integer"},
                "children_0_1": {"type": "boolean"},
                "children_2_5": {"type": "boolean"},
                "children_6_12": {"type": "boolean"},
                "children_13_17": {"type": "boolean"},
            },
            "required": [
                "age_band",
                "education",
                "household_income",
                "marital_status",
                "household_size",
                "metro_area",
                "county_poverty_share",
            ],
        },
    },
    {
        "name": TOOL_PAYOFF,
        "description": "Standard amortisation estimate for a loan.",
        "parameters": {
            "type": "object",
            "properties": {
                "principal": {"type": "number"},
                "apr": {"type": "number"},
                "payment": {"type": "number"},
            },
            "required": ["principal", "apr", "payment"],
        },
    },
    {"name": TOOL_METHOD, "description": "Method, disclosures and caveats.", "parameters": {"type": "object", "properties": {}}},
]


def call(name: str, **kwargs: Any) -> dict[str, Any]:
    """Invoke a tool by name. Unknown names are refused, not attempted."""
    fn = TOOLS.get(name)
    if fn is None:
        return _error(name, f"no such tool: {sorted(TOOLS)}")
    try:
        return fn(**kwargs)
    except TypeError as exc:
        return _error(name, f"bad arguments: {exc}")


def to_json(result: dict[str, Any]) -> str:
    """Serialise a tool result for the model. Truncated defensively."""
    blob = json.dumps(result, default=str)
    return blob if len(blob) <= 20_000 else blob[:20_000] + " …[truncated]"
