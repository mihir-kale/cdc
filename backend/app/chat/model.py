"""The model seam.

No endpoint is provisioned, so nothing here talks to a network. What exists is
the seam a real client will drop into, plus a deterministic stub so the whole
assistant is testable today and the wiring is proven before a key exists.

The protocol is deliberately narrow. A client returns the assistant turns it
wants the model to see and the tools available; it returns text. It has no way
to reach the complaint dataset, the survey model, or the filesystem, because
those are only reachable through :mod:`app.chat.tools`. That is the point: the
model is not trusted with data access, it is trusted only to phrase what the
tools already returned.

Swapping in a real client means implementing :class:`ChatModel` and constructing
:class:`Assistant` with it. Nothing else changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class Turn:
    """One message in the conversation."""

    role: str  # "system" | "user" | "tool"
    content: str
    name: str | None = None

    def as_api_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            d["name"] = self.name
        return d


@runtime_checkable
class ChatModel(Protocol):
    """What the assistant needs from a language model."""

    def complete(
        self,
        turns: list[Turn],
        tools: list[dict[str, Any]],
    ) -> str:
        """Return the assistant's reply as text.

        Implementations should either answer from the supplied tool results or
        state that it cannot. Returning a refusal is a valid and expected
        outcome; the assistant does not treat it as a failure.
        """
        ...


SYSTEM_PROMPT = """You are the assistant for Know Your Loan, which analyses \
CFPB consumer complaint data about payday lenders.

You answer questions by calling the provided tools. You cannot look anything up
by yourself: if a question needs data, call a tool. If the tools do not cover
what was asked, say so plainly.

Hard limits. These are not stylistic preferences:
- Never say a lender is safe, unsafe, a scam, trustworthy, risky, or predatory.
  You can describe complaint patterns and peer comparisons, nothing more.
- Never rank lenders, name a best or worst or safest lender, or produce an
  overall score. Complaint volume mostly reflects how many complaints a lender
  generated, and this dataset has no customer or loan-volume denominators, so a
  lender with more complaints is not a worse lender.
- Never tell anyone whether to borrow, take a loan, or apply for credit.
- Report only figures that appear in a tool result. Do not compute new ones,
  do not convert them into a judgement, and do not round them into a
  comparison the data does not support.
- Complaint shares are of a lender's complaints in this dataset. They are not a
  rate per customer, and there is no way to compute a per-customer rate here.
- The household figure is a survey association. It is not a prediction about
  the person asking and not a SNAP eligibility determination.

Write plainly, in short paragraphs. Say what the data shows, then what it does
not show. Do not open with a disclaimer; put the caveat where it is relevant."""


@dataclass
class ScriptedModel:
    """Deterministic stand-in for a real model.

    Returns queued replies in order, so a test can script a conversation,
    including a refusal or a guard violation, and assert on what the assistant
    does with it. When the script runs out it reports the call rather than
    improvising, so a test that expects two turns fails loudly instead of
    silently getting a generic answer.
    """

    replies: list[str] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def complete(self, turns: list[Turn], tools: list[dict[str, Any]]) -> str:
        self.calls.append(
            {
                "turns": [t.as_api_dict() for t in turns],
                "tools": [t["name"] for t in tools],
            }
        )
        if not self.replies:
            return "I don't have anything scripted for that."
        return self.replies.pop(0)


@dataclass
class EchoModel:
    """A model that quotes the tool results it was given.

    Not useful as an assistant, but useful as a worst case: it is the stand-in
    for a model that does its job literally, so the guard can be tested against
    something that is not already well-behaved.
    """

    calls: list[list[Turn]] = field(default_factory=list)

    def complete(self, turns: list[Turn], tools: list[dict[str, Any]]) -> str:
        self.calls.append(turns)
        for t in reversed(turns):
            if t.role == "tool":
                return f"Here is the raw result: {t.content}"
        return "I have no tool results to work from."


def render_transcript(turns: list[Turn]) -> str:
    """Human-readable transcript, for logs and for the debug pane."""
    out = []
    for t in turns:
        who = t.name or t.role
        body = t.content if len(t.content) <= 400 else t.content[:400] + " …"
        out.append(f"[{who}] {body}")
    return "\n".join(out)


def parse_tool_json(payload: str) -> dict[str, Any] | None:
    """Parse a tool result, tolerating a truncated tail."""
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        if payload.endswith(" …[truncated]"):
            try:
                return json.loads(payload[: -len(" …[truncated]")])
            except json.JSONDecodeError:
                return None
        return None
