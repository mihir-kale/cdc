"""Compose the offer briefing.

This is the product's main output. A user arrives holding a real offer from a
real lender, pastes it, and gets three things in one place:

1. **What people report about this lender.** The observed complaint mix, so the
   user can anticipate the kinds of problem they are most likely to encounter.
2. **What they would actually be paying.** A full cost breakdown of the figures
   on the document, including the check that matters most: whether the stated
   rate agrees with the payments.
3. **Optionally, where their household sits in survey data.** Offered, not
   pushed, and labelled as a survey association rather than a prediction.

Each section is assembled from the same tools the tabs use, so the briefing
cannot disagree with the interface. Nothing here is generated: there is no model
in this module, which is why every figure in it is exactly a figure the analysis
produced. A model is layered on afterwards, in the orchestrator, and its output
is guarded.

The credit breakdown is worth spelling out. For a single-payment payday loan the
number that matters is the cost as a multiple of the amount borrowed, and the
annualised rate. For an instalment loan it is the total interest and the share
of every payment that is interest. Both are shown, because a user comparing
offers needs both and neither alone is honest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.chat import tools
from app.chat.offer import Offer, implied_apr, parse_offer
from app.payoff import estimate_payoff


@dataclass
class Section:
    """One part of the briefing."""

    key: str
    heading: str
    #: Rendered lines. Deliberately plain text, not HTML: the Streamlit tab and
    #: any future endpoint both consume this, and HTML in a data structure is how
    #: a formatting bug turns into an injection.
    lines: list[str] = field(default_factory=list)
    #: Figures this section asserts, so the guard can allow exactly these.
    numbers: list[float] = field(default_factory=list)
    #: True when the section has nothing to say, e.g. no lender matched.
    empty: bool = False
    note: str | None = None


@dataclass
class Briefing:
    """The composed answer to a pasted offer."""

    offer: Offer
    sections: list[Section] = field(default_factory=list)
    lender_name: str | None = None
    lender_id: str | None = None
    #: What we still need, phrased for the user.
    needs: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.needs

    def numbers(self) -> list[float]:
        out: list[float] = []
        for s in self.sections:
            out.extend(s.numbers)
        return out

    def as_text(self) -> str:
        """Flat text form, for the model and for tests."""
        parts = []
        for s in self.sections:
            if s.empty:
                continue
            parts.append(s.heading)
            parts.extend(f"  {line}" for line in s.lines)
            if s.note:
                parts.append(f"  {s.note}")
            parts.append("")
        return "\n".join(parts).strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "lender_name": self.lender_name,
            "lender_id": self.lender_id,
            "needs": list(self.needs),
            "complete": self.complete,
            "sections": [
                {
                    "key": s.key,
                    "heading": s.heading,
                    "lines": list(s.lines),
                    "numbers": list(s.numbers),
                    "empty": s.empty,
                    "note": s.note,
                }
                for s in self.sections
            ],
        }


# --------------------------------------------------------------------------
# Section 1: what people report about this lender
# --------------------------------------------------------------------------


def _complaints_section(text: str) -> tuple[Section, str | None, str | None]:
    matches = tools.match_lenders_in_text(text, limit=4)
    if not matches:
        return (
            Section(
                key="complaints",
                heading="What people report about this lender",
                empty=True,
            ),
            None,
            None,
        )
    if len(matches) > 1:
        return (
            Section(
                key="complaints",
                heading="What people report about this lender",
                lines=[
                    "Your text mentions more than one lender: "
                    + ", ".join(m["name"] for m in matches)
                    + ".",
                    "Tell me which one the offer is from and I will report that"
                    " lender's complaint pattern.",
                ],
                empty=True,
            ),
            None,
            None,
        )

    hit = matches[0]
    result = tools.call(tools.TOOL_LENDER, lender_id=hit["id"])
    if not result.get("ok"):
        return (
            Section(
                key="complaints",
                heading="What people report about this lender",
                lines=[f"Complaint data for {hit['name']} could not be read."],
                empty=True,
            ),
            None,
            None,
        )

    d = result["data"]
    lines = [
        f"{d['name']} has {d['n_complaints']} payday-loan complaints in this"
        f" dataset. That is {str(d['evidence']).lower()}.",
        "Share of this lender's complaints, largest first:",
    ]
    numbers: list[float] = [float(d["n_complaints"])]
    for c in d["categories"] + [d["other"]]:
        lines.append(f"  {c['category']}: {c['complaints']} ({c['share']}%)")
        numbers.extend([float(c["complaints"]), float(c["share"])])

    # The category most likely to bite this specific user, with its own wording.
    guidance = [
        g for g in d["guidance"] if g.get("what_to_check") and g["category"]
    ]
    top = d["categories"][0] if d["categories"] else None
    note = None
    if top and guidance:
        match = next(
            (g for g in guidance if g["category"] == top["category"]), None
        )
        if match:
            # The label's own casing: "fees & costs" reads as a typo next to the
            # properly cased category list above it.
            note = (
                f"On {top['category']}, which is the largest share here, "
                f"consumers reported: {match['consumers_reported']} "
                f"Worth checking: {match['what_to_check']}"
            )

    return (
        Section(
            key="complaints",
            heading="What people report about this lender",
            lines=lines,
            numbers=numbers,
            note=note,
        ),
        d["name"],
        hit["id"],
    )


# --------------------------------------------------------------------------
# Section 2: what they would be paying
# --------------------------------------------------------------------------


def _cost_section(offer: Offer) -> Section:
    heading = "What you would be paying"
    if not offer.usable:
        return Section(
            key="cost",
            heading=heading,
            lines=[
                "I could not read enough of the offer to cost it out. I need at"
                " least the loan amount, plus either a rate, a payment schedule"
                " or a finance charge.",
            ],
            empty=True,
        )

    lines: list[str] = []
    numbers: list[float] = []
    P = float(offer.principal or 0.0)
    F = offer.finance_charge
    T = offer.total_repayment

    if P > 0 and F is not None and F > 0:
        lines.append(
            f"Borrow ${P:,.2f}, repay ${F:,.2f} in charges, ${P + F:,.2f} in"
            f" total. That is {F / P * 100:.1f}% of the amount borrowed."
        )
        numbers.extend([P, F, P + F, round(F / P * 100, 1)])
    if T is not None and P > 0:
        lines.append(f"Total repayment on the offer: ${T:,.2f}.")
        numbers.append(T)

    # Term.
    if offer.term_days:
        lines.append(f"Term: {offer.term_days} days.")
        numbers.append(float(offer.term_days))
    elif offer.term_months:
        lines.append(f"Term: {offer.term_months} months.")
        numbers.append(float(offer.term_months))

    # The rate, and whether the document agrees with itself.
    stated = offer.apr
    derived = None
    if offer.payment and offer.payment_count and offer.payment_count > 1:
        derived = implied_apr(P, float(offer.payment), offer.payment_count)
    if stated is None and derived is not None:
        stated = derived

    if stated is not None:
        lines.append(f"Annual percentage rate: {stated:g}%.")
        numbers.append(float(stated))
    if derived is not None and stated is not None and abs(derived - stated) > 1.0:
        lines.append(
            f"Check this: the payments on the offer work out to about"
            f" {derived:g}% APR, not the {stated:g}% stated. The figure on the"
            " document and the figure implied by the payments do not match."
        )
        numbers.append(float(derived))
    elif stated is not None and F is not None and P > 0 and offer.term_days:
        # Classic single-payment check: cost per $100 borrowed.
        lines.append(
            f"That is ${F / P * 100:,.2f} in charges for every $100 borrowed."
        )

    # The debt-trap case, from the shared arithmetic.
    if offer.payment and P > 0 and stated is not None:
        est = estimate_payoff(P, float(stated), float(offer.payment))
        if est.status == "interest_not_covered":
            lines.append(
                f"Warning: a ${offer.payment:,.2f} payment does not cover the"
                f" ${est.monthly_interest:,.2f} of interest accruing each month at"
                f" {stated:g}%. The balance would grow rather than shrink."
            )
            numbers.extend([float(offer.payment), est.monthly_interest])
        elif est.ok and offer.payment_count and est.months > 1:
            lines.append(
                f"Paying ${offer.payment:,.2f} a month retires this in about"
                f" {est.months} months, of which ${est.total_interest:,.2f} is"
                f" interest ({est.interest_share:.1f}% of everything you pay)."
            )
            numbers.extend(
                [
                    float(est.months),
                    est.total_interest,
                    round(est.interest_share, 1),
                ]
            )

    for w in offer.warnings:
        lines.append(f"Note: {w}.")

    return Section(key="cost", heading=heading, lines=lines, numbers=numbers)


# --------------------------------------------------------------------------
# Section 3: the optional household section
# --------------------------------------------------------------------------


def _household_section(profile: dict[str, Any] | None) -> Section:
    heading = "Where households like yours sit in survey data"
    if not profile:
        return Section(
            key="household",
            heading=heading,
            lines=[
                "You can fill in the Household Financial Context tab to see this.",
            ],
            empty=True,
        )
    result = tools.call(tools.TOOL_HOUSEHOLD, profile=profile)
    if not result.get("ok"):
        return Section(
            key="household",
            heading=heading,
            lines=[f"That section could not be read: {result.get('error')}"],
            empty=True,
        )
    d = result["data"]
    lines = [
        f"Households with a profile like yours sit in the"
        f" {str(d.get('band_label', '')).lower()}, at the"
        f" {d.get('survey_percentile')}th percentile of the survey reference"
        " distribution.",
    ]
    numbers = [float(d.get("survey_percentile") or 0)]
    return Section(
        key="household",
        heading=heading,
        lines=lines,
        numbers=numbers,
        # Carried verbatim from the model, and asserted by the backend tests.
        # This is a survey association. It is not a prediction about this
        # household, and it is not a risk score for this loan.
        note=(
            "This is a pattern found in survey data, not a prediction about"
            " you, and it says nothing about whether this particular loan would"
            " help or harm you. It does not estimate SNAP eligibility."
        ),
    )


# --------------------------------------------------------------------------


def build_briefing(
    text: str,
    household_profile: dict[str, Any] | None = None,
    *,
    include_household: bool = False,
) -> Briefing:
    """Parse the offer and compose all three sections."""
    offer = parse_offer(text)
    complaints, lender_name, lender_id = _complaints_section(offer.raw_text)
    cost = _cost_section(offer)
    household = (
        _household_section(household_profile)
        if include_household
        else Section(
            key="household",
            heading="Where households like yours sit in survey data",
            lines=[
                "Ask for this and I will add it, using the profile you have set"
                " on the Household Financial Context tab.",
            ],
            empty=True,
        )
    )

    needs = list(offer.missing)
    if lender_name is None and offer.raw_text:
        needs.append("the lender's name, so I can report their complaint pattern")

    return Briefing(
        offer=offer,
        sections=[complaints, cost, household],
        lender_name=lender_name,
        lender_id=lender_id,
        needs=needs,
    )
