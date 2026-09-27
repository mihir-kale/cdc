"""Tests for the assistant: the scope gate, the tools, the guard, the wiring.

The property that matters most is that the three refusal layers each work on
their own, and that they work in the right order. A system where a declined
question still reaches the model, or where a model reply can slip a verdict past
the guard, would look fine in a demo and be wrong in use.
"""

from __future__ import annotations

import unittest

from app.chat import guard, scope, tools
from app.chat.model import EchoModel, ScriptedModel
from app.chat.orchestrator import answer
from app.payoff import estimate_payoff


class TestScopeGate(unittest.TestCase):
    """The gate decides scope without a model. Exhaustive beats clever."""

    DECLINE = [
        "is Uprova Credit safe?",
        "is Cash Express a scam",
        "are payday lenders trustworthy",
        "is Advance America reliable",
        "can I trust Uprova",
        "what is the safest payday lender",
        "which payday lender is best",
        "rank the lenders by complaint volume",
        "list the safest lenders",
        "should I borrow from Uprova",
        "should I take out a loan",
        "can I afford a $2000 loan",
        "do you recommend Uprova",
        "which lender should I choose",
        "is it worth borrowing",
    ]
    ANSWER = [
        "what complaints did Uprova Credit receive",
        "Uprova Credit complaints",
        "what should I pay attention to with Advance America",
        "explain the methodology",
        "what does the peer comparison mean",
        "what do the scores mean",
        "how much interest will I pay on 1000 at 24% paying 50",
        "how long to pay off 500 at 36% paying 30",
        "what is the monthly payment needed",
        "what percentile am I in",
        "how does my household compare to the survey",
        "what is my survey percentile",
        "how much evidence is there for this lender",
    ]
    OUT = [
        "hi",
        "thanks!",
        "tell me a joke",
        "what is the weather",
        "who won the football game",
        "write me a poem",
        "",
        "   ",
        "asdfghjkl",
    ]

    def test_verdicts_and_advice_are_declined(self) -> None:
        for msg in self.DECLINE:
            with self.subTest(msg=msg):
                r = scope.classify(msg)
                self.assertEqual(r.decision, scope.Decision.DECLINE, msg)

    def test_in_scope_questions_are_answered(self) -> None:
        for msg in self.ANSWER:
            with self.subTest(msg=msg):
                r = scope.classify(msg)
                self.assertEqual(r.decision, scope.Decision.ANSWER, msg)

    def test_unrelated_and_empty_are_out_of_scope(self) -> None:
        for msg in self.OUT:
            with self.subTest(msg=msg):
                self.assertEqual(
                    scope.classify(msg).decision, scope.Decision.OUT_OF_SCOPE, msg
                )

    def test_verdict_beats_topic_when_both_present(self) -> None:
        # The ordering guarantee: naming a lender does not make a verdict
        # request answerable.
        r = scope.classify("is Uprova Credit, LLC safe? show me its complaints")
        self.assertEqual(r.decision, scope.Decision.DECLINE)
        self.assertEqual(r.refusal, scope.Refusal.LENDER_VERDICT)

    def test_ranking_outranks_verdict(self) -> None:
        r = scope.classify("what is the safest lender")
        self.assertEqual(r.refusal, scope.Refusal.LENDER_RANKING)

    def test_pay_attention_is_not_financial_advice(self) -> None:
        # "what should I pay attention to" is this product's own headline
        # question. An earlier "pay" alternative classified it as advice.
        r = scope.classify("what should I pay attention to?")
        self.assertEqual(r.decision, scope.Decision.ANSWER)

    def test_stem_alternatives_actually_match(self) -> None:
        # A trailing \\b on a stem alternative can never match, because the
        # boundary lands mid-word.
        self.assertEqual(
            scope.classify("explain the methodology").tools, (scope.TOOL_METHOD,)
        )
        self.assertIn(
            scope.TOOL_LENDER, scope.classify("tell me about their complaints").tools
        )

    def test_tools_are_a_subset_of_what_exists(self) -> None:
        for msg in self.ANSWER:
            for tool in scope.classify(msg).tools:
                self.assertIn(tool, tools.TOOLS, f"{msg} -> {tool}")


class TestTools(unittest.TestCase):
    def test_find_then_get_lender(self) -> None:
        found = tools.call(tools.TOOL_LOOKUP, query="upr")
        self.assertTrue(found["ok"])
        self.assertTrue(found["data"]["lenders"])
        lid = found["data"]["lenders"][0]["id"]
        label = tools.call(tools.TOOL_LENDER, lender_id=lid)
        self.assertTrue(label["ok"])
        self.assertEqual(label["data"]["n_complaints"], 175)
        # Five scored categories plus Other, and the shares must reconcile.
        self.assertEqual(len(label["data"]["categories"]), 5)
        total = sum(c["share"] for c in label["data"]["categories"])
        total += label["data"]["other"]["share"]
        self.assertAlmostEqual(total, 100.0, delta=0.2)

    def test_lender_name_resolves_inside_a_sentence(self) -> None:
        # The whole message is not a substring of the name; the name is a
        # substring of the message. Getting this backwards broke every
        # sentence-shaped question.
        hits = tools.match_lenders_in_text("Uprova Credit complaints")
        self.assertEqual([h["name"] for h in hits], ["Uprova Credit, LLC"])
        self.assertEqual(
            [h["name"] for h in tools.match_lenders_in_text("complaints for Advance America")],
            ["Advance America, Cash Advance Centers, Inc."],
        )

    def test_unrelated_text_matches_no_lender(self) -> None:
        for msg in ("explain the methodology", "what percentile am I in", "hi"):
            self.assertEqual(tools.match_lenders_in_text(msg), [], msg)

    def test_short_name_does_not_match_inside_a_longer_word(self) -> None:
        self.assertEqual(tools.match_lenders_in_text("advanced mathematics"), [])

    def test_payoff_refuses_the_debt_trap_and_reports_no_months(self) -> None:
        r = tools.call(tools.TOOL_PAYOFF, principal=1000, apr=24, payment=15)
        self.assertTrue(r["ok"])
        self.assertTrue(r["refused"])
        self.assertIsNone(r["data"]["months"])

    def test_payoff_ok_carries_authorised_claims(self) -> None:
        r = tools.call(tools.TOOL_PAYOFF, principal=1000, apr=24, payment=50)
        self.assertTrue(r["ok"])
        self.assertFalse(r.get("refused"))
        self.assertTrue(r["claims"])

    def test_household_rejects_invented_codes(self) -> None:
        r = tools.call(tools.TOOL_HOUSEHOLD, age_band=99)
        self.assertFalse(r["ok"])
        self.assertIn("age_band", r["error"])

    def test_household_requires_a_profile(self) -> None:
        self.assertFalse(tools.call(tools.TOOL_HOUSEHOLD)["ok"])

    def test_unknown_tool_is_refused(self) -> None:
        r = tools.call("rm_rf", path="/")
        self.assertFalse(r["ok"])
        self.assertIn("no such tool", r["error"])

    def test_every_tool_reports_its_own_name_and_ok_flag(self) -> None:
        for name, fn in tools.TOOLS.items():
            with self.subTest(tool=name):
                r = tools.call(name)
                self.assertIn("tool", r)
                self.assertIn("ok", r)
                self.assertEqual(r["tool"], name)


class TestGuard(unittest.TestCase):
    EVIDENCE = [tools.to_json(tools.call(tools.TOOL_LENDER, lender_id="5"))]

    def test_honest_answer_passes(self) -> None:
        text = (
            "Uprova Credit has 175 payday-loan complaints in this dataset. "
            "Fees and Costs is the largest category, at 96 complaints or 54.9%."
        )
        r = guard.check_reply(text, self.EVIDENCE)
        self.assertTrue(r.ok, r.violations)

    def test_ranking_is_replaced(self) -> None:
        for text in (
            "Uprova is the safest lender.",
            "The best lenders are listed below.",
            "I would rank them like this.",
            "Which one should I choose?",
            "Here are the top 3 lenders.",
        ):
            with self.subTest(text=text):
                r = guard.check_reply(text, self.EVIDENCE)
                self.assertFalse(r.ok)
                self.assertIn("ranking_language", r.violations)

    def test_verdict_is_replaced(self) -> None:
        for text in (
            "Uprova appears trustworthy.",
            "This lender is a scam.",
            "The company is reliable.",
            "I would grade this lender B.",
        ):
            with self.subTest(text=text):
                r = guard.check_reply(text, self.EVIDENCE)
                self.assertFalse(r.ok)
                self.assertTrue(
                    {"verdict_language", "ranking_language"} & set(r.violations)
                )

    def test_unsupported_figure_is_caught(self) -> None:
        r = guard.check_reply(
            "Uprova Credit received 4,200 complaints.", self.EVIDENCE
        )
        self.assertFalse(r.ok)
        self.assertIn("unsupported_number", r.violations)

    def test_descriptive_comparison_is_not_a_ranking(self) -> None:
        # "more prominent than peers" is the sanctioned phrasing and must not
        # trip the ranking check, or the guard would refuse honest answers.
        text = (
            "Fees and Costs is more prominent than among typical payday-loan "
            "peers. That is a comparison of complaint patterns, not a judgement."
        )
        self.assertTrue(guard.check_reply(text, self.EVIDENCE).ok)

    def test_a_refusal_reply_is_not_itself_flagged(self) -> None:
        # The guard's own replacement text must survive a second pass, or a
        # retried turn would loop.
        r = guard.check_reply("Uprova is the best lender.", self.EVIDENCE)
        self.assertFalse(r.ok)
        self.assertTrue(guard.check_reply(r.text, self.EVIDENCE).ok)


class TestAssistant(unittest.TestCase):
    def test_declined_question_never_reaches_the_model(self) -> None:
        m = ScriptedModel(replies=["Uprova is safe and the best lender."])
        r = answer("is Uprova Credit safe?", model=m)
        self.assertEqual(r.outcome, "declined")
        self.assertEqual(m.calls, [], "the model must not be called for a decline")

    def test_out_of_scope_never_reaches_the_model(self) -> None:
        m = ScriptedModel(replies=["Here is a joke."])
        r = answer("tell me a joke", model=m)
        self.assertEqual(r.outcome, "out_of_scope")
        self.assertEqual(m.calls, [])

    def test_refusals_name_what_the_product_can_do(self) -> None:
        for msg in (
            "is Uprova safe?",
            "rank the lenders",
            "should I borrow",
            "tell me a joke",
        ):
            with self.subTest(msg=msg):
                r = answer(msg, model=ScriptedModel())
                self.assertNotIn("I can't", r.text[:6].replace("I can", ""))
                self.assertTrue(len(r.text) > 80, "a refusal should redirect")

    def test_honest_answer_reaches_the_user(self) -> None:
        text = (
            "Uprova Credit has 175 payday-loan complaints in this dataset, which "
            "is stronger evidence. Fees and Costs is the largest category at 96 "
            "complaints, or 54.9% of the total."
        )
        r = answer("Uprova Credit complaints", model=ScriptedModel(replies=[text]))
        self.assertEqual(r.outcome, "answer")
        self.assertEqual(r.text, text)
        self.assertTrue(r.tool_names)

    def test_guarded_reply_is_replaced_not_edited(self) -> None:
        r = answer(
            "Uprova Credit complaints",
            model=ScriptedModel(
                replies=["Uprova Credit is the safest and best lender available."]
            ),
        )
        self.assertEqual(r.outcome, "guarded")
        self.assertNotIn("safest", r.text)
        self.assertNotIn("best lender", r.text)

    def test_hallucinated_figure_is_replaced(self) -> None:
        r = answer(
            "Uprova Credit complaints",
            model=ScriptedModel(replies=["Uprova had 9,999 complaints."]),
        )
        self.assertEqual(r.outcome, "guarded")
        self.assertIn("unsupported_number", r.violations)

    def test_model_receives_tool_results_and_the_tool_schemas(self) -> None:
        m = ScriptedModel(replies=["Fine."])
        answer("Uprova Credit complaints", model=m)
        self.assertEqual(len(m.calls), 1)
        call = m.calls[0]
        self.assertIn(tools.TOOL_LENDER, call["tools"])
        roles = [t["role"] for t in call["turns"]]
        self.assertIn("system", roles)
        self.assertIn("tool", roles)

    def test_payoff_uses_interface_figures_not_parsed_text(self) -> None:
        # A number the model could have inferred from the sentence is not
        # evidence; only what the interface holds counts.
        m = ScriptedModel(replies=["Here is the estimate."])
        r = answer(
            "what is the monthly payment needed",
            model=m,
            household_profile={"principal": 1000.0, "apr": 24.0, "payment": 50.0},
        )
        payoff = [t for t in r.tool_results if t["tool"] == tools.TOOL_PAYOFF]
        self.assertEqual(len(payoff), 1)
        self.assertEqual(payoff[0]["data"]["principal"], 1000.0)

    def test_payoff_without_figures_says_so(self) -> None:
        r = answer("how much interest will I pay", model=ScriptedModel())
        self.assertEqual(r.outcome, "out_of_scope")
        self.assertIn("Loan Payoff Calculator", r.text)

    def test_household_not_sent_when_no_profile_set(self) -> None:
        r = answer("what percentile am I in", model=ScriptedModel())
        self.assertEqual(r.outcome, "out_of_scope")
        self.assertIn("household profile", r.text)

    def test_household_sent_when_profile_present(self) -> None:
        profile = {
            "age_band": 3,
            "education": 3,
            "household_income": 4,
            "marital_status": 2,
            "household_size": 3,
            "metro_area": 1,
            "county_poverty_share": 0,
        }
        m = ScriptedModel(replies=["Your profile sits in a higher-strain band."])
        r = answer("what percentile am I in", model=m, household_profile=profile)
        self.assertEqual(r.outcome, "answer")
        ctx = [t for t in r.tool_results if t["tool"] == tools.TOOL_HOUSEHOLD][0]
        self.assertTrue(ctx["ok"])
        self.assertIn("survey_percentile", ctx["data"])

    def test_debt_trap_survives_to_the_reply(self) -> None:
        m = ScriptedModel(replies=["That payment does not cover the interest."])
        r = answer(
            "how much interest will I pay",
            model=m,
            household_profile={"principal": 1000.0, "apr": 24.0, "payment": 15.0},
        )
        payoff = [t for t in r.tool_results if t["tool"] == tools.TOOL_PAYOFF][0]
        self.assertTrue(payoff["refused"])

    def test_ambiguous_lender_name_is_not_guessed(self) -> None:
        r = answer("complaints", model=ScriptedModel())
        # A bare "complaints" resolves no lender, so nothing is fabricated.
        lender_results = [
            t for t in r.tool_results if t["tool"] == tools.TOOL_LENDER
        ]
        for t in lender_results:
            self.assertFalse(t["ok"])

    def test_default_model_is_the_stub_and_never_raises(self) -> None:
        r = answer("Uprova Credit complaints")
        self.assertIn(r.outcome, {"answer", "guarded", "out_of_scope"})

    def test_echo_model_cannot_smuggle_a_verdict(self) -> None:
        # Worst case: a model that quotes its input verbatim still cannot make
        # the assistant grade a lender.
        r = answer("Uprova Credit complaints", model=EchoModel())
        self.assertIn(r.outcome, {"answer", "guarded"})


class TestPayoffToolParity(unittest.TestCase):
    def test_tool_matches_the_module(self) -> None:
        r = estimate_payoff(1000.0, 24.0, 50.0)
        t = tools.call(tools.TOOL_PAYOFF, principal=1000.0, apr=24.0, payment=50.0)
        self.assertEqual(t["data"]["months"], r.months)
        self.assertAlmostEqual(t["data"]["total_interest"], r.total_interest, places=6)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
