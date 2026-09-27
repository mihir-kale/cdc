"""Tests for the generated interpretation on a lender page.

The contract is deliberately unusual: the model writes the prose, and the
deterministic text is the floor rather than a fallback of last resort. These
tests pin both halves, because the interesting failures are all cases where one
half is supposed to catch the other.
"""

from __future__ import annotations

import unittest

from app import label_store
from app.chat import guard
from app.chat.model import ScriptedModel
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
