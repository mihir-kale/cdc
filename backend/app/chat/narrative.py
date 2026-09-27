"""The written interpretation on a lender page.

Two questions are answered here in prose: what to pay attention to with this
lender, and how its complaint pattern compares with peers. Both were previously
assembled by string surgery in the Streamlit app, which produced three fixed
paragraphs that read identically for every lender and repeated what the marks
above them already said.

The prose is now the model's job, with the deterministic version kept as the
floor rather than deleted. The floor matters more than it looks: the output guard
can reject a reply that grades a lender or invents a figure, but it cannot notice
a reply that simply omits the disclosure. So enforcement is by rejection, not by
hope. A reply that fails the guard is discarded and the deterministic text is
shown instead, which means the page can never end up with the no-grade
disclosure quietly missing.

With no endpoint configured this module always returns the floor, so the page
reads exactly as it did before. Wiring an endpoint is one argument.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.chat import guard
from app.chat.model import ChatModel, Turn

# Fixed regardless of the model. This is the guarantee, and it is also the
# fallback's, so it is written once here and asserted by tests.
NO_GRADE_DISCLOSURE = (
    "These are not a grade, and there is no overall score for a lender. Complaint "
    "volume reflects how many complaints a lender generated, and this dataset "
    "has no customer or loan-volume denominators, so a lender with more "
    "complaints is not a worse lender."
)

PEER_MARK_DISCLOSURE = (
    "A solid mark with a direction means the model can separate this lender from "
    "its peers on that complaint type. A dash means it cannot, and carries no "
    "direction."
)

NARRATIVE_SYSTEM = """You are writing the short interpretive passage on a \
lender page in Know Your Loan, which analyses CFPB consumer complaint data \
about payday lenders.

You are given that lender's observed complaint mix, its peer comparisons, its \
evidence level, and per-category guidance. Write two short paragraphs in plain \
language: first what a consumer should pay attention to with this lender, then \
how its complaint pattern compares with typical payday-loan peers.

Hard limits. These are not stylistic preferences:
- Never say the lender is safe, unsafe, a scam, trustworthy, risky or
  predatory, and never give a risk score or a credit score. You can describe
  complaint patterns and nothing more.
- Never rank lenders or name a best, worst or safest one.
- Report only figures that appear in the data you were given. Do not compute new
  ones and do not convert them into a judgement.
- Complaint shares are of this lender's complaints in the dataset. They are not a
  rate per customer.
- If the data cannot distinguish a pattern from peers, say so plainly rather than
  implying a difference.
- Always state that the comparison is not a grade and that there is no overall
  score for a lender.

Write plainly and briefly. Two or three sentences per paragraph. No headings, \
no bullet points, no preamble."""


@dataclass
class Narrative:
    """One rendered interpretation, and where it came from."""

    #: Paragraphs, in order.
    paragraphs: list[str]
    #: True when these paragraphs were written by a model rather than assembled.
    generated: bool
    #: Why the model's text was not used, when it was not.
    fallback_reason: str | None = None

    def as_html(self, paragraph_class: str = "kyl-note") -> str:
        body = "".join(
            f'<p class="{paragraph_class}">{guard_html_escape(p)}</p>'
            for p in self.paragraphs
        )
        disclosure = (
            f'<p class="kyl-fine">{guard_html_escape(NO_GRADE_DISCLOSURE)}</p>'
        )
        return f"<div>{body}{disclosure}</div>"


def guard_html_escape(text: str) -> str:
    """Escape for HTML. Duplicated from the app on purpose.

    The chat package cannot import app.py, and app.py is the only other place
    that needs this, so a four-line escape beats a circular dependency.
    """
    import html

    return html.escape(str(text), quote=True)


# --------------------------------------------------------------------------
# The floor: the deterministic text
# --------------------------------------------------------------------------


def _clause(text: str) -> str:
    text = text.strip().rstrip(".")
    if text.lower().startswith("check"):
        text = text[5:].strip()
    return text[:1].lower() + text[1:] if text else text


def deterministic_watch_for(label: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    """What to pay attention to, assembled from the largest observed categories."""
    scored = [r for r in rows if r["slug"] != "other" and r["complaints"] > 0]
    if not scored:
        return "No complaints in this dataset for this lender, so there is no pattern here to look at."

    top = scored[:2]
    names = [r["label"].split(" &")[0].split(" /")[0].lower() for r in top]
    subject = " and ".join(names)
    verb = "makes up" if len(names) == 1 else "make up"
    guidance = "; ".join(
        _clause(r["what_to_inspect"]) for r in top if r.get("what_to_inspect")
    )

    total = int(label["n_complaints"])
    if total < 10:
        suffix = "" if total == 1 else "s"
        lead = (
            f"With only {total} complaint{suffix} on record, any one category can"
            " look dominant by chance, so treat this as a starting point rather"
            " than a pattern."
        )
    else:
        lead = f"{subject.capitalize()} {verb} the largest share of the complaints associated with this lender."

    return f"{lead} Worth checking: {guidance}." if guidance else lead


def deterministic_peer_comparison(label: dict[str, Any]) -> str:
    """How separable this lender is, in words."""
    counts = {"more": 0, "fewer": 0, "similar": 0}
    for value in label.get("dimensions", {}).values():
        c = value.get("comparison", "similar")
        counts[c] = counts.get(c, 0) + 1
    separable = counts["more"] + counts["fewer"]
    if separable == 0:
        return (
            "None of the five complaint patterns can be distinguished from peers"
            " here, so the comparison supports no statement in either direction."
        )
    parts = []
    if counts["more"]:
        parts.append(f"more complaints than peers on {counts['more']}")
    if counts["fewer"]:
        parts.append(f"fewer complaints than peers on {counts['fewer']}")
    return (
        f"The model can separate this lender from peers on {separable} of 5 "
        f"patterns: {', '.join(parts)}."
    )


def floor_narrative(label: dict[str, Any], rows: list[dict[str, Any]]) -> Narrative:
    return Narrative(
        paragraphs=[
            deterministic_watch_for(label, rows),
            deterministic_peer_comparison(label),
        ],
        generated=False,
    )


# --------------------------------------------------------------------------
# The model path
# --------------------------------------------------------------------------


def build_facts(label: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    """The evidence the model is given, and nothing else.

    A compact factual brief. The model gets figures and guidance, not prose, so
    there is no existing wording for it to paraphrase into a verdict.
    """
    dims = label.get("dimensions", {})
    other = label.get("other", {})
    lines = [
        f"Lender: {label['name']}",
        f"Payday-loan complaints in dataset: {label['n_complaints']}",
        f"Evidence level: {label['evidence']}",
        "",
        "Observed mix (share is of this lender's complaints, not a rate per customer):",
    ]
    scored = [r for r in rows if r["complaints"] > 0]
    for r in scored:
        lines.append(
            f"  {r['label']}: {r['complaints']} complaints, "
            f"{float(r['share']) * 100:.1f}%"
        )
    if other.get("complaints"):
        lines.append(
            f"  {other.get('label', 'Other reported issues')}: "
            f"{other['complaints']} complaints, "
            f"{float(other.get('share', 0)) * 100:.1f}%"
        )
    lines += ["", "Peer comparison per category (model output, not a grade):"]
    for slug, d in dims.items():
        lines.append(f"  {d.get('label', slug)}: {d.get('comparison', 'similar')}")
    lines += ["", "Guidance per category:"]
    for r in rows:
        if r.get("what_to_inspect"):
            lines.append(f"  {r['label']}: {r['what_to_inspect']}")
    return "\n".join(lines)


def build_narrative(
    label: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    model: ChatModel | None = None,
) -> Narrative:
    """Model-written interpretation, or the floor if there is no usable model."""
    floor = floor_narrative(label, rows)
    if model is None:
        return floor

    facts = build_facts(label, rows)
    try:
        # Turn objects, not dicts: ChatModel implementations call as_api_dict()
        # on them, and passing plain dicts raises inside the model, which the
        # except below would silently turn into a fallback.
        raw = model.complete(
            [
                Turn(role="system", content=NARRATIVE_SYSTEM),
                Turn(role="user", content=facts),
            ],
            [],
        )
    except Exception as exc:  # a transport failure must not blank the page
        return Narrative(
            paragraphs=floor.paragraphs,
            generated=False,
            fallback_reason=f"model call failed: {exc}",
        )

    text = (raw or "").strip()
    if not text:
        return Narrative(
            paragraphs=floor.paragraphs,
            generated=False,
            fallback_reason="model returned nothing",
        )

    checked = guard.check_reply(
        text,
        # The guard is shown the facts, so a figure the model invented is
        # unsupported, and the fixed disclosure is sanctioned so the reply is
        # allowed to restate it.
        [facts],
        sanctioned_numbers=_floor_numbers(label, rows),
        require_no_grade_disclosure=True,
    )
    if not checked.ok:
        return Narrative(
            paragraphs=floor.paragraphs,
            generated=False,
            fallback_reason=",".join(checked.violations),
        )

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()] or [text]
    return Narrative(paragraphs=paragraphs, generated=True)


def _floor_numbers(label: dict[str, Any], rows: list[dict[str, Any]]) -> list[float]:
    """Every figure legitimately on the page, so the guard can allow a restatement."""
    out: list[float] = [float(label.get("n_complaints", 0))]
    for r in rows:
        if r.get("complaints") is not None:
            out.append(float(r["complaints"]))
        if r.get("share") is not None:
            share = float(r["share"])
            out.append(share * 100 if share <= 1 else share)
    counts = {"more": 0, "fewer": 0, "similar": 0}
    for d in label.get("dimensions", {}).values():
        counts[d.get("comparison", "similar")] = counts.get(d.get("comparison", "similar"), 0) + 1
    out += [float(counts["more"]), float(counts["fewer"]), float(counts["similar"])]
    out.append(float(counts["more"] + counts["fewer"]))
    out.append(5.0)
    return out
