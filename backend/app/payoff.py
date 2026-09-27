"""Standard amortisation arithmetic for the payoff calculator.

Extracted from ``app.py`` so the same numbers are reachable from a tool call and
from the Streamlit widget, and so they can be tested at all. The formula used to
live inline in a widget branch, which meant the debt-trap branch had no test and
the chat layer would have had to reach into a rendering function to reuse it.

Nothing here is a prediction. A payoff estimate assumes a fixed rate and a
level monthly payment for the whole term, which real loans do not do: variable
rates, fees, insurance and missed payments all change the answer. The result is
labelled an estimate everywhere it is shown.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

# A payment below this many dollars is not a loan repayment, it is a rounding
# error, and dividing by it produces a payoff time in the millions of years.
_MIN_PAYMENT = 0.01
# Beyond this the annuity equation is no longer solvable: the payment does not
# cover the interest, so the balance grows instead of amortising.
_MAX_AMORTISING_APR = 500.0


@dataclass(frozen=True)
class PayoffResult:
    """Outcome of one amortisation estimate.

    ``status`` is one of:

    ``ok``
        The loan amortises. The other fields are populated.
    ``interest_not_covered``
        The monthly payment does not cover one month of interest, so the balance
        grows. This is the debt-trap case and it is a refusal, not an estimate:
        reporting a payoff time here would be the single most misleading thing
        this module could do.
    ``invalid_payment``
        The payment is zero or negative, so there is nothing to solve.
    """

    status: str
    principal: float
    apr: float
    payment: float
    monthly_rate: float
    monthly_interest: float
    months: int | None = None
    total_paid: float | None = None
    total_interest: float | None = None
    years: float | None = None
    interest_share: float | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict[str, object]:
        """JSON-ready form, for a tool result the model will read as data."""
        return asdict(self)


def monthly_interest(principal: float, apr: float) -> float:
    """Interest accruing in the first month. The number a payment must beat."""
    return principal * ((apr / 100.0) / 12.0)


def estimate_payoff(
    principal: float,
    apr: float,
    payment: float,
) -> PayoffResult:
    """Months to repay ``principal`` at ``apr`` paying ``payment`` per month.

    Solves the standard annuity equation,
    ``n = -ln(1 - rP/A) / ln(1 + r)``, and rounds up to whole months, because a
    loan is repaid in whole payments and rounding down understates the cost.
    """
    principal = float(principal)
    apr = float(apr)
    payment = float(payment)

    if principal < 0:
        raise ValueError("principal must not be negative")
    if not 0.0 <= apr <= _MAX_AMORTISING_APR:
        raise ValueError(f"apr must be between 0 and {_MAX_AMORTISING_APR}")
    if payment < _MIN_PAYMENT:
        return PayoffResult(
            status="invalid_payment",
            principal=principal,
            apr=apr,
            payment=payment,
            monthly_rate=(apr / 100.0) / 12.0,
            monthly_interest=monthly_interest(principal, apr),
        )

    rate = (apr / 100.0) / 12.0
    interest = principal * rate

    if rate > 0 and payment <= interest:
        # Debt trap. No amount of patience fixes this one, so it is reported as
        # a refusal rather than as a very large number of months.
        return PayoffResult(
            status="interest_not_covered",
            principal=principal,
            apr=apr,
            payment=payment,
            monthly_rate=rate,
            monthly_interest=interest,
        )

    if rate == 0:
        months = math.ceil(principal / payment)
    else:
        months = math.ceil(
            -math.log(1 - (rate * principal) / payment) / math.log(1 + rate)
        )
    # A zero-principal loan is fully repaid by the first payment.
    months = max(months, 1)

    total_paid = payment * months
    total_interest = total_paid - principal

    return PayoffResult(
        status="ok",
        principal=principal,
        apr=apr,
        payment=payment,
        monthly_rate=rate,
        monthly_interest=interest,
        months=months,
        total_paid=total_paid,
        total_interest=total_interest,
        years=round(months / 12.0, 1),
        interest_share=(total_interest / total_paid * 100) if total_paid > 0 else 0.0,
    )
