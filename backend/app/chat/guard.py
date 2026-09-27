"""Post-generation checks on the assistant's reply.

The scope gate stops the wrong question reaching the model. This catches the
failure the gate cannot: the model answering an in-scope question in a way the
evidence does not support. The specific risk is reintroducing the ranking and
verdict language the interface deliberately removed. Ask a model "compare these
two lenders" and it will grade them, no matter how carefully the prompt is
worded, because grading is what language models do when handed comparative data.

So the reply is checked after the fact, against the claims the tools actually
authorised. Three checks:

1. **Verdict language.** A reply that calls a lender safe, unsafe, trustworthy
   or similar is replaced, whatever the tool results said.
2. **Ranking language.** "best", "worst", "safest lender", a numbered league
   table: refused, because FinePrint publishes no ranking.
3. **Unsupported numbers.** Every figure in the reply must appear in some tool
   result. A number that appears nowhere in the evidence is a hallucination
   regardless of how well it reads.

The reply is replaced with a refusal rather than edited. A partial edit would
leave the unsupported claim in place with a caveat attached, which is the thing
most likely to be believed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

RANKING_REFUSAL = (
    "I can't rank or grade lenders. Complaint volume mostly reflects how many "
    "complaints a lender generated, and there are no customer or loan-volume "
    "denominators here, so more complaints does not mean a worse lender. I can "
    "describe one lender's complaint pattern, or compare two specific lenders' "
    "patterns, without saying either is better."
)

VERDICT_REFUSAL = (
    "I can't say whether a lender is safe or unsafe. What the data supports is "
    "the pattern of complaints consumers reported about that lender, and how "
    "that compares with modeled payday-loan peers. That is a description of "
    "complaints, not a verdict on the lender."
)

# A verdict *about a lender*. Bare adjectives are not enough: "this pattern is
# risky" and "the fee disclosures are unclear" are fine, and over-broad patterns
# here would refuse most honest answers.
_VERDICT = re.compile(
    r"\b(?:is|are|was|were|seems?|looks?|appears?)\s+"
    r"(?:\w+\s+){0,3}?"
    r"(?:safe|unsafe|a\s+scam|a\s+fraud|fraudulent|trustworthy|untrustworthy|"
    r"legit(?:imate)?|a\s+rip\s*off|predatory|reliable|unreliable)\b"
    r"|\b(?:safe|trustworthy|legit(?:imate)?|honest|reliable)\s+"
    r"(?:lender|loan|company|choice)\b"
    r"|\b(?:lender|company)\s+is\s+(?:good|bad|fine|okay|ok)\b"
    r"|\bverdict\b"
    r"|\b(?:i|we)\s+(?:would\s+)?rate\b"
    r"|\bgraded?\b"
    # A letter grade is a grade whatever it is wrapped in.
    r"|\b(?:grade|rated|rating)\s+[A-F]\b"
    r"|\b[A-F]\s*-\s*grade\b",
    re.I,
)

_RANKING = re.compile(
    r"\b(?:best|worst|safest|least\s+bad|most\s+dangerous)\s+"
    r"(?:lender|loan|company|option|choice)s?\b"
    r"|\bthe\s+best\s+(?:lender|loan|one)\b"
    r"|\brank(?:s|ed|ing)?\s+(?:the\s+)?(?:lender|loan|them)\b"
    r"|\bwhich\s+(?:lender|one)\s+should\s+i\b"
    r"|\b(?:top|bottom)\s+\d+\s+(?:lender|loan|company)s?\b"
    r"|\btop\s+(?:lender|loan|company)s?\b"
    r"|\brecommend\s+(?:a\s+)?(?:lender|loan|company)\b"
    r"|\bgo\s+with\b"
    r"|\b(?:overall|final)\s+(?:score|rating|grade)\b"
    r"|\b\d+\s*(?:/\s*100)?\s*(?:overall\s+)?(?:score|grade)\s+of\b"
    # A bare superlative with no noun after it still ranks: "the safest" is a
    # ranking claim even when the sentence never says "lender".
    r"|\bthe\s+(?:best|worst|safest|least\s+bad|most\s+reliable)\b"
    r"|\b(?:best|safest|most\s+reliable)\s+(?:option|choice|one)\b",
    re.I,
)

# This product does not produce a risk score for a person or a loan. The
# household figure is a survey association and the model that produces it says
# in its own documentation that it does not predict what taking out a loan would
# do. So any claim of a risk or credit score is refused rather than answered,
# because there is no honest version of the number to give.
_SCORE_CLAIM = re.compile(
    r"\b(?:your\s+|the\s+|their\s+|his\s+|her\s+)?"
    r"(?:risk|credit\s+worthiness|creditworthiness|credit)\s*"
    r"(?:score|rating|number)\b"
    r"|\byour\s+(?:score|rating)\s+is\b"
    r"|\brisk\s+level\b"
    r"|\bhow\s+(?:risky|safe)\s+(?:is|are)\s+(?:this|that|the)\s+loan\b"
    # A risk verdict on the specific offer, which is the judgement this product
    # is built not to make.
    r"|\b(?:risky|dangerous|unsafe|hazardous|risky-looking)\s+"
    r"(?:loan|offer|deal)\b"
    r"|\b(?:a|an)\s+(?:risky|dangerous|unsafe)\s+(?:loan|one|idea)\b",
    re.I,
)

# Unsolicited advice. The other checks stop the model grading a lender or
# inventing a number; none of them stopped it telling someone what to do. On a
# page whose entire purpose is a person deciding whether to take a loan, that is
# the failure that matters most, so it is checked explicitly.
_ADVICE = re.compile(
    r"\byou\s+(?:should|shouldn't|should\s+not|must|need\s+to|ought\s+to|"
    r"may\s+want\s+to|have\s+to)\s+(?:\w+\s+){0,3}?"
    r"(?:borrow|take|apply|sign|accept|get|choose|pick|use|avoid|repay|"
    r"refinance)\b"
    r"|\b(?:i|we)\s+(?:would\s+)?recommend\b"
    r"|\b(?:this|that|the)\s+(?:(?:loan|offer|deal)\s+)?is\s+(?:a\s+)?"
    r"(?:good|decent|fair|bad|poor|great|bad\s+value)\s+"
    r"(?:deal|one|choice|value|option)\b"
    r"|\byou(?:'| a)?re\s+(?:better|worse)\s+off\b"
    # "you will be better off", not only "you're better off"
    r"|\byou\s+will\s+be\s+(?:better|worse)\s+off\b"
    r"|\byou(?:'| a)?re\s+(?:better|worse)\s+off\s+(?:off\s+)?"
    r"(?:if|with|by|doing|taking|borrowing)\b"
    r"|\bi(?:'d|\s+would)\s+(?:suggest|advise)\b"
    r"|\bworth\s+(?:taking|signing|borrowing)\b"
    r"|\bconsider\s+(?:taking|borrowing|applying)\b"
    r"|\bavoid\s+this\s+lender\b"
    r"|\bgo\s+with\s+(?:this|that)\s+(?:lender|loan)\b",
    re.I,
)

ADVICE_REFUSAL = (
    "I am not going to tell you whether to take this loan. What I can do is "
    "show you what people reported about this lender, what these terms cost, "
    "and where households with a profile like yours sit in survey data. Those "
    "are three separate facts, and the decision is yours."
)

SCORE_REFUSAL = (
    "There is no risk score to give you here, and I would not invent one. What "
    "I can show is the household survey figure, which describes how households "
    "with characteristics like yours appear in national survey data. It is not a "
    "prediction about you and not a judgement about this loan, and the model "
    "behind it is documented as not forecasting what taking out a loan would do. "
    "The complaint and cost figures above are the parts of this analysis that "
    "speak to a specific lender and a specific offer."
)

# Numbers, with thousands separators, decimals and percent signs. A bare small
# integer is not matched: category codes and ages would swamp the check.
# The refusal strings below, and the scope gate's, are known-safe by
# construction: they are the text this system writes when it declines. They are
# exempt from the checks below because the checks cannot tell a negation from an
# assertion -- "I can't say whether a lender is safe" trips any pattern that
# catches "this lender is safe". Exempting them by exact match keeps the
# patterns strict for model output while making the guard idempotent: a reply
# that was already replaced passes a second pass untouched, so a retried turn
# cannot loop.
SYSTEM_TEXTS: frozenset[str] = frozenset()


def register_system_texts(texts: object) -> None:
    """Register known-safe system-authored strings.

    Additive, and safe to call more than once. The guard registers its own
    refusals at import time so that idempotency does not depend on some other
    module having been imported first.
    """
    global SYSTEM_TEXTS
    SYSTEM_TEXTS = SYSTEM_TEXTS | frozenset(
        t for t in texts if isinstance(t, str)  # type: ignore[union-attr]
    )


_NUMBER = re.compile(
    r"(?<![\w.])(?:\$?\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+%?|\d+%|\$\d+)(?![\w])"
)


@dataclass
class GuardResult:
    """Outcome of checking one reply."""

    text: str
    ok: bool
    violations: tuple[str, ...] = ()
    unsupported: tuple[str, ...] = field(default=())


# The disclosure the product is required to make, in its ordinary phrasings. These
# are negations: "this is not a grade" contains the word "grade", and "there is no
# overall score" contains "overall score". A model asked to state the disclaimer
# therefore trips the very patterns meant to catch a grade being handed out.
#
# These spans are removed before the verdict and ranking checks run, and only
# these. It is not a general negation-blind exemption: "Uprova is not safe" does
# not match here and is still caught, because the point of the pattern is that a
# bare superlative is a claim even when it is a hedged one.
_NEGATED_DISCLOSURE = re.compile(
    r"\b(?:is\s+not|are\s+not|was\s+not|were\s+not|not\s+a|not\s+an|no|"
    r"never|without)\s+(?:an?\s+)?"
    r"(?:overall\s+|final\s+|lender\s+)?"
    r"(?:grade|score|rating|verdict|grading|rank(?:ing)?s?)\b"
    r"|\bthere\s+is\s+no\s+(?:overall\s+)?(?:score|grade|rating|verdict)\b"
    r"|\bnothing\s+here\s+is\s+a\s+(?:grade|score|rating|verdict)\b",
    re.I,
)


def strip_negated_disclosures(text: str) -> str:
    """Remove disclaimer phrasing before the ranking and verdict checks."""
    return _NEGATED_DISCLOSURE.sub(" ", text or "")


def _numbers(text: str) -> set[str]:
    """Normalise figures so 1,234 and 1234.0 compare equal."""
    out: set[str] = set()
    for m in _NUMBER.findall(text or ""):
        raw = m.replace("$", "").replace(",", "").replace("%", "").strip()
        try:
            val = float(raw)
        except ValueError:
            continue
        out.add(f"{val:g}")
    return out


def _allowed_numbers(tool_results: list[str]) -> set[str]:
    allowed: set[str] = set()
    for blob in tool_results:
        allowed |= _numbers(blob)
    return allowed


def check_reply(
    reply: str,
    tool_results: list[str],
    *,
    allow_unsupported: bool = False,
    sanctioned_numbers: list[float] | None = None,
    require_no_grade_disclosure: bool = False,
) -> GuardResult:
    """Check one assistant reply against what the tools actually returned.

    ``tool_results`` are the serialised tool payloads given to the model. They
    are the entire evidence base for the reply, so a figure absent from all of
    them is unsupported.

    ``allow_unsupported`` exists for tests that deliberately inject a bad figure
    and need the number check to be the thing that fires.

    ``require_no_grade_disclosure`` checks presence rather than absence. The
    other checks can only reject a claim that is made; none of them can notice a
    required statement that was left out. On a page where the model writes the
    disclosure, a model that simply omits it would otherwise pass, and the
    no-grade guarantee would quietly disappear. So the guarantee is enforced in
    both directions: forbidden claims are rejected, and the disclosure must be
    present.
    """
    text = reply or ""
    if text in SYSTEM_TEXTS:
        return GuardResult(text, True, ("system_text",))
    violations: list[str] = []

    if _SCORE_CLAIM.search(text):
        violations.append("score_claim")
    if _ADVICE.search(text):
        violations.append("advice")
    # Checked against the text with disclaimer phrasing removed, so stating the
    # no-grade disclosure is not treated as asserting a grade.
    scannable = strip_negated_disclosures(text)
    if _RANKING.search(scannable):
        violations.append("ranking_language")
    if _VERDICT.search(scannable):
        violations.append("verdict_language")

    unsupported: list[str] = []
    if not allow_unsupported and tool_results:
        allowed = _allowed_numbers(tool_results)
        # A composed briefing asserts figures it derived from tool output, such
        # as a total repaid or a percentage of the amount borrowed. Those are
        # passed in explicitly by the composer, which knows what it computed,
        # rather than loosened here.
        for n in sanctioned_numbers or []:
            allowed.add(f"{float(n):g}")
        # Ordinals and small counts the assistant legitimately derives, e.g.
        # "five categories", are words not figures, so anything still unmatched
        # here was written as a numeral.
        for n in sorted(_numbers(text) - allowed, key=lambda s: -len(s)):
            unsupported.append(n)

    if require_no_grade_disclosure and not _NEGATED_DISCLOSURE.search(text):
        violations.append("missing_disclosure")

    if violations:
        if "advice" in violations:
            return GuardResult(ADVICE_REFUSAL, False, tuple(violations), ())
        if "missing_disclosure" in violations:
            return GuardResult(
                "This passage did not state that the comparison is not a grade, "
                "so it is not shown. The lender page always carries that "
                "statement.",
                False,
                tuple(violations),
                (),
            )
        if "score_claim" in violations:
            return GuardResult(SCORE_REFUSAL, False, tuple(violations), ())
        if "ranking_language" in violations:
            return GuardResult(RANKING_REFUSAL, False, tuple(violations), ())
        return GuardResult(VERDICT_REFUSAL, False, tuple(violations), ())

    if unsupported:
        return GuardResult(
            "I don't have a figure for that in the data I retrieved, so I would "
            "rather not guess. Ask me about a specific lender's complaint "
            "pattern, a loan's payoff, or what the peer comparison means.",
            False,
            ("unsupported_number",),
            tuple(unsupported),
        )

    return GuardResult(text, True)


# Registered here rather than left to the caller, so the guard is correct on its
# own terms the moment it is imported.
register_system_texts(
    {RANKING_REFUSAL, VERDICT_REFUSAL, SCORE_REFUSAL, ADVICE_REFUSAL}
)
