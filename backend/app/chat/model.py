"""The model seam.

The Gemini client is implemented and used only when a key is configured; with no
key every call site receives ``None`` and the deterministic text renders, so the
app is fully functional offline and nothing here is required for it to run.

The SDK is imported lazily, inside :meth:`GeminiModel._client`, rather than at
module scope. CI installs ``backend/requirements-test.txt``, which does not
include the root ``requirements.txt`` where ``google-genai`` is pinned, so a
top-level import would break the suite on a clean checkout.

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

import hashlib
import json
import os
import time
from collections import OrderedDict
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


#: The model used when none is configured. Overridable via the ``gemini.model``
#: secret, because model names move and this file should not have to.
#:
#: gemini-3.5-flash was the first choice and returned 503 UNAVAILABLE on every
#: attempt against a live key -- "high demand", not an auth failure. gemini-3.6-flash
#: and later respond. A flash model is deliberate: the reply is at most three
#: sentences of panel text, and the guard rejects anything it did not ask for.
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"

#: Read in this order by the SDK itself, but checked here too so a key is
#: recognised the same way whether it came from a secret or the environment.
GEMINI_KEY_ENV_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")


def gemini_key_from_env() -> str | None:
    """The configured Gemini key, or None.

    ``GOOGLE_API_KEY`` takes precedence when both are set, which is the SDK's own
    rule, so this matches it rather than inventing a different one.
    """
    for name in reversed(GEMINI_KEY_ENV_VARS):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return None


#: HTTP statuses worth retrying. 429 is quota/throughput, 503 is capacity.
_TRANSIENT_STATUS = frozenset({429, 503})


def _is_transient(exc: Exception) -> bool:
    """True for a capacity or rate-limit failure, False for anything real.

    An invalid key is a 400 and must not be retried, and a prompt blocked by
    safety filters is not an error at all -- retrying either just delays the
    deterministic fallback the caller falls back to anyway.
    """
    status = getattr(exc, "code", None)
    if status is None:
        return False
    try:
        return int(status) in _TRANSIENT_STATUS
    except (TypeError, ValueError):
        return False


def resolve_gemini_config(secret_table: dict[str, Any] | None = None) -> dict | None:
    """Decide whether a Gemini client can be built, and with what settings.

    Pure and Streamlit-free on purpose: ``app.py`` is a Streamlit script and
    cannot be imported by the test suite -- ``import app`` resolves to the
    backend package, which is the name collision this repo already documents.
    So the decision lives here and the caller passes in whatever it read from
    ``st.secrets``.

    ``secret_table`` is the ``[gemini]`` section::

        [gemini]
        api_key = "..."
        model   = "gemini-3.5-flash"   # optional

    The environment is the fallback, which is how a local run works without a
    secrets file. Returns None when no key is configured, and that None is the
    signal the app runs its deterministic text -- not an error.
    """
    cfg: dict[str, Any] = {}
    if secret_table:
        cfg = {k: str(v).strip() for k, v in dict(secret_table).items() if v}

    key = cfg.get("api_key") or gemini_key_from_env()
    if not key:
        return None

    cfg["api_key"] = key
    cfg.setdefault("model", DEFAULT_GEMINI_MODEL)
    return cfg


@dataclass
class GeminiModel:
    """A :class:`ChatModel` backed by the Gemini API.

    The assistant passes a flat list of turns and a tool schema; this flattens
    the turns into one prompt and returns the reply text. It is given no data
    access beyond that prompt, which is the property that matters: a model here
    can only phrase what the tools already returned.

    Failures are raised, not swallowed. Every call site already treats an
    exception as "use the deterministic text", so swallowing here would hide the
    reason and make a broken key look like a working app.
    """

    api_key: str
    model: str = DEFAULT_GEMINI_MODEL
    temperature: float = 0.2
    max_output_tokens: int = 800
    #: Short retries for capacity blips. Live testing returned 503 UNAVAILABLE
    #: ("high demand") intermittently against a valid key, including on models
    #: that succeeded moments earlier, so a single attempt was not a reliable
    #: test of whether the model is reachable. Deliberately small and bounded:
    #: the call site falls back to deterministic text on any failure, so waiting
    #: longer than this only delays the page.
    #: Small on purpose. A Streamlit render is serial -- one panel blocks the
    #: next -- so a retry budget that looks reasonable in isolation multiplies by
    #: the number of panels. Measured: three attempts with 1.5s backoff held the
    #: page for over four seconds per panel against a rate-limited key.
    max_attempts: int = 2
    retry_backoff: float = 1.0
    #: Hard ceiling on one request, in milliseconds. Without it a slow call
    #: holds the whole page rather than one panel, because Streamlit renders
    #: panels in series and there is no other thread to answer on.
    timeout_ms: int = 15000
    #: Replies are keyed by their prompt and reused. Without this every Streamlit
    #: rerun re-called the API for text it had already generated: a repeated
    #: identical query measured 7.6s. A panel's figures are deterministic for a
    #: given state, so the same prompt can only produce the same passage.
    cache_size: int = 128
    #: Injected in tests. Defaults to a real client built from ``api_key``.
    client_factory: Any = None
    #: Built on first use and reused; see :meth:`_client`.
    _client_obj: Any = field(default=None, repr=False)
    #: prompt -> reply. Bounded, insertion-ordered, dropped oldest first.
    _cache: "OrderedDict[str, str]" = field(default_factory=OrderedDict, repr=False)

    def _client(self) -> Any:
        """The SDK client, built once and reused.

        Cached because building one per call is not merely wasteful: the SDK
        closes its HTTP transport when a client is discarded, and a second
        request through a fresh client in the same session fails with
        "Cannot send a request, as the client has been closed."
        """
        if self._client_obj is not None:
            return self._client_obj
        if self.client_factory is not None:
            self._client_obj = self.client_factory()
            return self._client_obj
        try:
            from google import genai  # noqa: PLC0415 -- deliberate lazy import
        except ImportError as exc:  # pragma: no cover - depends on the env
            raise RuntimeError(
                "google-genai is not installed. Run: pip install google-genai"
            ) from exc
        # Imported here with the SDK, for the same lazy reason.
        from google.genai import types  # noqa: PLC0415

        self._client_obj = genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(timeout=self.timeout_ms),
        )
        return self._client_obj

    def complete(
        self,
        turns: list[Turn],
        tools: list[dict[str, Any]],
    ) -> str:
        # No running event loop, so this is the sync client. ``config`` is a
        # plain dict rather than a types.GenerateContentConfig: the SDK parses
        # dicts into its own pydantic config, and not importing ``types`` is what
        # lets the whole client be unit-tested without the SDK installed.
        prompt = "\n\n".join(
            f"[{t.role}{'/' + t.name if t.name else ''}]\n{t.content}" for t in turns
        )
        cache_key = hashlib.sha256(
            f"{self.model}|{self.temperature}|{self.max_output_tokens}|{prompt}".encode()
        ).hexdigest()
        if cache_key in self._cache:
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]

        last: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self._client().models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config={
                        "temperature": self.temperature,
                        "max_output_tokens": self.max_output_tokens,
                    },
                )
            except Exception as exc:
                last = exc
                if not _is_transient(exc) or attempt == self.max_attempts:
                    raise
                time.sleep(self.retry_backoff * attempt)
                continue
            text = (getattr(response, "text", "") or "").strip()
            # An empty reply is not cached. It means the model declined or was
            # cut off, and caching that would suppress a retry on the next rerun
            # when it may well have succeeded.
            if text:
                self._cache[cache_key] = text
                while len(self._cache) > self.cache_size:
                    self._cache.popitem(last=False)
            return text
        raise last or RuntimeError("unreachable")  # pragma: no cover


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
