"""Deterministic scope gate for the assistant.

Every user message passes through :func:`classify` before any model is called.
This is the whole reason the assistant can be relied on to decline: scope is
decided by ordinary Python over an allowlist, not by asking a language model to
police itself. A prompt instruction is bypassable, costs a round trip to fail,
and cannot be unit tested. A match on a keyword list can be tested exhaustively,
which is what the tests below do.

Three outcomes:

``answer``
    In scope, and the gate also says *which* tools are likely relevant, so an
    irrelevant tool is never called and its data never enters the context.

``decline``
    Recognisably a request the assistant must refuse: a verdict on whether a
    lender is safe, financial advice, or a ranking of lenders. Each carries the
    reason so the refusal can be specific rather than a generic brush-off.

``out_of_scope``
    Not about this product at all. The model is not consulted, so this is also
    the cheap path for chit-chat and off-topic questions.

The ordering matters and is tested: a message that both names a lender and asks
for a verdict ("is Uprova safe?") is a ``decline``, not an ``answer``. Otherwise
the most important rejection in the system would be the one an unrelated
keyword could bypass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class Decision(str, Enum):
    ANSWER = "answer"
    DECLINE = "decline"
    OUT_OF_SCOPE = "out_of_scope"


class Refusal(str, Enum):
    """Why the assistant is declining, so the reply can be specific."""

    LENDER_VERDICT = "lender_verdict"
    FINANCIAL_ADVICE = "financial_advice"
    LENDER_RANKING = "lender_ranking"
    OUT_OF_DOMAIN = "out_of_domain"


# Tools the assistant can reach. The gate's job is to pick among these, never to
# invent a capability.
TOOL_BRIEFING = "build_offer_briefing"
TOOL_LENDER = "get_lender_complaints"
TOOL_HOUSEHOLD = "get_household_context"
TOOL_PAYOFF = "estimate_payoff"
TOOL_METHOD = "get_methodology"
TOOL_LOOKUP = "find_lenders"

# Ordered most specific first. These run before any topic matching, because a
# question can contain both a lender name and a demand for a verdict.
# Each alternative states its own boundaries. A stem such as "methodolog" is a
# prefix of a longer word, so a trailing \b would land mid-word and the match
# would always fail; a whole word such as "fees" keeps \b on both sides.
def _rx(*alternatives: str) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{a})" for a in alternatives), re.I)


_VERDICT_PATTERNS: tuple[tuple[Refusal, re.Pattern[str]], ...] = (
    (
        Refusal.LENDER_RANKING,
        _rx(
            r"\brank(?:ing|ings|ed)?\b",
            r"\bbest\b",
            r"\bworst\b",
            r"\bsafest\b",
            r"\bleast\s+bad\b",
            r"\btop\s+\d+\b",
            r"\bwhich\s+lender\s+should\b",
            r"\brecommend\s+(?:a\s+)?lender\b",
            r"\bcompare\s+all\b",
            r"\blist\s+the\s+(?:best|worst|safest)\b",
            r"\bbiggest\s+(?:red\s+)?flags?\s+across\b",
        ),
    ),
    (
        Refusal.LENDER_VERDICT,
        _rx(
            # A lender name sits between the copula and the adjective ("is
            # Uprova Credit safe?"), so allow a short run of any words rather
            # than a single token.
            r"\b(?:is|are|was|were)\b[^.?]{0,40}?\b"
            r"(?:safe|unsafe|scam|fraud|legit|trustworthy|reliable|risky|"
            r"predatory|dangerous)\b",
            r"\b(?:safe|trustworthy|legit|honest)\s+(?:lender|loan|company)\b",
            r"\b(?:should|would)\s+i\s+(?:borrow|take\s+out|get\s+a\s+loan|"
            r"apply)\b",
            r"\bcan\s+i\s+trust\b",
            r"\bdo\s+you\s+recommend\b",
            r"\bis\s+it\s+(?:safe|ok|okay|fine|legit|legal)\b",
            r"\brip(?:ped)?\s+off\b",
        ),
    ),
    (
        Refusal.FINANCIAL_ADVICE,
        _rx(
            # "pay" is deliberately absent: "what should I pay attention to" is
            # this product's own headline question, and a bare "pay" here
            # classified it as a request for financial advice.
            r"\bwhat\s+should\s+i\s+(?:borrow|take\s+out|choose|apply\s+for)\b",
            r"\bshould\s+i\s+(?:borrow|invest|buy|save)\b",
            r"\bcan\s+i\s+afford\b",
            r"\bhow\s+much\s+can\s+i\s+borrow\b",
            r"\bfinancial\s+advice\b",
            r"\binvest(?:ing|ments?)?\b",
            r"\bmortgage\b",
            r"\bcredit\s+score\s+boost\b",
            r"\brefinanc(?:e|ing)\b",
            r"\btax(?:es|\s+advice)\b",
            r"\blegal\s+advice\b",
            r"\bis\s+it\s+(?:worth|worthwhile|financially\s+wise)\b",
        ),
    ),
)

# Topic patterns. Each names the tools it makes relevant.
# An offer pasted in full: figures, a rate, or the words that appear on a loan
# document. Matched on document shape so a badly formatted offer is still
# recognised, and deliberately ahead of the question-shaped patterns.
_OFFER_SHAPE = _rx(
    r"\bloan\s*(?:amount|principal)\s*[:\-]",
    r"\badvance\s*amount\s*[:\-]",
    r"\bamount\s*(?:borrowed|financed)\s*[:\-]",
    r"\bfinance\s*charge\s*[:\-]",
    r"\btotal\s*repayment\s*[:\-]",
    r"\bapr\s*[:\-]?\s*\d",
    r"\bannual\s+percentage\s+rate\s*[:\-]",
    r"\bprincipal\s*(?:amount)?\s*[:\-]",
    r"\d+\s*(?:monthly\s+)?payments?\s+of\s+\$",
    r"\bamount\s+repayable\b",
    r"\bterm\s*[:\-]\s*\d+\s*(?:days?|months?)",
)

_TOPIC_PATTERNS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (
        _OFFER_SHAPE,
        (TOOL_BRIEFING, TOOL_LENDER, TOOL_PAYOFF),
    ),
    (
        _rx(
            r"\bmethodolog",
            r"\bhow\s+(?:is|are|do)\s+(?:this|it|the\s+(?:score|number|"
            r"comparison))\b",
            r"\bwhat\s+(?:does|do)\b[^.?]{0,40}?\b"
            r"(?:score|comparison|number|share|figure)s?\s+mean\b",
            r"\bpeer\b",
            r"\bpeer[- ]referenc",
            r"\bempirical\b",
            r"\bshrinkage\b",
            r"\bposterior\b",
            r"\bcredible\s+interval",
            r"\bstatistic",
            r"\bformul",
            r"\bdisclos",
            r"\bcaveat",
            r"\blimitation",
            r"\bwhere\s+does\s+the\s+data\s+come\b",
            r"\bevidence\b",
        ),
        (TOOL_METHOD,),
    ),
    (
        _rx(
            r"\bpayoff\b",
            r"\bpay\s+off\b",
            r"\brepay(?:ment)?\b",
            r"\bamortis",
            r"\bamortiz",
            r"\bhow\s+long\s+(?:to|does\s+it\s+take)\b",
            r"\bhow\s+many\s+months\b",
            r"\bhow\s+much\s+interest\b",
            r"\btotal\s+interest\b",
            r"\bmonthly\s+payment\b",
            r"\bpayment\s+schedule\b",
            r"\bdebt\s+trap\b",
            r"\binterest\s+rate\b",
            r"\bapr\b",
            r"\bprincipal\b",
        ),
        (TOOL_PAYOFF,),
    ),
    (
        _rx(
            r"\bhousehold\b",
            r"\bmy\s+situation\b",
            r"\bmy\s+profile\b",
            r"\bfinancial\s+context\b",
            r"\bpercentile\b",
            r"\bsurvey\b",
            r"\bsnap\b",
            r"\bfood\s+(?:assistance|insecurity)\b",
            r"\bwell[- ]?being\b",
            r"\bmy\s+(?:age|income|education|marital|family\s+size)\b",
            r"\bcompare\s+me\b",
            r"\bam\s+i\s+(?:typical|normal|similar)\b",
            # The briefing's own follow-up offer. Framed as the survey figure it
            # is, so the gate routes it to the household tool rather than
            # treating it as a request for a verdict on the loan.
            r"\bwhere\s+(?:do\s+)?households?\s+like\s+(?:me|you|us)\s+"
            r"(?:sit|fall|rank)\b",
            r"\b(?:add|show|include)\s+(?:that|the)\s+(?:household|survey|"
            r"percentile)\b",
            r"\bhow\s+does\s+(?:my|our)\s+(?:household|profile|demographics)\s+"
            r"(?:compare|stack|look)\b",
        ),
        (TOOL_HOUSEHOLD,),
    ),
    (
        _rx(
            r"\blenders?\b",
            r"\bcomplaint",
            r"\bcfpb\b",
            r"\bborrow",
            r"\bpayday\b",
            r"\bloans?\b",
            r"\bfees?\b",
            r"\bservicing\b",
            r"\bwithdrawal\b",
            r"\bauthoris",
            r"\bauthoriz",
            r"\bunauthoris",
            r"\bunauthoriz",
            r"\bcredit\s+report",
            r"\bdispute",
            r"\bwhat\s+(?:should|do)\s+i\s+(?:watch|look|pay\s+attention)\b",
            r"\bwhich\s+lender\b",
        ),
        (TOOL_LENDER, TOOL_LOOKUP),
    ),
)

# Small talk and unrelated domains. Checked last, and only once nothing in scope
# matched, so "what's the weather" cannot shadow a real question.
_OUT_OF_DOMAIN = re.compile(
    r"^\s*(hi|hey|hello|yo|thanks|thank\s+you|ta|ok|okay|cool|nice|"
    r"good\s+morning|good\s+evening|bye|goodbye)\b[\s!.?]*$"
    r"|\b(weather|forecast|temperature|stock\s+price|crypto|bitcoin|"
    r"recipe|joke|football|soccer|election|president|news|movie|"
    r"restaurant|hotel|flight|vacation|translate|spell\s+this|"
    r"write\s+(?:me\s+)?(?:a\s+)?(?:poem|song|essay|story)|"
    r"medical|doctor|symptom|diagnos)\b",
    re.I,
)


@dataclass(frozen=True)
class ScopeResult:
    """Gate outcome plus the reasoning, kept so it can be asserted in tests."""

    decision: Decision
    tools: tuple[str, ...] = ()
    refusal: Refusal | None = None
    matched: str | None = None
    notes: tuple[str, ...] = field(default=())


def classify(message: str) -> ScopeResult:
    """Decide whether ``message`` may be answered, without consulting a model."""
    text = (message or "").strip()
    if not text:
        return ScopeResult(
            decision=Decision.OUT_OF_SCOPE,
            refusal=Refusal.OUT_OF_DOMAIN,
            matched="empty",
        )

    # Refusals first. A verdict request that also names a lender is still a
    # refusal, and this ordering is what makes that true.
    for refusal, pattern in _VERDICT_PATTERNS:
        m = pattern.search(text)
        if m:
            return ScopeResult(
                decision=Decision.DECLINE,
                refusal=refusal,
                matched=m.group(0),
                notes=("refusal matched before topic",),
            )

    tools: list[str] = []
    matched: list[str] = []
    for pattern, tool_names in _TOPIC_PATTERNS:
        m = pattern.search(text)
        if m:
            matched.append(m.group(0))
            for t in tool_names:
                if t not in tools:
                    tools.append(t)

    if tools:
        return ScopeResult(
            decision=Decision.ANSWER,
            tools=tuple(tools),
            matched=matched[0] if matched else None,
            notes=("in scope",),
        )

    if _OUT_OF_DOMAIN.search(text):
        return ScopeResult(
            decision=Decision.OUT_OF_SCOPE,
            refusal=Refusal.OUT_OF_DOMAIN,
            matched="out_of_domain",
        )

    # Unknown, but not recognisably harmful. Treated as out of scope rather than
    # guessed at: an unrecognised question is exactly the case where the assistant
    # should not improvise an answer from tools it was not steered toward.
    return ScopeResult(
        decision=Decision.OUT_OF_SCOPE,
        refusal=Refusal.OUT_OF_DOMAIN,
        matched="no_topic_match",
        notes=("no tool pattern matched",),
    )
