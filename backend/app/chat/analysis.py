"""The analysis box attached to each panel.

Each of the three tool panels carries one of these: a short passage written for
that panel specifically, about the data that panel is showing and nothing else.
This is the whole point of the two-panel layout. The query box decides which
panels open; the panels display; the analysis explains the display. There is no
free-form answer surface, so there is nowhere for the model to drift into
unsolicited advice about whether to take the loan.

Each analysis states its own limit, because the limit differs by panel and
carrying the right one matters:

* the lender panel is a complaint pattern, not a verdict on the lender, and is
  never a grade or an overall score;
* the payoff panel is standard amortisation on fixed terms, and real loans vary
  rate, add fees and get missed;
* the household panel is a survey association, not a prediction about the person
  reading it and not an eligibility estimate.

As with the lender narrative, the model writes the prose and the deterministic
text is the floor, with the guard deciding which is shown. A panel never renders
a model passage that grades a lender, invents a figure, or omits its limit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.chat import guard
from app.chat.model import ChatModel, Turn
from app.chat.narrative import _clause, guard_html_escape

# The limit each panel must state. The guard requires the first, the payoff
# panel's model is asked for its own, and the household one is fixed because it
# is the model's own documentation.
LENDER_LIMIT = (
    "This is a complaint pattern, not a grade. There is no overall score for a "
    "lender, and a lender with more complaints is not a worse lender."
)
PAYOFF_LIMIT = (
    "This is standard amortisation on a fixed rate and a level monthly payment. "
    "Real loans vary: a rate change, a fee, or a missed payment changes the "
    "answer. It is an estimate of the arithmetic, not advice about the loan."
)
HOUSEHOLD_LIMIT = (
    "This is a pattern found in survey data. It is not a prediction about you, "
    "it does not estimate SNAP eligibility, and it says nothing about this loan "
    "or this lender."
)

SYSTEM = """You are writing the short analysis shown beside one panel in \
Know Your Loan, which analyses CFPB consumer complaint data about payday \
lenders.

You are given the figures that panel is displaying. Write two or three plain \
sentences explaining what they mean for someone reading that panel. Be specific \
to the numbers you were given.

Hard limits. These are not stylistic preferences:
- Never say a lender is safe, unsafe, a scam, trustworthy, risky or predatory.
- Never rank lenders, and never give a risk score or a credit score.
- Never tell anyone whether to borrow, take a loan, or apply for credit.
- Report only figures you were given. Do not compute new ones and do not turn
  them into a judgement.
- If the figures cannot distinguish something, say so rather than implying a
  difference.
- End by stating the limit given to you, in your own words.

No headings, no bullet points, no preamble."""


@dataclass
class Analysis:
    """One panel's analysis passage."""

    text: str
    generated: bool
    #: The limit shown under the passage, always present.
    limit: str
    fallback_reason: str | None = None

    def as_html(self) -> str:
        return (
            '<div class="kyl-analysis">'
            '<p class="kyl-analysis-head">What this means</p>'
            f'<p class="kyl-note">{guard_html_escape(self.text)}</p>'
            f'<p class="kyl-fine">{guard_html_escape(self.limit)}</p>'
            "</div>"
        )


# --------------------------------------------------------------------------
# Floors
# --------------------------------------------------------------------------


def _floor_text(kind: str, facts: dict[str, Any]) -> str:
    if kind == "lender":
        name = facts.get("name", "this lender")
        total = facts.get("n_complaints", 0)
        if not total:
            return (
                f"There are no complaints on record for {name} in this dataset, "
                "so there is no pattern here to read."
            )
        top = facts.get("top_category")
        share = facts.get("top_share")
        line = (
            f"{name} has {total} payday-loan complaints in this dataset. "
            f"The largest category is {top}"
        )
        if share is not None:
            line += f", at {share:.1f}% of those complaints"
        line += "."
        guidance = facts.get("top_guidance")
        if guidance:
            # _clause strips the guidance's own leading "Check", which the
            # sentence already supplies.
            line += f" Worth checking: {_clause(guidance)}"
        return line
    if kind == "payoff":
        parts = []
        principal = facts.get("principal")
        total = facts.get("total_repayment")
        months = facts.get("months")
        interest = facts.get("total_interest")
        if principal:
            parts.append(f"borrowing ${principal:,.2f}")
        if total:
            parts.append(f"repaying ${total:,.2f} in total")
        if months:
            parts.append(
                f"over about {months} month{'s' if months != 1 else ''}"
            )
        if interest is not None:
            parts.append(f"of which ${interest:,.2f} is interest")
        if not parts:
            return (
                "There are not enough figures here to work out what the loan "
                "would cost. An amount and a rate, or a payment schedule, are "
                "needed."
            )
        return (
            "On the figures given, that is " + ", ".join(parts) + "."
        )
    band = facts.get("band_label")
    pct = facts.get("percentile")
    if not band:
        return (
            "Not enough of a household profile was given to place it against the "
            "survey data."
        )
    return (
        f"Households with a profile like yours sit in the {str(band).lower()}, at "
        f"the {pct}th percentile of the survey reference distribution."
    )


# --------------------------------------------------------------------------


def _sanctioned(kind: str, facts: dict[str, Any]) -> list[float]:
    out: list[float] = []
    for key, value in facts.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        out.append(float(value))
    return out


def build_analysis(
    kind: str,
    facts: dict[str, Any],
    *,
    model: ChatModel | None = None,
    limit: str | None = None,
) -> Analysis:
    """The analysis passage for one panel, model-written or the floor.

    ``kind`` is "lender", "payoff" or "household" and decides both the limit and
    the floor wording.
    """
    if kind == "lender":
        default_limit = LENDER_LIMIT
    elif kind == "payoff":
        default_limit = PAYOFF_LIMIT
    else:
        default_limit = HOUSEHOLD_LIMIT
    lim = limit or default_limit
    floor = _floor_text(kind, facts)

    if model is None:
        return Analysis(text=floor, generated=False, limit=lim)

    lines = [f"{k}: {v}" for k, v in facts.items() if v not in (None, "", [])]
    try:
        raw = model.complete(
            [
                Turn(role="system", content=SYSTEM),
                Turn(
                    role="user",
                    content=(
                        f"Panel: {kind}\n"
                        f"The limit you must state: {lim}\n"
                        f"Figures shown in this panel:\n" + "\n".join(lines)
                    ),
                ),
            ],
            [],
        )
    except Exception as exc:
        return Analysis(
            text=floor,
            generated=False,
            limit=lim,
            fallback_reason=f"model call failed: {exc}",
        )

    text = (raw or "").strip()
    if not text:
        return Analysis(
            text=floor, generated=False, limit=lim, fallback_reason="model returned nothing"
        )

    checked = guard.check_reply(
        text,
        ["\n".join(lines)],
        sanctioned_numbers=_sanctioned(kind, facts),
        require_no_grade_disclosure=(kind == "lender"),
    )
    if not checked.ok:
        return Analysis(
            text=floor,
            generated=False,
            limit=lim,
            fallback_reason=",".join(checked.violations),
        )
    return Analysis(text=checked.text, generated=True, limit=lim)
