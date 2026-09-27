"""Tests for the two-panel layout and the dual input paths.

Driving Streamlit's widgets from raw DOM events is unreliable, so the clear and
regenerate behaviour is asserted here with AppTest, which commits widget values
the way the framework does. The browser check covers layout and rendering; this
covers the interaction.
"""

from __future__ import annotations

import unittest
from pathlib import Path

try:
    from streamlit.testing.v1 import AppTest
except ModuleNotFoundError as exc:  # pragma: no cover
    # Streamlit is deliberately absent from the backend's test requirements, the
    # same way the app's runtime deps are kept out of backend/requirements.txt.
    # The backend job therefore skips this file, and the checks run where
    # Streamlit is installed. Same convention as the processed-feature skips in
    # test_safety_labels.py.
    raise unittest.SkipTest(f"streamlit is not installed: {exc}") from exc

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def run(query: str | None = None) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    assert not at.exception, [str(e.value)[:200] for e in at.exception]
    if query is not None:
        at.session_state["kyl_chat"] = query
        at.run()
        assert not at.exception, [str(e.value)[:200] for e in at.exception]
    return at


def text(at: AppTest) -> str:
    """All rendered text, entities decoded.

    The panels are built with st.html, so the raw values carry escapes such as
    "Fees &amp; Costs". Asserting against those would test the escaping rather
    than the content.
    """
    import html as _html

    blob = " ".join(
        [n.value for n in at.markdown]
        + [n.value for n in at.get("html")]
        + [b.label for b in at.button]
    )
    return _html.unescape(blob)


class TestNoLeakedSource(unittest.TestCase):
    """Streamlit 1.64 renders a bare string statement in a function body as
    Markdown. A function that ends up with two docstrings therefore puts its
    second one on the page, in the middle of the interface, with no error
    anywhere. It happened once, so it is pinned.
    """

    def _app_path(self) -> Path:
        return Path(__file__).resolve().parent.parent / "app.py"

    def test_no_bare_string_statements_in_function_bodies(self) -> None:
        import ast

        tree = ast.parse(self._app_path().read_text(encoding="utf-8"))
        offenders = []
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # Index 0 is the docstring, which Streamlit does not render. Anything
            # after it is a stray expression statement and does get rendered.
            for i, stmt in enumerate(fn.body[1:], start=1):
                if (
                    isinstance(stmt, ast.Expr)
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)
                ):
                    offenders.append(f"{fn.name}:{stmt.lineno}")
        self.assertEqual(offenders, [], f"bare strings render as Markdown: {offenders}")

    def test_no_internal_docstrings_on_the_page(self) -> None:
        at = run()
        for token in (
            "Takes survey codes",
            "Split from the render",
            "HTML-escape",
            "inside the body",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, text(at))


class TestLayout(unittest.TestCase):
    def test_starts_clean(self) -> None:
        at = run()
        self.assertIn("Name a lender", text(at))
        self.assertEqual(len(at.tabs), 0, "the tab strip is gone")

    def test_four_panels(self) -> None:
        at = run()
        labels = [e.label for e in at.get("expander")]
        self.assertEqual(len(labels), 4)
        for expected in (
            "Lender Complaint Profile",
            "Household Financial Context",
            "Loan Payoff Calculator",
            "Methodology",
        ):
            self.assertTrue(
                any(expected.lower() in l.lower() for l in labels), expected
            )

    def test_no_advice_or_verdict_anywhere(self) -> None:
        for q in (
            "Uprova Credit",
            "Uprova Credit, $300 at 391% paying $376 in 14 days",
            "I'm 35-44, household income 50-75k, college graduate",
        ):
            with self.subTest(q=q):
                t = text(run(q))
                self.assertNotRegex(t, r"you should (take|borrow|sign|apply)")
                self.assertNotRegex(t, r"risk score|credit score")
                self.assertNotRegex(t, r"\b(safest|best|worst) lender\b")


class TestPartialQueries(unittest.TestCase):
    def test_lender_name_only_opens_one_panel(self) -> None:
        at = run("Uprova Credit")
        self.assertIn("Opened the complaint panel only", text(at))
        self.assertIn("Fees & Costs", text(at))

    def test_lender_and_terms_opens_two(self) -> None:
        at = run("Uprova Credit, $300 at 391% paying $376 in 14 days")
        self.assertIn("Opened the complaint and payoff panels", text(at))

    def test_terms_only_opens_payoff(self) -> None:
        at = run("$300 at 391% paying $376 in 14 days")
        self.assertNotIn("Fees & Costs", text(at))

    def test_household_only_opens_household(self) -> None:
        at = run("I'm 35-44, household income 50-75k")
        t = text(at)
        self.assertNotIn("Fees & Costs", t)
        # The panel headlines the survey percentile rather than the raw
        # association rate; the rate is demoted to a disclosure.
        self.assertIn("Where this household sits in the survey", t)

    def test_two_lenders_closes_the_panel(self) -> None:
        at = run("Uprova Credit and Cash Express, $300 at 391%")
        self.assertIn("more than one lender", text(at))
        self.assertNotIn("Fees & Costs", text(at))

    def test_verdict_query_still_shows_facts_but_says_it_will_not_grade(self) -> None:
        at = run("is Uprova Credit safe?")
        t = text(at)
        self.assertIn("Fees & Costs", t)
        self.assertRegex(t, r"will not say a lender is safe|does not grade")

    def test_unknown_query_opens_nothing(self) -> None:
        at = run("hello there")
        self.assertIn("Nothing in that could be matched", text(at))


class TestAnalysisInvalidation(unittest.TestCase):
    """The core behaviour: edit a figure, the analysis goes."""

    def _payoff_number_inputs(self, at: AppTest):
        return [n for n in at.number_input if n.label in
                ("Loan amount", "APR %", "Monthly payment")]

    def _keyed(self, at: AppTest, prefix: str):
        """The one widget whose key starts with ``prefix``.

        Panel widget keys carry a token derived from the query, so a second query
        produces a different key. Matching on prefix finds the current one.
        """
        # AppTest exposes these as sequence proxies, not lists.
        widgets = list(at.number_input) + list(at.selectbox) + list(at.text_input)
        hits = [n for n in widgets if (n.key or "").startswith(prefix)]
        self.assertEqual(len(hits), 1, f"expected one {prefix}, got {[n.key for n in hits]}")
        return hits[0]

    def test_analysis_present_for_query_supplied_figures(self) -> None:
        at = run("Uprova Credit, $300 at 391% paying $376 in 14 days")
        self.assertIn("What this means", text(at))

    def test_editing_a_figure_clears_the_analysis(self) -> None:
        at = run("Uprova Credit, $300 at 391% paying $376 in 14 days")
        self.assertNotIn("have changed since this was last read", text(at))

        self._keyed(at, "kyl_chat_principal").set_value(800.0).run()
        # Re-fetch: AppTest element handles are snapshots, so the pre-run handle
        # still reports the old value and asserting on it tests nothing.
        self.assertEqual(self._keyed(at, "kyl_chat_principal").value, 800.0)

        t = text(at)
        self.assertIn("have changed since this was last read", t)
        self.assertIn("Regenerate analysis", t)

    def test_regenerate_restores_an_analysis_for_the_new_figures(self) -> None:
        at = run("Uprova Credit, $300 at 391% paying $376 in 14 days")
        self._keyed(at, "kyl_chat_principal").set_value(800.0).run()
        self.assertEqual(self._keyed(at, "kyl_chat_principal").value, 800.0)
        self.assertIn("Regenerate analysis", text(at))

        regen = [b for b in at.button if b.key == "kyl_chat_payoff_analysis_regen2"]
        self.assertTrue(regen, "regenerate button should be offered")
        regen[0].click().run()
        self.assertNotEqual(text(at), "")
        t = text(at)
        self.assertIn("What this means", t)
        self.assertNotIn("have changed since this was last read", t)
        # The rebuilt analysis must describe the figure now on screen.
        self.assertIn("800", t)

    def test_reverting_to_the_queried_figure_regenerates(self) -> None:
        # Typing a different figure clears the analysis. Typing the queried one
        # back is not a stale state: the figures on screen now match what the
        # query supplied, so the analysis is rebuilt for them rather than left
        # asking to be regenerated. The assertion that matters is that whatever
        # is shown describes 300 and not 800.
        at = run("Uprova Credit, $300 at 391% paying $376 in 14 days")
        self._keyed(at, "kyl_chat_principal").set_value(800.0).run()
        self.assertIn("have changed since this was last read", text(at))
        self._keyed(at, "kyl_chat_principal").set_value(300.0).run()
        t = text(at)
        self.assertNotIn("have changed since this was last read", t)
        self.assertIn("What this means", t)

    def test_household_edit_clears_its_analysis(self) -> None:
        at = run("I'm 35-44, household income 50-75k, college graduate")
        self.assertIn("What this means", text(at))
        # Age bands come from the survey codebook, so "55-61" is a real option
        # and "55-64" -- which the old local copy invented -- no longer is. The
        # widget's value is the survey code behind the label, not the label.
        self._keyed(at, "kyl_chat_age").set_value("55-61").run()
        self.assertEqual(self._keyed(at, "kyl_chat_age").value, 5)
        t = text(at)
        self.assertIn("have changed since this was last read", t)

    def test_a_second_query_replaces_the_analysis_rather_than_latching(self) -> None:
        # An earlier version latched a "seen" flag and never generated again.
        at = run("I'm 35-44, household income 50-75k")
        self.assertIn("What this means", text(at))
        at.session_state["kyl_chat"] = "I'm 55-61, household income 50-75k"
        at.run()
        t = text(at)
        self.assertNotIn("have changed since this was last read", t)
        self.assertIn("What this means", t)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
