"""Know Your Lender — a Streamlit front end for the FinePrint analysis.

Three tools, deliberately kept apart because they answer different questions
from different data:

  1. Lender Complaint Profile  -- CFPB complaint patterns for one lender,
     scored against modelled payday peers. Reused from the FastAPI service via
     ``app.label_store`` so both surfaces read one committed artifact.
  2. Household Financial Context -- a survey-based estimate, described in
     survey terms. Not an eligibility determination.
  3. Loan Payoff Calculator      -- plain amortisation arithmetic.

Statistical behaviour is unchanged from the previous version: the grade band cut
points, the categorical casting contract, the loan arithmetic and the model
feature vector are all preserved. Only presentation and interaction changed.

Presentation notes that matter when editing this file:

* Custom components go through ``st.html``, not ``st.markdown``. ``st.html``
  does not parse Markdown or LaTeX, so a dollar amount renders as ``$10.00``
  rather than opening a maths span, and ``**`` never leaks through as literal
  asterisks. The previous version used ``st.write`` and produced both artefacts.
* All styling lives in ``kyl_theme.stylesheet()`` and is scoped by
  ``data-testid`` / ``role`` / ``aria-*``. Do not add generated emotion class
  names; they move between Streamlit releases.
* The theme in ``.streamlit/config.toml`` used to set ``primaryColor`` to
  ``#FFFFFF``, which made the selected tab and the primary button white on
  white. It is corrected there and mirrored in ``kyl_theme.TOKENS``.
"""

from __future__ import annotations

import html
import importlib.util
import math
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import xgboost as xgb

_BACKEND = Path(__file__).resolve().parent / "backend"

# The lender Safety Label is reused from the FastAPI service rather than
# reimplemented, so both surfaces render identical numbers off one committed
# artifact. label_store is standard-library only and imports nothing from its own
# package, so it is loaded straight from its file.
#
# It is deliberately NOT imported as `app.label_store`. This script is itself
# called app.py, and Streamlit's runtime registers the entrypoint in sys.modules
# under its own stem, so the name `app` is already taken by the script and is not
# a package. `from app.label_store import ...` therefore dies with
# "No module named 'app.label_store'; 'app' is not a package" -- and it dies only
# on the deployed runtime, because locally the backend package happens to win the
# name. Loading by path sidesteps the collision entirely.
_spec = importlib.util.spec_from_file_location(
    "kyl_label_store", _BACKEND / "app" / "label_store.py"
)
if _spec is None or _spec.loader is None:  # pragma: no cover
    raise ImportError(f"cannot load label_store from {_BACKEND}")
_label_store = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_label_store)

get_lender = _label_store.get_lender
lender_index = _label_store.lender_index

from kyl_theme import GRADE_STYLE, TOKENS, stylesheet  # noqa: E402

# --------------------------------------------------------------------------
# Data and model constants. Unchanged from the previous version on purpose.
# --------------------------------------------------------------------------

SNAP_MODEL_PATH = "snap_xgboost.json"

# Peer-anchored A-F bands, mirroring frontend/src/lib/grades.ts. Method C puts
# a typical modelled payday peer at exactly 50, so 50 is the C/D boundary; the
# remaining cuts sit in gaps in the observed distribution rather than at even
# intervals. Across all 2,410 dimension-scores in the committed artifact that
# gives A 18.3%, B 17.6%, C 34.7%, D 3.2%, E 5.8%, F 20.4%. Evenly spaced cuts
# would put 72.9% of every dimension in F while the model itself calls 91% of
# them indistinguishable from peers.
#
# These are relative, per-dimension bands. There is deliberately no overall
# grade: the five dimensions overlap, so one number would hide that.
GRADE_BANDS = [
    (65.0, "A", "Much more favorable than modeled payday peers"),
    (57.5, "B", "More favorable than modeled payday peers"),
    (50.0, "C", "About average for modeled payday peers"),
    (40.0, "D", "Somewhat less favorable than modeled payday peers"),
    (30.0, "E", "Less favorable than modeled payday peers"),
    (0.0, "F", "Much less favorable than modeled payday peers"),
]

COMPARISON_TEXT = {
    "more": "More of these complaints than typical peers",
    "fewer": "Fewer of these complaints than typical peers",
    "similar": "Too close to typical peers to tell",
}

# The complete category set for each categorical feature, in the order xgboost
# saw them at training time. Declared explicitly because a bare
# astype("category") on a one-row frame derives its categories from that single
# row, so a household aged 45-54 would be sent as category code 0 and silently
# route the prediction through the wrong branch of every categorical split.
# Same constant and same reasoning as backend/app/financial_impact.py.
CATEGORICAL_CATEGORIES = {
    "agecat": [1, 2, 3, 4, 5, 6, 7, 8],
    "PPEDUC": [1, 2, 3, 4, 5],
    "PPINCIMP": [1, 2, 3, 4, 5, 6, 7, 8, 9],
    "PPMARIT": [1, 2, 3, 4, 5],
    "PPMSACAT": [0, 1],
}

AGE_BANDS = ["18-24", "25-34", "35-44", "45-54", "55-64", "65-74", "75+", "75+"]
EDUCATION = [
    "Less than High School",
    "High School",
    "Associate's Degree",
    "Bachelor's Degree",
    "Graduate or Professional Degree",
]
INCOME = [
    "Less than $20,000",
    "$20,000 to $29,999",
    "$30,000 to $39,999",
    "$40,000 to $49,999",
    "$50,000 to $59,999",
    "$60,000 to $74,999",
    "$75,000 to $99,999",
    "$100,000 to $149,999",
    "$150,000 or more",
]
MARITAL = [
    "Married",
    "Widowed",
    "Divorced/Separated",
    "Never married",
    "Living with partner",
]
METRO = ["Yes", "No"]

LENDER_KEY = "kyl_lender"
# Search results shown at once. Small enough to stay above the fold, so the
# report card is never buried under a scroll box.
MAX_MATCHES = 6
HOUSEHOLD_FORM_KEY = "kyl_household_form"

# The official SNAP program page. The model is not this, and the copy says so;
# the link exists so a reader has somewhere authoritative to go.
SNAP_OFFICIAL = "https://www.fns.usda.gov/snap"


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def esc(value: object) -> str:
    """HTML-escape. Everything interpolated into st.html goes through this."""
    return html.escape(str(value), quote=True)


def plural(n: int, singular: str, plural_form: str | None = None) -> str:
    """'1 complaint' / '2 complaints'. Fixes the '1 complaints' defect."""
    word = singular if n == 1 else (plural_form or f"{singular}s")
    return f"{n:,} {word}"


def grade_for(score: float) -> tuple[str, str]:
    """Return ``(letter, descriptor)`` for a 0-100 score, clamping outliers."""
    clamped = max(0.0, min(100.0, float(score)))
    for minimum, letter, descriptor in GRADE_BANDS:
        if clamped >= minimum:
            return letter, descriptor
    return "F", GRADE_BANDS[-1][2]


def alert(kind: str, title: str, body: str) -> None:
    """A rendered alert.

    Uses ``st.html`` so dollar amounts are never treated as LaTeX and ``**``
    never appears literally. ``kind`` is danger | warning | info | success.
    """
    st.html(
        f'<div class="kyl-alert kyl-alert-{esc(kind)}" role="note">'
        f"<div><b>{esc(title)}</b> {esc(body)}</div></div>"
    )


def section_card(inner_html: str) -> None:
    st.html(f'<section class="kyl-card">{inner_html}</section>')


def _render_lender_report(label: dict) -> None:
    """Name, counts, evidence badge, five grade cards, methodology accordion."""
    # 1-3: identity, complaint count, evidence badge.
    section_card(
        '<div class="kyl-lender-head">'
        f'<span class="kyl-lender-name">{esc(label["name"])}</span>'
        f'<span class="kyl-badge">Evidence: {esc(label["evidence"])}</span></div>'
        f'<p class="kyl-meta">'
        f'<b>{esc(plural(label["n_complaints"], "complaint"))}</b> in this dataset'
        f" &middot; {esc(label['methodology']['direction'])}</p>"
    )

    # 4: the five grade cards.
    cards = []
    for slug, dim in label["dimensions"].items():
        letter, descriptor = grade_for(dim["score"])
        style = GRADE_STYLE[letter]
        pct = min(100.0, max(0.0, dim["score"]))

        facts = [("Complaints", f"{dim['complaints']:,}")]
        if dim.get("prevalence") is not None:
            facts.append(
                (
                    "Estimated rate",
                    f"{dim['prevalence'] * 100:.1f}%",
                )
            )
            facts.append(
                (
                    "90% interval",
                    f"{dim['prevalence_lo90'] * 100:.1f}–"
                    f"{dim['prevalence_hi90'] * 100:.1f}%",
                )
            )
        facts.append(("Verdict", COMPARISON_TEXT[dim["comparison"]]))

        fact_rows = "".join(
            f"<div><span>{esc(k)}</span><span>{esc(v)}</span></div>" for k, v in facts
        )

        # The scale is explicitly labelled at both ends with the peer reference
        # marked, because an unlabelled bar asserts nothing.
        scale = (
            '<div class="kyl-scale">'
            f'<div class="kyl-scale-track">'
            f'<span class="kyl-scale-fill" style="width:{pct:.1f}%;'
            f'background:{style["fg"]}"></span>'
            '<span class="kyl-scale-peer" style="left:50%"></span>'
            "</div>"
            '<div class="kyl-scale-legend">'
            "<span>0 &middot; least favorable</span>"
            "<span>peers sit at 50</span>"
            "<span>100 &middot; most</span>"
            "</div></div>"
        )

        # Native <details> disclosure: keyboard operable, no JS, and it only
        # expands when the reader asks, so nothing shifts on hover.
        details = (
            "<details><summary>View details</summary>"
            f'<p class="kyl-fine">Raw score {dim["score"]:.1f} of 100.'
            f' Modeled peer rate for this complaint type is'
            f' {dim.get("peer_rate", float("nan")) * 100:.2f}% of complaints'
            f" received by a modeled peer. Shrinkage pulls small samples toward"
            f" the middle, so an extreme score on thin evidence is not an extreme"
            f" lender.</p></details>"
        )

        cards.append(
            f'<article class="kyl-grade" style="--kyl-card:{style["bg"]};'
            f'--kyl-border:{style["edge"]};--kyl-edge:{style["fg"]}">'
            f'<h4 class="kyl-grade-name">{esc(dim["label"])}</h4>'
            '<div class="kyl-grade-row">'
            f'<span class="kyl-letter" style="color:{style["fg"]}">{letter}</span>'
            f'<span class="kyl-grade-word" style="color:{style["fg"]}">'
            f'{style["word"]}</span></div>'
            f'<p class="kyl-compare">{esc(descriptor)}</p>'
            f'<div class="kyl-facts">{fact_rows}</div>'
            f"{scale}{details}</article>"
        )

    st.html(f'<div class="kyl-grades">{"".join(cards)}</div>')

    # 5: methodology / disclaimer accordion.
    caveats = "".join(f"<li>{esc(c)}</li>" for c in label["methodology"]["caveats"])
    with st.expander("Methodology and limitations"):
        st.markdown(label["methodology"]["summary"])
        st.markdown(f'<ul class="kyl-list">{caveats}</ul>', unsafe_allow_html=True)
        st.markdown(
            f'<p class="kyl-fine">Method: {esc(label["method"])}. Grades are relative'
            " to modeled payday peers and are shown per dimension. There is no"
            " overall grade, because the five dimensions overlap and one number"
            " would hide that. The CFPB has not classified any lender as safe or"
            " unsafe, and neither does this model.</p>",
            unsafe_allow_html=True,
        )




def _render_household_result(age, education, income, marital, metro, size, children):
    data = {
        "agecat": AGE_BANDS.index(age) + 1,
        "PPEDUC": EDUCATION.index(education) + 1,
        "PPINCIMP": INCOME.index(income) + 1,
        "PPMARIT": MARITAL.index(marital) + 1,
        "PPMSACAT": 1 if metro == "Yes" else 0,
        "PPHHSIZE": size,
        "total_children": children,
        "child_ratio": children / size if size else 0.0,
    }
    frame = pd.DataFrame([data])
    for name, categories in CATEGORICAL_CATEGORIES.items():
        frame[name] = pd.Categorical(frame[name], categories=categories)

    booster = xgb.Booster()
    booster.load_model(SNAP_MODEL_PATH)
    rate = float(booster.predict(xgb.DMatrix(frame, enable_categorical=True))[0])

    pct = rate * 100
    if pct >= 65:
        band = "Higher strain"
        reading = (
            "Households with these characteristics more often reported receiving"
            " SNAP benefits in the survey than the modeled peer group."
        )
    elif pct >= 35:
        band = "Typical strain"
        reading = (
            "Households with these characteristics reported receiving SNAP benefits"
            " at roughly the rate of the modeled peer group."
        )
    else:
        band = "Lower strain"
        reading = (
            "Households with these characteristics less often reported receiving"
            " SNAP benefits in the survey than the modeled peer group."
        )

    section_card(
        '<p class="kyl-outcome-lab">Survey association</p>'
        f'<p class="kyl-outcome-val">{pct:.1f}%</p>'
        f'<p class="kyl-outcome-note"><b>{esc(band)}.</b> {esc(reading)}</p>'
    )

    section_card(
        "<h3>What this means</h3>"
        '<ul class="kyl-list">'
        "<li>It places a household like this one within a 2016 survey population"
        " of 6,394 US households.</li>"
        "<li>SNAP receipt is used as a proxy for financial strain, so a higher"
        " figure points to more strain, not to a benefit being available.</li>"
        "</ul>"
        "<h3>What this does not mean</h3>"
        '<ul class="kyl-list">'
        "<li>It is not an eligibility determination, and it cannot tell you"
        " whether you personally would qualify.</li>"
        "<li>It is not a forecast. Two households with identical answers can sit"
        " in very different circumstances.</li>"
        "<li>It says nothing about any lender and changes no complaint grade.</li>"
        "</ul>"
    )

    # Which factors carry the most weight, at the model level. This is a
    # property of the fitted model, not an attribution for this household, and
    # the copy says so.
    try:
        gains = booster.get_score(importance_type="gain")
        order = sorted(gains.items(), key=lambda kv: -kv[1])[:3]
        friendly = {
            "child_ratio": "children relative to household size",
            "total_children": "presence of children",
            "PPHHSIZE": "household size",
            "PPINCIMP": "household income band",
            "agecat": "age group",
            "PPEDUC": "education",
            "PPMARIT": "marital status",
            "PPMSACAT": "metro versus non-metro",
        }
        top = "".join(
            f"<li>{esc(friendly.get(k, k))}</li>" for k, _ in order
        )
        factors = (
            "<h3>Factors that matter most in this model</h3>"
            f'<ul class="kyl-list">{top}</ul>'
            '<p class="kyl-fine">These are the strongest splits across the whole'
            " fitted model, not a breakdown of this particular household. A tree"
            " model has no per-household attribution, so this should not be read"
            " as a list of reasons for the number above.</p>"
        )
        section_card(factors)
    except Exception:  # pragma: no cover - diagnostics only, never blocks output
        pass

    st.html(
        f'<p class="kyl-note">For an actual determination, eligibility is set by'
        f" your state agency. Official program information: "
        f'<a href="{esc(SNAP_OFFICIAL)}" target="_blank" rel="noopener noreferrer">'
        f"USDA Food and Nutrition Service — SNAP</a>.</p>"
    )




# --------------------------------------------------------------------------
# Page shell
# --------------------------------------------------------------------------

st.set_page_config(
    page_title="Know Your Lender",
    page_icon=":bar_chart:",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(stylesheet(), unsafe_allow_html=True)

# The one place a serif is used: the wordmark.
st.html(
    '<header style="margin:0 0 1.5rem">'
    '<p class="kyl-mark">Know Your Lender</p>'
    '<p class="kyl-tag">Three independent tools for payday-loan questions</p>'
    '<p class="kyl-lede">Explore CFPB complaint patterns, understand a household’s'
    " position within survey data, and estimate the cost and timeline of repaying a"
    " loan.</p>"
    "</header>"
)

lender_tab, household_tab, calculator_tab = st.tabs(
    [
        "Lender Complaint Profile",
        "Household Financial Context",
        "Loan Payoff Calculator",
    ]
)


# ==========================================================================
# 1. Lender Complaint Profile
# ==========================================================================
with lender_tab:
    st.html(
        '<div style="margin:1.5rem 0 1rem">'
        "<h2>Lender Complaint Profile</h2>"
        '<p class="kyl-note">See how a lender’s CFPB payday-loan complaint pattern'
        " compares with modeled peers. Complaint data reflects reported issues, not"
        " the total number of customers or an official safety determination.</p>"
        "</div>"
    )

    lenders = lender_index()

    picked_id = st.session_state.get(LENDER_KEY)

    # A real search field. live=True commits 250ms after typing stops, so results
    # narrow as you type without pressing Enter. Results are capped at
    # MAX_MATCHES and rendered as a short list, so nothing is buried under a
    # scroll box and no list is shown before the user has searched for anything.
    # There is no separate "change" control and no browse panel: this one field
    # is the only way in, and retyping is how you change lenders.
    query = st.text_input(
        "Search for a lender",
        placeholder="Start typing a lender name…",
        key=f"{LENDER_KEY}_query",
        live=True,
        type="default",
    )

    needle = query.strip().lower()
    matches = [r for r in lenders if needle in r["name"].lower()] if needle else []

    if needle and not matches:
        st.html(
            f'<p class="kyl-note" style="margin:.5rem 0 0">No lender matches'
            f" <b>{esc(query.strip())}</b>. Try a shorter fragment of the name.</p>"
        )
    elif matches:
        shown = matches[:MAX_MATCHES]
        st.html(
            f'<p class="kyl-note" style="margin:.6rem 0 .35rem">'
            + (
                f"{len(matches):,} match"
                f"{'es' if len(matches) != 1 else ''} — pick one:"
                if len(matches) > len(shown)
                else "Pick one:"
            )
            + "</p>"
        )
        for row in shown:
            if st.button(
                f"{row['name']}   ·   {plural(row['n_complaints'], 'complaint')}",
                key=f"{LENDER_KEY}_hit_{row['id']}",
                width="stretch",
                type="primary" if row["id"] == picked_id else "secondary",
            ):
                st.session_state[LENDER_KEY] = row["id"]
                st.rerun()

    if picked_id is None:
        section_card(
            "<h3>No lender selected</h3>"
            '<p class="kyl-note">Search for a lender above to see its complaint'
            " profile. Every grade is a comparison against modeled payday peers,"
            " not a safety verdict.</p>"
        )
    else:
        label = get_lender(picked_id)
        if label is None:
            section_card("<h3>Lender not found</h3>")
        else:
            _render_lender_report(label)


# ==========================================================================
# 2. Household Financial Context
# ==========================================================================
with household_tab:
    st.html(
        '<div style="margin:1.5rem 0 1rem">'
        "<h2>Household Financial Context</h2>"
        '<p class="kyl-note">This model compares your selections with patterns in'
        " survey data. It is not an official SNAP eligibility determination.</p>"
        "</div>"
    )

    input_col, result_col = st.columns([1, 1], gap="large")

    with input_col:
        with st.form(HOUSEHOLD_FORM_KEY, border=False):
            st.markdown("**Your household**")
            age = st.selectbox("Age group", AGE_BANDS, index=1)
            education = st.selectbox("Highest education", EDUCATION, index=3)
            income = st.selectbox("Household income", INCOME, index=4)
            marital = st.selectbox("Marital status", MARITAL, index=0)
            metro = st.selectbox("Live in a city or metro area", METRO, index=0)
            size = st.number_input(
                "People in household", min_value=1, max_value=20, value=3, step=1
            )
            children = st.number_input(
                "Children in the household", min_value=0, max_value=20, value=1, step=1
            )

            submitted = st.form_submit_button(
                "Generate estimate", type="primary", width="stretch"
            )

    with result_col:
        if not submitted:
            section_card(
                "<h3>What you will see</h3>"
                '<p class="kyl-note">Choose a household on the left and select'
                " <b>Generate estimate</b>. You will get a short plain-language"
                " reading of how a household with these characteristics sat in the"
                " CFPB National Financial Well-Being Survey, what that does and does"
                " not tell you, and which inputs carry the most weight in the"
                " model.</p>"
            )
        else:
            _render_household_result(age, education, income, marital, metro, size, children)


# ==========================================================================
# 3. Loan Payoff Calculator
# ==========================================================================
with calculator_tab:
    st.html(
        '<div style="margin:1.5rem 0 1rem">'
        "<h2>Loan Payoff Calculator</h2>"
        '<p class="kyl-note">Work out how long a loan takes to clear and what it'
        " costs. This is arithmetic on the numbers you enter; it is not a quote,"
        " an offer, or financial advice.</p>"
        "</div>"
    )

    loan_col, payoff_col = st.columns([1, 1], gap="large")

    with loan_col:
        principal = st.number_input(
            "Loan amount",
            min_value=1.0,
            max_value=10_000_000.0,
            value=1000.0,
            step=50.0,
            key="kyl_principal",
            format="%.2f",
        )
        apr = st.number_input(
            "Annual interest rate (APR)",
            min_value=0.0,
            max_value=500.0,
            value=24.0,
            step=0.5,
            key="kyl_apr",
            format="%.2f",
        )
        payment = st.number_input(
            "Monthly payment",
            min_value=0.01,
            max_value=10_000_000.0,
            value=50.0,
            step=5.0,
            key="kyl_payment",
            format="%.2f",
        )

    monthly_rate = (apr / 100.0) / 12.0
    monthly_interest = principal * monthly_rate

    with loan_col:
        # Always shown, so the number the payment must beat is never hidden.
        if monthly_interest > 0:
            st.html(
                f'<p class="kyl-note" style="margin:.35rem 0 0">Minimum payment to'
                f" cover this month’s interest: <b>${monthly_interest:,.2f}</b></p>"
            )
        else:
            st.html(
                '<p class="kyl-note" style="margin:.35rem 0 0">This loan accrues no'
                " monthly interest at an APR of 0%.</p>"
            )

    with payoff_col:
        if payment <= 0:
            alert("warning", "Check your payment.", "Enter a monthly payment above zero.")
        elif monthly_rate > 0 and payment <= monthly_interest:
            # Previously rendered through st.write, which turned the two dollar
            # amounts into a LaTeX span and left literal ** markers on screen.
            alert(
                "danger",
                "Debt trap warning:",
                f"your ${payment:,.2f} monthly payment does not cover the"
                f" ${monthly_interest:,.2f} in monthly interest. At this payment"
                " level the balance will grow rather than be paid off.",
            )
        else:
            if monthly_rate == 0:
                months = math.ceil(principal / payment)
            else:
                n_months = -math.log(
                    1 - (monthly_rate * principal) / payment
                ) / math.log(1 + monthly_rate)
                months = math.ceil(n_months)

            total_paid = payment * months
            total_interest = total_paid - principal
            years = round(months / 12.0, 1)
            interest_share = (total_interest / total_paid * 100) if total_paid > 0 else 0.0

            m1, m2 = st.columns(2)
            with m1:
                st.metric("Estimated payoff time", f"{months} months", delta=f"~{years} years")
                st.metric("Total amount paid", f"${total_paid:,.2f}")
            with m2:
                st.metric("Total interest", f"${total_interest:,.2f}")
                st.metric(
                    "Interest as share of payments", f"{interest_share:.1f}%"
                )

            if total_interest > 0:
                alert(
                    "info",
                    "Cost breakdown:",
                    f"{interest_share:.1f}% of everything you pay goes to interest"
                    f" rather than reducing the balance. On ${principal:,.2f} at"
                    f" {apr:.2f}% APR, paying ${payment:,.2f} a month clears the loan"
                    f" in {months} months.",
                )
            else:
                alert(
                    "success",
                    "No interest charged:",
                    f"at an APR of 0% this loan clears in {months} months with no"
                    " interest cost.",
                )

# --------------------------------------------------------------------------
# Footer
# --------------------------------------------------------------------------
st.html(
    '<footer class="kyl-foot">'
    "<p><b>Know Your Lender</b> draws on two public sources. The lender complaint"
    " profile is derived from CFPB consumer complaint data; the household estimate"
    " comes from the CFPB National Financial Well-Being Survey.</p>"
    "<p>Complaints are consumer-submitted reports and do not necessarily indicate"
    " verified wrongdoing. Complaint volume indicates how much evidence supports a"
    " grade, not how many customers a lender has or how much misconduct it commits."
    " A lender is not penalised for having more complaints.</p>"
    "<p>Grades are relative comparisons against modeled payday peers, shown per"
    " dimension, and there is no overall score. The household estimate is a survey"
    " association from 2016, not an eligibility determination, a forecast, or"
    " advice. The loan calculator is arithmetic on your inputs.</p>"
    "</footer>"
)
