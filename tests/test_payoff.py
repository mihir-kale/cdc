"""Tests for the extracted amortisation arithmetic.

The debt-trap branch is the one that matters: it is the only path where the
module refuses to produce a number, and it used to live untested inside a
Streamlit widget.
"""

from __future__ import annotations

import math
import unittest

from app.payoff import PayoffResult, estimate_payoff, monthly_interest


class TestPayoff(unittest.TestCase):
    def test_zero_interest_is_principal_over_payment(self) -> None:
        r = estimate_payoff(principal=1200.0, apr=0.0, payment=100.0)
        self.assertTrue(r.ok)
        self.assertEqual(r.months, 12)
        self.assertEqual(r.total_paid, 1200.0)
        self.assertEqual(r.total_interest, 0.0)
        self.assertEqual(r.interest_share, 0.0)

    def test_annuity_matches_the_closed_form(self) -> None:
        principal, apr, payment = 1000.0, 24.0, 50.0
        r = estimate_payoff(principal, apr, payment)
        rate = (apr / 100.0) / 12.0
        expected = -math.log(1 - (rate * principal) / payment) / math.log(1 + rate)
        # Rounded up to whole months, so at most one month of slack.
        self.assertLessEqual(r.months - expected, 1.0)
        self.assertGreater(r.months, expected)

    def test_rounds_up_so_a_partial_final_payment_is_not_free(self) -> None:
        # 1000 at 24% repaid at 333.34/mo is 3.003 months, so 4 payments.
        r = estimate_payoff(principal=1000.0, apr=24.0, payment=333.34)
        self.assertEqual(r.months, 4)

    def test_totals_are_internally_consistent(self) -> None:
        r = estimate_payoff(principal=2500.0, apr=18.5, payment=120.0)
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.total_paid, r.payment * r.months, places=6)
        self.assertAlmostEqual(
            r.total_interest, r.total_paid - r.principal, places=6
        )
        self.assertAlmostEqual(
            r.interest_share, r.total_interest / r.total_paid * 100, places=6
        )
        self.assertAlmostEqual(r.years, round(r.months / 12.0, 1), places=6)

    def test_interest_not_covered_refuses_instead_of_answering(self) -> None:
        # 1000 at 24% accrues 20.00/mo; paying 15 never touches the principal.
        r = estimate_payoff(principal=1000.0, apr=24.0, payment=15.0)
        self.assertEqual(r.status, "interest_not_covered")
        self.assertFalse(r.ok)
        # The dangerous part is what it must NOT contain.
        self.assertIsNone(r.months)
        self.assertIsNone(r.total_paid)
        self.assertIsNone(r.years)
        # But the user still needs the threshold that explains the refusal.
        self.assertAlmostEqual(r.monthly_interest, 20.0, places=6)

    def test_payment_exactly_covering_interest_is_still_a_trap(self) -> None:
        # Boundary: 1200 at 12% is exactly 12.00 a month, so paying 12.00 leaves
        # the balance flat forever and never retires any principal.
        r = estimate_payoff(principal=1200.0, apr=12.0, payment=12.0)
        self.assertAlmostEqual(r.monthly_interest, 12.0, places=6)
        self.assertEqual(r.status, "interest_not_covered")

    def test_one_cent_above_interest_amortises(self) -> None:
        r = estimate_payoff(principal=1200.0, apr=12.0, payment=12.01)
        self.assertTrue(r.ok)
        self.assertGreater(r.months, 0)

    def test_non_positive_payment_is_invalid_not_a_crash(self) -> None:
        for bad in (0.0, -50.0, 0.001):
            r = estimate_payoff(principal=1000.0, apr=24.0, payment=bad)
            self.assertEqual(r.status, "invalid_payment")
            self.assertIsNone(r.months)

    def test_zero_principal_is_repaid_immediately(self) -> None:
        r = estimate_payoff(principal=0.0, apr=24.0, payment=50.0)
        self.assertTrue(r.ok)
        self.assertEqual(r.months, 1)

    def test_out_of_range_inputs_raise(self) -> None:
        with self.assertRaises(ValueError):
            estimate_payoff(principal=-1.0, apr=24.0, payment=50.0)
        with self.assertRaises(ValueError):
            estimate_payoff(principal=100.0, apr=-1.0, payment=50.0)
        with self.assertRaises(ValueError):
            estimate_payoff(principal=100.0, apr=5000.0, payment=50.0)

    def test_monthly_interest_helper_agrees_with_result(self) -> None:
        r = estimate_payoff(principal=3000.0, apr=36.0, payment=200.0)
        self.assertAlmostEqual(
            r.monthly_interest, monthly_interest(3000.0, 36.0), places=9
        )

    def test_to_dict_is_json_ready(self) -> None:
        r: PayoffResult = estimate_payoff(1000.0, 24.0, 50.0)
        d = r.to_dict()
        self.assertEqual(d["status"], "ok")
        self.assertIsInstance(d["months"], int)
        for v in d.values():
            self.assertIsInstance(v, (int, float, str, type(None)))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
