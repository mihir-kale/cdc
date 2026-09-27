"""Tests for the generated interpretation on a lender page.

The contract is deliberately unusual: the model writes the prose, and the
deterministic text is the floor rather than a fallback of last resort. These
tests pin both halves, because the interesting failures are all cases where one
half is supposed to catch the other.
"""

from __future__ import annotations

import os
from unittest import mock

import unittest

from app import label_store
from app.chat import guard
from app.chat.analysis import build_analysis
from app.chat.model import (
    DEFAULT_GEMINI_MODEL,
    GeminiModel,
    ScriptedModel,
    Turn,
    gemini_key_from_env,
    resolve_gemini_config,
)
from app.chat.narrative import (
    NO_GRADE_DISCLOSURE,
    build_facts,
    build_narrative,
    deterministic_peer_comparison,
    deterministic_watch_for,
    floor_narrative,
)


def _label(lender_id: str = "5") -> dict:
    return label_store.get_lender(lender_id)


def _rows(label: dict) -> list[dict]:
    meta = label_store.dataset_summary()["dimensions"]
    return [
        {
            "slug": slug,
            "label": d["label"],
            "complaints": d["complaints"],
            "share": d["share"],
            "what_to_inspect": meta[slug].get("what_to_inspect", ""),
        }
        for slug, d in label["dimensions"].items()
    ]


GOOD = (
    "Fees and servicing make up most of what people reported here. Worth "
    "checking how payments are credited and what the fee disclosures say.\n\n"
    "The model can separate this lender from peers on 5 of 5 patterns. This is "
    "not a grade and there is no overall score for a lender."
)


class TestFloor(unittest.TestCase):
    """The deterministic text. This is what renders with no endpoint."""

    def setUp(self) -> None:
        self.label = _label()
        self.rows = _rows(self.label)

    def test_watch_for_names_the_largest_categories(self) -> None:
        text = deterministic_watch_for(self.label, self.rows)
        self.assertIn("largest share", text)
        self.assertIn("Worth checking", text)

    def test_peer_comparison_counts_separable_dimensions(self) -> None:
        text = deterministic_peer_comparison(self.label)
        self.assertRegex(text, r"on \d of 5 patterns")

    def test_floor_is_not_marked_generated(self) -> None:
        n = floor_narrative(self.label, self.rows)
        self.assertFalse(n.generated)
        self.assertEqual(len(n.paragraphs), 2)

    def test_no_endpoint_gives_the_floor(self) -> None:
        n = build_narrative(self.label, self.rows, model=None)
        self.assertFalse(n.generated)
        self.assertIsNone(n.fallback_reason)
        self.assertEqual(n.paragraphs, floor_narrative(self.label, self.rows).paragraphs)

    def test_sparse_lender_is_hedged(self) -> None:
        sparse = next(
            r["id"] for r in label_store.lender_index() if r["n_complaints"] < 10
        )
        label = label_store.get_lender(sparse)
        text = deterministic_watch_for(label, _rows(label))
        self.assertIn("by chance", text)

    def test_facts_carry_no_prose_to_paraphrase(self) -> None:
        facts = build_facts(self.label, self.rows)
        self.assertIn("Fees & Costs", facts)
        self.assertIn("complaints in dataset", facts)
        # The brief is figures and guidance. No existing sentence for a model to
        # lift a verdict out of.
        self.assertNotIn("safest", facts)
        self.assertNotIn("best", facts.lower().replace("better", ""))


class TestGeneratedNarrative(unittest.TestCase):
    def setUp(self) -> None:
        self.label = _label()
        self.rows = _rows(self.label)

    def test_a_faithful_reply_is_used(self) -> None:
        n = build_narrative(self.label, self.rows, model=ScriptedModel(replies=[GOOD]))
        self.assertTrue(n.generated)
        self.assertIsNone(n.fallback_reason)
        self.assertEqual(len(n.paragraphs), 2)
        self.assertIn("Fees and servicing", n.paragraphs[0])

    def test_a_verdict_is_discarded(self) -> None:
        reply = "This is the safest lender around.\n\nNot a grade, no overall score."
        n = build_narrative(self.label, self.rows, model=ScriptedModel(replies=[reply]))
        self.assertFalse(n.generated)
        self.assertIn("ranking_language", n.fallback_reason)

    def test_a_risk_score_is_discarded(self) -> None:
        reply = "Your risk score is 12.\n\nNot a grade, no overall score."
        n = build_narrative(self.label, self.rows, model=ScriptedModel(replies=[reply]))
        self.assertFalse(n.generated)
        self.assertIn("score_claim", n.fallback_reason)

    def test_an_invented_figure_is_discarded(self) -> None:
        reply = (
            "This lender has 4,200 complaints.\n\n"
            "Not a grade, no overall score."
        )
        n = build_narrative(self.label, self.rows, model=ScriptedModel(replies=[reply]))
        self.assertFalse(n.generated)
        self.assertIn("unsupported_number", n.fallback_reason)

    def test_omitting_the_disclosure_is_discarded(self) -> None:
        # Rejection cannot notice an absent claim, so presence is checked too.
        # Without this the no-grade guarantee disappears silently.
        reply = "Fees are the main thing people reported here. Check the fee disclosures."
        n = build_narrative(self.label, self.rows, model=ScriptedModel(replies=[reply]))
        self.assertFalse(n.generated)
        self.assertIn("missing_disclosure", n.fallback_reason)

    def test_restating_a_legitimate_figure_is_allowed(self) -> None:
        total = self.label["n_complaints"]
        reply = (
            f"This lender has {total} complaints in the dataset.\n\n"
            "Not a grade, no overall score."
        )
        n = build_narrative(self.label, self.rows, model=ScriptedModel(replies=[reply]))
        self.assertTrue(n.generated, n.fallback_reason)

    def test_a_transport_failure_falls_back_rather_than_raising(self) -> None:
        class Broken:
            def complete(self, turns, tools):
                raise RuntimeError("endpoint unreachable")

        n = build_narrative(self.label, self.rows, model=Broken())
        self.assertFalse(n.generated)
        self.assertIn("endpoint unreachable", n.fallback_reason)
        self.assertEqual(n.paragraphs, floor_narrative(self.label, self.rows).paragraphs)

    def test_an_empty_reply_falls_back(self) -> None:
        n = build_narrative(self.label, self.rows, model=ScriptedModel(replies=["   "]))
        self.assertFalse(n.generated)
        self.assertIn("nothing", n.fallback_reason)

    def test_the_disclosure_is_always_rendered(self) -> None:
        for model in (
            None,
            ScriptedModel(replies=[GOOD]),
            ScriptedModel(replies=["safest lender ever"]),
        ):
            with self.subTest(model=type(model).__name__):
                n = build_narrative(self.label, self.rows, model=model)
                self.assertIn(NO_GRADE_DISCLOSURE, n.as_html())


class TestDisclosureGuardInteraction(unittest.TestCase):
    """The guard has to allow the disclaimer while still catching a real claim."""

    ALLOWED = [
        "This is not a grade and there is no overall score for a lender.",
        "There is no overall score for a lender.",
        "Nothing here is a grade.",
        "These are not ratings.",
    ]
    BLOCKED = [
        "Uprova is the safest lender.",
        "Uprova is the best lender overall.",
        "They are the best.",
        "Uprova is not safe.",
        "I would rate this lender B.",
    ]

    def test_disclaimer_phrasing_is_allowed(self) -> None:
        for text in self.ALLOWED:
            with self.subTest(text=text):
                self.assertTrue(guard.check_reply(text, []).ok)

    def test_real_claims_are_still_blocked(self) -> None:
        for text in self.BLOCKED:
            with self.subTest(text=text):
                self.assertFalse(guard.check_reply(text, []).ok)

    def test_presence_check_is_opt_in(self) -> None:
        # Without the flag, a reply with no disclaimer is fine: not every reply
        # is a lender narrative and most do not need the statement.
        self.assertTrue(guard.check_reply("Fees are 54.9% of complaints.", []).ok)
        self.assertFalse(
            guard.check_reply(
                "Fees are 54.9% of complaints.", [], require_no_grade_disclosure=True
            ).ok
        )

    def test_disclosure_refusal_is_idempotent(self) -> None:
        r = guard.check_reply("They are the best.", [])
        self.assertTrue(guard.check_reply(r.text, []).ok)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

class TestGeminiClient(unittest.TestCase):
    """The Gemini client, exercised without the SDK or a network.

    The contract that matters: a configured client is used, a broken one raises
    so the call site falls back, and a reply the guard rejects still leaves the
    deterministic text in place. That last one is the safety property, and it is
    the reason a model can be switched on at all.
    """

    FACTS = {
        "name": "Uprova Credit",
        "n_complaints": 331,
        "band_label": "Higher financial strain among surveyed households",
        "percentile": 72,
    }

    class _StubModels:
        def __init__(self, reply: str = "Uprova shows a higher share of "
                                         "servicing complaints than peers.") -> None:
            self.reply = reply
            self.calls: list[dict] = []

        def generate_content(self, **kwargs):
            self.calls.append(kwargs)
            text = self.reply(kwargs) if callable(self.reply) else self.reply
            return type("R", (), {"text": text})()

    class _StubClient:
        def __init__(self, models):
            self.models = models

    def _model(self, reply="ok", **kw):
        models = self._StubModels(reply)
        return GeminiModel(
            api_key="test-key",
            client_factory=lambda: self._StubClient(models),
            **kw,
        ), models

    def test_complete_returns_the_reply_text(self) -> None:
        model, models = self._model("A short factual sentence.")
        out = model.complete([Turn(role="user", content="explain")], [])
        self.assertEqual(out, "A short factual sentence.")
        self.assertEqual(len(models.calls), 1)

    def test_turns_are_flattened_into_one_prompt(self) -> None:
        model, models = self._model()
        model.complete(
            [Turn(role="system", content="SYSTEM"), Turn(role="user", content="USER")],
            [],
        )
        prompt = models.calls[0]["contents"]
        self.assertIn("SYSTEM", prompt)
        self.assertIn("USER", prompt)
        self.assertIn("[system]", prompt)

    def test_empty_reply_is_empty_not_an_exception(self) -> None:
        model, _ = self._model("")
        self.assertEqual(model.complete([Turn(role="user", content="x")], []), "")

    def test_client_failure_raises_so_the_caller_falls_back(self) -> None:
        class Boom:
            @property
            def models(self):
                raise RuntimeError("quota exhausted")

        model = GeminiModel(api_key="k", client_factory=lambda: Boom())
        with self.assertRaises(RuntimeError):
            model.complete([Turn(role="user", content="x")], [])

    def test_a_guarded_reply_leaves_the_deterministic_text_in_place(self) -> None:
        # A model that grades a lender must not change what the panel shows.
        model, _ = self._model("Uprova is a predatory lender with a risk score of 12.")
        a = build_analysis("lender", self.LENDER_FACTS, model=model)
        self.assertFalse(a.generated)
        self.assertNotIn("predatory", a.text)
        self.assertIn(a.limit, a.as_html())

    def test_a_model_cannot_report_a_figure_it_was_not_given(self) -> None:
        model, _ = self._model("The lender serves 4.2 million customers.")
        a = build_analysis("lender", self.LENDER_FACTS, model=model)
        self.assertFalse(a.generated)
        self.assertNotIn("4.2 million", a.text)

    LENDER_FACTS = {
        "name": "Uprova Credit",
        "n_complaints": 331,
        "top_category": "Servicing & Payment Handling",
        "top_share": 34.1,
    }

    def test_a_compliant_reply_is_used(self) -> None:
        # A lender reply must carry the no-grade disclosure verbatim or the guard
        # rejects it, which is why this test asserts on a reply that includes it
        # rather than on any plausible-sounding sentence.
        reply = (
            "This lender's complaints lean towards servicing and payment "
            "handling. " + NO_GRADE_DISCLOSURE
        )
        model, _ = self._model(reply)
        a = build_analysis("lender", self.LENDER_FACTS, model=model)
        self.assertTrue(a.generated, a.fallback_reason)
        self.assertIn("servicing", a.text)
        self.assertIn(a.limit, a.as_html())

    def test_the_disclosure_is_required_on_the_page_not_from_the_model(self) -> None:
        # The disclosure is fixed product copy that Analysis.as_html() always
        # renders in its own paragraph, so the guarantee is about the page, not
        # about the model reproducing 47 words verbatim. Requiring it inside the
        # model's prose meant no real model reply was ever used.
        model, _ = self._model(
            "This lender's complaints lean towards servicing and payment handling."
        )
        a = build_analysis("lender", self.LENDER_FACTS, model=model)
        self.assertTrue(a.generated, a.fallback_reason)
        self.assertNotIn("not a grade", a.text)
        self.assertEqual(a.as_html().count(a.limit), 1)
        self.assertIn("no overall score for a lender", a.as_html())

    def test_a_reply_that_grades_is_still_rejected_with_the_limit_present(self) -> None:
        # Relaxing where the disclosure is checked must not weaken anything the
        # guard is for.
        model, _ = self._model(
            "This lender is a predatory scam with a risk score of 12 out of 100."
        )
        a = build_analysis("lender", self.LENDER_FACTS, model=model)
        self.assertFalse(a.generated)
        self.assertIn("no overall score for a lender", a.as_html())

    def test_a_transient_error_is_retried_then_raises(self) -> None:
        from app.chat.model import _is_transient

        class Err(Exception):
            def __init__(self, code):
                super().__init__(f"http {code}")
                self.code = code

        self.assertTrue(_is_transient(Err(503)))
        self.assertTrue(_is_transient(Err(429)))
        self.assertFalse(_is_transient(Err(400)))   # bad key: do not retry
        self.assertFalse(_is_transient(Err(403)))   # forbidden: do not retry
        self.assertFalse(_is_transient(Exception("x")))  # no status: do not retry

    def test_retry_stops_after_max_attempts(self) -> None:
        attempts = {"n": 0}

        class Err(Exception):
            code = 503

        class Flaky:
            @property
            def models(self):
                attempts["n"] += 1
                raise Err("unavailable")

        model = GeminiModel(api_key="k", client_factory=lambda: Flaky(),
                            max_attempts=3, retry_backoff=0)
        with self.assertRaises(Err):
            model.complete([Turn(role="user", content="x")], [])
        self.assertEqual(attempts["n"], 3)


class TestGeminiKeyResolution(unittest.TestCase):
    def test_no_key_anywhere_is_none(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(gemini_key_from_env())

    def test_google_api_key_wins_when_both_are_set(self) -> None:
        # The SDK's own precedence rule, matched deliberately.
        env = {"GEMINI_API_KEY": "a", "GOOGLE_API_KEY": "b"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(gemini_key_from_env(), "b")

    def test_a_blank_key_is_not_a_key(self) -> None:
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "   "}, clear=True):
            self.assertIsNone(gemini_key_from_env())



if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestGeminiConfigResolution(unittest.TestCase):
    """The pure decision: is a key configured, and which settings apply.

    Lives in chat.model rather than app.py because app.py is a Streamlit script
    and cannot be imported here -- `import app` resolves to the backend package,
    which is the name collision this repo already documents.
    """

    def test_no_secret_and_no_env_is_none(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(resolve_gemini_config(None))
            self.assertIsNone(resolve_gemini_config({}))

    def test_env_key_alone_is_enough(self) -> None:
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "from-env"}, clear=True):
            cfg = resolve_gemini_config(None)
        self.assertEqual(cfg["api_key"], "from-env")
        self.assertEqual(cfg["model"], DEFAULT_GEMINI_MODEL)

    def test_secret_key_wins_over_the_environment(self) -> None:
        env = {"GEMINI_API_KEY": "from-env"}
        table = {"api_key": "from-secret", "model": "gemini-x"}
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = resolve_gemini_config(table)
        self.assertEqual(cfg["api_key"], "from-secret")
        self.assertEqual(cfg["model"], "gemini-x")

    def test_a_blank_secret_key_falls_back_to_the_environment(self) -> None:
        env = {"GEMINI_API_KEY": "from-env"}
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = resolve_gemini_config({"api_key": "   "})
        self.assertEqual(cfg["api_key"], "from-env")

    def test_a_secret_model_without_a_key_is_not_enough(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(resolve_gemini_config({"model": "gemini-x"}))
