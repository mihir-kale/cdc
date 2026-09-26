"""Placeholder lender data.

These three records are hardcoded fakes. They exist only so the team can confirm
that the frontend and backend talk to each other. Replace this module with real
lender data once the CFPB ingestion work starts.
"""

from app.models import Lender

LENDERS: list[Lender] = [
    Lender(
        id="placeholder-cash",
        name="Placeholder Cash Advance",
        states=["NC", "SC"],
        product="Payday loan",
        apr_range="391% - 1,500%",
        complaint_count=0,
    ),
    Lender(
        id="example-loans",
        name="Example Loans LLC",
        states=["NC", "VA", "GA"],
        product="Installment loan",
        apr_range="150% - 300%",
        complaint_count=0,
    ),
    Lender(
        id="sample-financial",
        name="Sample Financial Services",
        states=["NC", "SC", "VA"],
        product="Personal loan",
        apr_range="8% - 36%",
        complaint_count=0,
    ),
]
