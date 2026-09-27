"""The assistant: gate, tools, model, guard.

The order is the design. Each stage can end the turn, and each refusal is a
first-class return rather than an exception or an apology appended to an answer:

    message -> scope.classify -> (refuse) -> model -> guard -> (replace) -> reply

A declined or out-of-scope message never reaches the model, so it costs nothing
and cannot be talked past. An in-scope message gets tool results, a reply, and a
post-check; if the reply grades a lender or quotes a figure no tool returned, it
is replaced.

:func:`answer` is the whole public surface. The Streamlit tab and any future HTTP
endpoint both call it, so the behaviour is identical wherever it is reached from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.chat import guard, scope, tools
from app.chat.briefing import Briefing, build_briefing
from app.chat.model import SYSTEM_PROMPT, ChatModel, ScriptedModel, Turn


@dataclass
class AssistantReply:
    """What the UI needs to render one turn."""

    text: str
    #: ``answer`` | ``declined`` | ``out_of_scope`` | ``guarded``
    outcome: str
    refusal: str | None = None
    tool_names: tuple[str, ...] = ()
    tool_results: tuple[dict[str, Any], ...] = ()
    violations: tuple[str, ...] = field(default=())
    #: Present when the reply is a composed offer briefing.
    briefing: Briefing | None = None

    @property
    def used_tools(self) -> bool:
        return bool(self.tool_names)


def _refusal_text(reason: str | None) -> str:
    if reason and reason in tools.REFUSALS:
        return tools.REFUSALS[reason]
    return tools.REFUSALS["out_of_domain"]


def _resolve_lender_id(message: str) -> str | None:
    """Best-effort single-lender resolution from free text.

    The model is expected to call ``find_lenders`` first, but a one-shot
    question naming a lender should not fail because the model skipped that
    step. Matching is delegated to the tools module, which knows the entity
    suffixes; this only picks among the candidates.
    """
    candidates = tools.match_lenders_in_text(message, limit=6)
    if not candidates:
        return None
    if len(candidates) > 1:
        # Only accept an unambiguous match. Guessing between two lenders named in
        # one sentence is exactly the kind of quiet wrong answer to avoid.
        return None
    return candidates[0]["id"]


def _gather(
    tool_names: tuple[str, ...],
    message: str,
    household_profile: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Run the tools the gate sanctioned, and nothing else.

    This is the security boundary in practice. The model does not choose which
    tools run; the gate does, from the user's own words, and the model receives
    the results. A prompt injection in the message cannot widen the toolset,
    because the toolset was fixed before the message was read as anything but
    text.
    """
    results: list[dict[str, Any]] = []
    household = dict(household_profile or {})

    for name in tool_names:
        if name == tools.TOOL_METHOD:
            results.append(tools.call(tools.TOOL_METHOD))
        elif name == tools.TOOL_LOOKUP:
            # Query the extracted name rather than the whole sentence, so the
            # lookup is not a substring test against a full message.
            names = tools.match_lenders_in_text(message, limit=6)
            query = names[0]["name"] if len(names) == 1 else message
            results.append(tools.call(tools.TOOL_LOOKUP, query=query, limit=6))
        elif name == tools.TOOL_LENDER:
            lender_id = _resolve_lender_id(message)
            if lender_id is None:
                results.append(
                    {
                        "tool": tools.TOOL_LENDER,
                        "ok": False,
                        "error": "no lender in the dataset matches that name",
                        "claims": [],
                        "data": {},
                    }
                )
            else:
                results.append(tools.call(tools.TOOL_LENDER, lender_id=lender_id))
        elif name == tools.TOOL_HOUSEHOLD:
            if household:
                results.append(tools.call(tools.TOOL_HOUSEHOLD, profile=household))
            else:
                # Not sent when the UI has no profile. Explaining a household
                # result without the household's inputs is still possible; it
                # just cannot be recomputed from the chat surface alone.
                results.append(
                    {
                        "tool": tools.TOOL_HOUSEHOLD,
                        "ok": False,
                        "error": "no household profile is set in the interface",
                        "claims": [],
                        "data": {},
                    }
                )
        elif name == tools.TOOL_PAYOFF:
            # Figures come from the interface, never from parsing the message.
            # A number the model inferred from conversation is not evidence.
            if all(k in household for k in ("principal", "apr", "payment")):
                results.append(
                    tools.call(
                        tools.TOOL_PAYOFF,
                        principal=household["principal"],
                        apr=household["apr"],
                        payment=household["payment"],
                    )
                )
            else:
                results.append(
                    {
                        "tool": tools.TOOL_PAYOFF,
                        "ok": False,
                        "error": (
                            "no loan figures are set in the interface; enter them "
                            "on the Loan Payoff Calculator tab"
                        ),
                        "claims": [],
                        "data": {},
                    }
                )
    return results


def answer_offer(
    text: str,
    *,
    model: ChatModel | None = None,
    household_profile: dict[str, Any] | None = None,
    include_household: bool = False,
) -> AssistantReply:
    """Answer a pasted loan offer with the composed briefing.

    The briefing is assembled from the tools before the model is consulted, so
    the model only ever phrases figures the analysis produced. When no endpoint
    is configured the briefing *is* the reply, which is why the tab is useful
    today rather than a placeholder.
    """
    verdict = scope.classify(text)
    if verdict.decision is not scope.Decision.ANSWER:
        return answer(
            text, model=model, household_profile=household_profile
        )

    briefing: Briefing = build_briefing(
        text, household_profile=household_profile, include_household=include_household
    )

    if model is None:
        return AssistantReply(
            text=briefing.as_text(),
            outcome="answer",
            tool_names=(scope.TOOL_BRIEFING,),
            briefing=briefing,
        )

    # Give the model the composed briefing as its only evidence, plus the same
    # hard limits, then guard the result against the figures it was given.
    turns = [
        Turn(role="system", content=SYSTEM_PROMPT),
        Turn(role="user", content=text),
        Turn(
            role="tool",
            name=scope.TOOL_BRIEFING,
            content=briefing.as_text(),
        ),
    ]
    raw = model.complete(turns, tools.TOOL_SCHEMAS)
    checked = guard.check_reply(
        raw,
        [briefing.as_text()],
        sanctioned_numbers=briefing.numbers(),
    )
    if not checked.ok:
        # Fall back to the composed briefing rather than the model's text. The
        # briefing is the product; the model is only ever a nicer phrasing of it.
        return AssistantReply(
            text=briefing.as_text(),
            outcome="guarded",
            tool_names=(scope.TOOL_BRIEFING,),
            briefing=briefing,
            violations=checked.violations,
        )
    return AssistantReply(
        text=checked.text,
        outcome="answer",
        tool_names=(scope.TOOL_BRIEFING,),
        briefing=briefing,
    )


def answer(
    message: str,
    *,
    model: ChatModel | None = None,
    household_profile: dict[str, Any] | None = None,
) -> AssistantReply:
    """Answer one user message, or decline it."""
    verdict = scope.classify(message)

    if verdict.decision is scope.Decision.DECLINE:
        return AssistantReply(
            text=_refusal_text(
                verdict.refusal.value if verdict.refusal else "out_of_domain"
            ),
            outcome="declined",
            refusal=verdict.refusal.value if verdict.refusal else None,
        )

    if verdict.decision is scope.Decision.OUT_OF_SCOPE:
        return AssistantReply(
            text=_refusal_text("out_of_domain"),
            outcome="out_of_scope",
            refusal="out_of_domain",
        )

    results = _gather(verdict.tools, message, household_profile)
    usable = [r for r in results if r.get("ok")]
    if not usable:
        detail = "; ".join(
            r.get("error", "unavailable") for r in results if not r.get("ok")
        )
        return AssistantReply(
            text=(
                "I can't answer that from this analysis"
                + (f": {detail}." if detail else ".")
                + " Try a specific lender name, or ask what the peer comparison "
                "and evidence levels mean."
            ),
            outcome="out_of_scope",
            refusal="out_of_domain",
            tool_names=verdict.tools,
            tool_results=tuple(results),
        )

    turns: list[Turn] = [
        Turn(role="system", content=SYSTEM_PROMPT),
        Turn(role="user", content=message),
    ]
    for r in results:
        turns.append(
            Turn(role="tool", content=tools.to_json(r), name=r.get("tool"))
        )

    client = model or ScriptedModel()
    raw = client.complete(turns, tools.TOOL_SCHEMAS)

    checked = guard.check_reply(raw, [tools.to_json(r) for r in results])
    if not checked.ok:
        return AssistantReply(
            text=checked.text,
            outcome="guarded",
            tool_names=verdict.tools,
            tool_results=tuple(results),
            violations=checked.violations,
        )

    return AssistantReply(
        text=checked.text,
        outcome="answer",
        tool_names=verdict.tools,
        tool_results=tuple(results),
    )
