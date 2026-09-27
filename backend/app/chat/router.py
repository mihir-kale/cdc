"""Decide what a query is asking for, and which panels it should open.

The interface is two panels: a query box on the left, and four read-only
collapsibles on the right. This module is the join between them. A user types
whatever they have, which is rarely a complete question, and the router works
out what can be shown from it.

The partial cases are the point, not an edge case:

    "Uprova Credit"
        -> lender panel only

    "Uprova Credit, $300 at 391% for 14 days"
        -> lender and payoff panels

    "$300 at 391%, I'm 35-44, income 50-75k"
        -> payoff and household panels

Nothing is inferred that is not in the text. A panel opens only when the query
actually contains what that panel needs, so the interface never shows a figure
the user did not supply and never implies a comparison that was not asked for.
That restraint is what keeps the read-only panels honest: they display, they do
not speculate.

Demographics are the weak spot and are handled by explicit syntax rather than
inference. Guessing a household profile from prose would be both unreliable and
exactly the kind of quiet invention the rest of this design refuses, so the
recognised forms are narrow and listed in DEMOGRAPHIC_PATTERNS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.chat import tools
from app.chat.offer import Offer, parse_offer

PANEL_LENDER = "lender"
PANEL_PAYOFF = "payoff"
PANEL_HOUSEHOLD = "household"
PANEL_METHOD = "methodology"

PANELS = (PANEL_LENDER, PANEL_PAYOFF, PANEL_HOUSEHOLD, PANEL_METHOD)

# Survey codebook, restated here so the router can map a typed range onto the
# same codes the Household panel uses. These MUST track
# financial_impact.AGE_BANDS; tests/test_chat.py asserts the two agree.
#
# All eight bands are reachable, and each maps to a distinct code. An earlier
# version listed only six patterns: codes 7 ("70-74") and 8 ("75 or older") were
# unreachable, and "62-69" and "70-74" shared one pattern, so a household that
# said it was 72 was coded as 62-69 and the panel opened showing the wrong
# band. Ranges are still what is matched, as before -- a bare "I'm 35" has
# never resolved, and widening that is a separate decision.
AGE_RANGES: tuple[tuple[str, int], ...] = (
    # "20-24" belongs to this band too; the pattern previously only accepted a
    # range *starting* at 18 or 19, so the most obvious way to type the youngest
    # band did not resolve.
    (r"1[8-9]\s*-\s*2[0-4]|2[0-4]\s*-\s*2[0-4]|under\s*25|18-24|20-24", 1),
    (r"2[5-9]\s*-\s*3[0-4]", 2),
    (r"3[5-9]\s*-\s*4[0-4]", 3),
    (r"4[5-9]\s*-\s*5[0-9]|5[0-4]\s*-\s*5[0-9]", 4),
    (r"5[5-9]\s*-\s*6[0-1]|5[5-9]\s*-\s*5[0-9]", 5),
    (r"6[2-9]\s*-\s*6[0-9]", 6),
    (r"7[0-4]\s*-\s*7[0-4]", 7),
    (r"7[5-9]\s*-\s*[89][0-9]|8[0-9]\s*-\s*[89][0-9]|9[0-9]\s*-\s*[89][0-9]"
     r"|over\s*75|75\s*or\s*older", 8),
)
# One pattern per codebook band, tested from the top down, because the bands are
# identified by the leading digits of whichever income figure was typed.
#
# These were badly misaligned with financial_impact.INCOME_BANDS. The old set had
# seven patterns for nine bands, so "$75,000 to $99,999" and "$150,000 or more"
# were unreachable, and the ones that existed were shifted: "income 120k" was
# coded 6 ($60,000-$74,999) and "income 180k" was coded 8, neither of which is
# the band those numbers fall in.
INCOME_RANGES: tuple[tuple[str, int], ...] = (
    # "under 20k" is checked first, ahead of the 20k band itself: "under 20k"
    # contains "20k", and since the bands are tried top down, band 2 would
    # otherwise claim it and report a sub-$20,000 household as $20,000+.
    (r"(?:under|less\s+than)\s*\$?\s*(?:1[0-9]|20)(?:,?000|,?999|k)?\b", 1),
    (r"\$?\s*(?:1[5-9][0-9]|[2-9][0-9]{2})(?:,?000|k)\b|over\s*\$?\s*1[45]0|\b150s\b", 9),
    (r"\$?\s*1[0-4][0-9](?:,?000|k)\b|\b1[0-4]0s\b", 8),
    # ,999 as well as ,000: the band runs to $99,999, so a typed "99,999" has to
    # land here rather than fall through.
    (r"\$?\s*(?:7[5-9]|8[0-9]|9[0-9])(?:,?000|,?999|k)\b|\b[789]0s\b", 7),
    (r"\$?\s*(?:6[0-9]|7[0-4])(?:,?000|k)\b|\b60s\b", 6),
    (r"\$?\s*5[0-9](?:,?000|k)\b|\b50s\b", 5),
    (r"\$?\s*4[0-9](?:,?000|k)\b|\b40s\b", 4),
    (r"\$?\s*3[0-9](?:,?000|k)\b|\b30s\b", 3),
    (r"\$?\s*2[0-9](?:,?000|k)\b|\b20s\b", 2),
    (r"\$?\s*1[0-9](?:,?000|,?999|k)\b|\b1[0-9]k\b", 1),
)
EDUCATION_RANGES: tuple[tuple[str, int], ...] = (
    (r"less\s+than\s+high\s*school|no\s+high\s*school", 1),
    (r"high\s*school|hs\b", 3),
    (r"some\s+college|college\s+but\s+no", 3),
    (r"bachelor|undergraduate|degree", 4),
    (r"graduate|postgraduate|master|phd", 5),
)
MARITAL_RANGES: tuple[tuple[str, int], ...] = (
    (r"\bmarried\b", 1),
    (r"\bdivorced\b|\bseparated\b|\bwidowed\b", 3),
)
SIZE_RANGES: tuple[tuple[str, int], ...] = (
    (r"\balone\b|\b1\s*person\b|single\s+adult", 1),
    (r"\b2\s*(?:people|adults|person)\b|\bcouple\b|\bmarried\s+with\s+1\b", 2),
    (r"\b3\s*(?:people|person)\b", 3),
    (r"\b4\s*(?:people|person)\b", 4),
)
METRO_RANGES: tuple[tuple[str, int], ...] = (
    (r"\bnon-?metro\b|\brural\b|\bsmall\s+town\b", 0),
    (r"\bmetro\b|\burban\b|\bcity\b|\bsuburb", 1),
)

# Only these seven fields participate. Anything else typed is ignored rather
# than guessed at, so a partial household profile stays visibly partial.
_HOUSEHOLD_GROUPS: tuple[tuple[str, int, tuple[tuple[str, int], ...]], ...] = (
    ("age_band", 8, AGE_RANGES),
    ("household_income", 9, INCOME_RANGES),
    ("education", 5, EDUCATION_RANGES),
    ("marital_status", 5, MARITAL_RANGES),
    ("household_size", 5, SIZE_RANGES),
    ("metro_area", 2, METRO_RANGES),
)

_COUNTY_RICH = re.compile(
    r"(?:county\s+poverty|poverty\s+share)\D{0,12}(40|less|fewer|more)\b", re.I
)


@dataclass
class Route:
    """What a query resolved to, and which panels that justifies opening."""

    raw: str = ""
    #: Panels to open, in display order.
    panels: list[str] = field(default_factory=list)
    lender_name: str | None = None
    lender_id: str | None = None
    #: True when more than one dataset lender was named.
    ambiguous_lender: bool = False
    #: The query asked for a verdict, an opinion, or advice. The panels still
    #: open, because the complaint mix is a fact and refusing to show it would be
    #: its own failure, but the interface says plainly what it is not.
    seeking_verdict: bool = False
    offer: Offer = field(default_factory=Offer)
    household: dict[str, Any] = field(default_factory=dict)
    #: Household fields named but not understood, so the panel can say so.
    household_unmatched: list[str] = field(default_factory=list)
    #: Panels whose preconditions are met.
    notes: list[str] = field(default_factory=list)

    @property
    def has_lender(self) -> bool:
        return self.lender_id is not None

    @property
    def has_figures(self) -> bool:
        return self.offer.usable

    @property
    def has_household(self) -> bool:
        return bool(self.household)

    def to_dict(self) -> dict[str, Any]:
        return {
            "panels": list(self.panels),
            "lender_name": self.lender_name,
            "lender_id": self.lender_id,
            "ambiguous_lender": self.ambiguous_lender,
            "seeking_verdict": self.seeking_verdict,
            "has_figures": self.has_figures,
            "offer": self.offer.to_dict(),
            "household": dict(self.household),
            "household_unmatched": list(self.household_unmatched),
            "notes": list(self.notes),
        }


def _match_group(text: str, field: str, groups) -> int | None:
    for pattern, code in groups:
        if re.search(rf"\b(?:{pattern})", text, re.I):
            return code
    return None


def _route_household(text: str) -> tuple[dict[str, Any], list[str]]:
    """Map explicit demographic phrasing onto survey codes.

    Narrow on purpose. If the user writes "I'm 35-44 and make about $60k", the
    age and income map and education, marital status, household size and
    county poverty do not, so the household panel opens showing what was
    understood and naming what was not. It does not fill the gaps with defaults,
    because a survey percentile computed from guessed inputs is a number the
    user did not ask for and cannot check.
    """
    out: dict[str, Any] = {}
    unmatched: list[str] = []
    for field_name, _max_code, groups in _HOUSEHOLD_GROUPS:
        code = _match_group(text, field_name, groups)
        if code is not None:
            out[field_name] = code
        else:
            unmatched.append(field_name)
    m = _COUNTY_RICH.search(text)
    if m:
        token = m.group(1).lower()
        if token in ("40", "more"):
            out["county_poverty_share"] = 1
        else:
            out["county_poverty_share"] = 0
    else:
        unmatched.append("county_poverty_share")
    return out, unmatched


def route(query: str) -> Route:
    """Work out what to show for a query of any completeness."""
    raw = (query or "").strip()
    r = Route(raw=raw)
    if not raw:
        return r

    # --- lender ---
    matches = tools.match_lenders_in_text(raw, limit=4)
    if len(matches) == 1:
        r.lender_id = matches[0]["id"]
        r.lender_name = matches[0]["name"]
    elif len(matches) > 1:
        r.ambiguous_lender = True
        r.lender_name = ", ".join(m["name"] for m in matches)

    # --- loan figures ---
    r.offer = parse_offer(raw)

    # --- household ---
    household, unmatched = _route_household(raw)
    r.household = household
    r.household_unmatched = unmatched

    r.seeking_verdict = bool(
        re.search(
            r"\b(?:is|are|was|were)\b[^.?]{0,40}?\b(?:safe|unsafe|a\s+scam|"
            r"fraud|trustworthy|reliable|predatory|risky|dangerous)\b"
            r"|\b(?:should|would)\s+i\s+(?:borrow|take\s+out|apply|get\s+a\s+loan)\b"
            r"|\bcan\s+i\s+trust\b"
            r"|\bdo\s+you\s+recommend\b"
            r"|\bwhich\s+lender\s+should\b"
            r"|\b(?:best|safest|worst)\s+lenders?\b"
            # "which lender is best" puts the superlative last
            r"|\bwhich\s+lenders?\s+(?:is|are|should|would)\b"
            r"|\b(?:is|are)\s+(?:the\s+)?(?:best|worst|safest)\b"
            r"|\brank\s+(?:the\s+)?(?:lenders?|them)\b"
            r"|\b(?:your|my)\s+(?:risk|credit\s+worthiness)\s*(?:score|rating)\b",
            raw,
            re.I,
        )
    )

    # --- which panels that earns ---
    if r.has_lender:
        r.panels.append(PANEL_LENDER)
    if r.has_figures:
        r.panels.append(PANEL_PAYOFF)
    if household:
        r.panels.append(PANEL_HOUSEHOLD)
    if re.search(
        r"\b(methodolog|how\s+(?:is|are|do|does)\b.{0,30}\bwork|"
        r"how\s+(?:is|are)\s+(?:this|it|that)\s+(?:calculated|derived|computed)|"
        r"what\s+does\s+.{0,30}\smean|peer[- ]referenc|"
        r"what\s+is\s+the\s+evidence\b|"
        r"where\s+does\s+the\s+data\s+come|how\s+is\s+this\s+scored)\b",
        raw,
        re.I,
    ):
        r.panels.append(PANEL_METHOD)

    if r.seeking_verdict:
        r.notes.append(
            (
                "You asked whether this lender is safe or which to choose. The"
                " panels show what consumers reported and what the terms cost."
                if r.panels
                else
                "You asked whether a lender is safe or which to choose. Nothing"
                " here can answer that, and this analysis will not say a lender is"
                " safe or unsafe, or rank lenders."
            )
            + " This analysis does not grade, and does not tell you whether to"
            " borrow."
        )
    if r.ambiguous_lender:
        r.notes.append(
            f"Your text names more than one lender ({r.lender_name}), so the "
            "complaint panel is closed. Say which one the offer is from."
        )
    elif not r.panels:
        r.notes.append(
            "Nothing in that could be matched to a lender, a set of loan terms, "
            "or a household profile."
        )
    if r.has_lender and r.has_figures:
        r.notes.append(
            "Opened the complaint and payoff panels, since the query named a "
            "lender and a set of terms."
        )
    elif r.has_lender:
        r.notes.append(
            "Opened the complaint panel only. Add the amount, the rate and the "
            "term to open the payoff panel too."
        )
    return r


#: What the interface shows when nothing has been asked yet.
PLACEHOLDER = (
    "Name a lender, paste the terms of an offer, or give a household profile. "
    "You do not need all three."
)

EXAMPLES: tuple[tuple[str, str], ...] = (
    ("Uprova Credit", "opens the complaint panel"),
    (
        "Uprova Credit, $300 at 391% for 14 days",
        "opens the complaint and payoff panels",
    ),
    (
        "I'm 35-44, household income 50-75k, college graduate",
        "opens the household panel",
    ),
    (
        "Uprova Credit $300 at 391% for 14 days, I'm 35-44, income 50-75k",
        "opens all three",
    ),
)
