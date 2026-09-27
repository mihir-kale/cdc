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
import json
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

from kyl_theme import TOKENS, stylesheet  # noqa: E402

dataset_summary = _label_store.dataset_summary

_HOUSEHOLD_CONTEXT_PATH = _BACKEND / "app" / "generated" / "financial_impact_context.json"
try:
    _HOUSEHOLD_CONTEXT = json.loads(_HOUSEHOLD_CONTEXT_PATH.read_text(encoding="utf-8"))
except (OSError, ValueError):  # pragma: no cover
    _HOUSEHOLD_CONTEXT = {}

# --------------------------------------------------------------------------
# Data and model constants. Unchanged from the previous version on purpose.
# --------------------------------------------------------------------------

SNAP_MODEL_PATH = "snap_xgboost.json"

COMPARISON_TEXT = {
    "more": "More complaints than typical peers",
    "fewer": "Fewer complaints than typical peers",
    "similar": "Similar to typical peers",
}

# What each comparison does and does not license us to say. The "similar" case
# is the overwhelming majority of dimensions, and it is a statement that the
# model found nothing rather than a middling score, so it is worded as such
# rather than as a lukewarm verdict.
COMPARISON_QUALIFIER = {
    "more": (
        "Available complaint data suggests this type of complaint makes up a"
        " larger share of this lender's complaints than among typical payday-loan"
        " peers."
    ),
    "fewer": (
        "Available complaint data suggests this type of complaint makes up a"
        " smaller share of this lender's complaints than among typical payday-loan"
        " peers."
    ),
    "similar": (
        "Available complaint data does not clearly distinguish this lender from"
        " typical payday-loan peers."
    ),
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


def _complaint_evidence_stats() -> dict[str, float] | None:
    """How much the complaint data actually supports, computed from the artifact.

    These are the uncomfortable numbers, and they belong in front of a reader
    rather than in a notebook. They are recomputed on every run so they cannot
    drift away from the artifact they describe.

    Deliberately reported as a median interval *width* in percentage points and
    not as a ratio to the point estimate: where the estimated prevalence is near
    zero, a ratio explodes arithmetically and would overstate the uncertainty.
    """
    try:
        artifact = _label_store.load_artifact()
    except Exception:  # pragma: no cover - artifact is committed
        return None

    dims = [
        value
        for lender in artifact["lenders"]
        for value in lender["dimensions"].values()
    ]
    if not dims:  # pragma: no cover
        return None

    total = len(dims)
    similar = sum(1 for d in dims if d["comparison"] == "similar")
    thin = sum(1 for d in dims if d["complaints"] < 10)
    complaints = sorted(d["complaints"] for d in dims)
    mid = len(complaints) // 2
    median_complaints = (
        complaints[mid]
        if len(complaints) % 2
        else (complaints[mid - 1] + complaints[mid]) / 2
    )
    widths = sorted(
        (d["prevalence_hi90"] - d["prevalence_lo90"]) * 100 for d in dims
    )
    return {
        "dimensions": total,
        "similar_pct": 100 * similar / total,
        "thin_pct": 100 * thin / total,
        "median_complaints": median_complaints,
        "median_interval_width": widths[mid],
    }


def _render_lender_report(label: dict) -> None:
    """One report card, one row per dimension, verdict first.

    There is deliberately no letter grade. A grade says "this lender is good",
    and nothing here supports that: the score is a peer-relative posterior whose
    median dimension rests on zero observed complaints, and for 91% of
    dimensions the model itself reports that it cannot distinguish the lender
    from its peers. Banding that into A-F manufactured certainty the analysis
    does not contain.

    What each row does claim is narrower and supportable: whether this type of
    complaint makes up a larger, smaller, or indistinguishable share of this
    lender's payday complaints than among modeled peers. The Method C score is
    kept, because it preserves information and gives the scale continuity, but
    it is subordinate to the verdict and to the evidence behind it.
    """
    rows = []
    for dim in label["dimensions"].values():
        verdict = COMPARISON_TEXT[dim["comparison"]]
        qualifier = COMPARISON_QUALIFIER[dim["comparison"]]
        pct = min(100.0, max(0.0, dim["score"]))

        facts = [
            ("Raw score", f"{dim['score']:.1f} of 100"),
            ("Complaints in this category", f"{dim['complaints']:,}"),
            ("Share of lender's complaints", f"{dim['prevalence'] * 100:.1f}%"),
            (
                "90% credible interval",
                f"{dim['prevalence_lo90'] * 100:.1f}"
                f"\u2013{dim['prevalence_hi90'] * 100:.1f}%",
            ),
            ("Modeled peer rate", f"{dim.get('peer_rate', 0.0) * 100:.2f}%"),
        ]
        dl = "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in facts)

        scale = (
            '<div class="kyl-scale">'
            '<div class="kyl-scale-track">'
            f'<span class="kyl-scale-fill" style="width:{pct:.1f}%"></span>'
            '<span class="kyl-scale-peer" style="left:50%"></span>'
            "</div>"
            '<div class="kyl-scale-legend">'
            "<span>0</span><span>modeled peers sit at 50</span><span>100</span>"
            "</div></div>"
        )

        rows.append(
            '<li class="kyl-rowcard" tabindex="0" '
            f'aria-label="{esc(dim["label"])}: {esc(verdict)}.">'
            f'<p class="kyl-rowcard-name">{esc(dim["label"])}</p>'
            '<div class="kyl-rowcard-main">'
            f'<p class="kyl-rowcard-verdict">{esc(verdict)}</p>'
            f"{scale}</div>"
            '<p class="kyl-rowcard-meta">'
            f'Score <b>{dim["score"]:.0f}</b> / 100'
            f' &middot; {esc(label["evidence"])}</p>'
            f'<p class="kyl-rowcard-qualifier">{esc(qualifier)}</p>'
            f'<div class="kyl-rowcard-detail"><dl>{dl}</dl>'
            "<p>Shrinkage pulls small samples toward the middle, so a score near"
            " 50 on little data is mostly the prior rather than a finding about"
            " this lender.</p></div>"
            "</li>"
        )

    complaints = esc(plural(label["n_complaints"], "CFPB payday complaint"))
    st.html(
        '<article class="kyl-report">'
        '<header class="kyl-report-head"><div>'
        f'<h2 class="kyl-report-name">{esc(label["name"])}</h2>'
        f'<p class="kyl-meta" style="margin:.25rem 0 0">{complaints}</p>'
        "</div>"
        f'<span class="kyl-badge">{esc(label["evidence"])}</span>'
        "</header>"
        f'<ul style="list-style:none;margin:0;padding:0">{"".join(rows)}</ul>'
        "</article>"
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

    year = _HOUSEHOLD_CONTEXT.get("survey_year", "a national")
    section_card(
        '<p class="kyl-outcome-lab">Survey association</p>'
        f'<p class="kyl-outcome-val">{pct:.1f}%</p>'
        f'<p class="kyl-outcome-note"><b>{esc(band)}.</b> {esc(reading)}</p>'
        '<p class="kyl-note" style="margin-top:.7rem">A survey association from'
        f" {esc(year)}, not an eligibility determination and not a personal"
        " forecast. What that means, and what it does not, is in the Methodology"
        " tab.</p>"
    )
    st.html(
        '<p class="kyl-note">For an actual determination, eligibility is set by'
        " your state agency. Official program information: "
        f'<a href="{esc(SNAP_OFFICIAL)}" target="_blank" rel="noopener noreferrer">'
        "USDA Food and Nutrition Service &mdash; SNAP</a>.</p>"
    )

def _render_methodology() -> None:
    """Everything about how the numbers are produced and what they cannot mean.

    Deliberately kept out of the three product tabs. Each of those answers one
    question and should read as a clean answer to it; the qualifications belong
    in one place a reader can choose to open.

    The uncomfortable statistics lead. They are the reason the interface is
    worded the way it is, and burying them would make the hedging look like a
    disclaimer rather than as the finding.
    """
    st.html(
        '<div style="margin:1.5rem 0 1rem">'
        "<h2>Methodology</h2>"
        '<p class="kyl-note">How each figure is produced, what it supports, and'
        " where it stops.</p></div>"
    )

    stats = _complaint_evidence_stats()

    if stats:
        st.html(
            '<section class="kyl-card">'
            "<h3>What the complaint data can and cannot support</h3>"
            '<p class="kyl-note">We set out to rate payday lenders from public'
            " complaint data. For most dimensions it does not support a"
            " distinction, and the interface is built to say so rather than to"
            " paper over it.</p>"
            '<dl class="kyl-stats">'
            f"<dt>Comparisons that cannot distinguish a lender from its peers"
            f"</dt><dd>{stats['similar_pct']:.1f}%</dd>"
            f"<dt>Dimensions resting on fewer than 10 complaints</dt>"
            f"<dd>{stats['thin_pct']:.1f}%</dd>"
            f"<dt>Median complaints behind a single dimension score</dt>"
            f"<dd>{stats['median_complaints']:.0f}</dd>"
            f"<dt>Median width of the 90% credible interval</dt>"
            f"<dd>{stats['median_interval_width']:.0f} percentage points</dd>"
            "</dl>"
            f'<p class="kyl-fine">Across all {int(stats["dimensions"]):,}'
            " lender-dimension comparisons in the dataset. The median dimension"
            " carries no observed complaints at all, so its score is almost"
            " entirely the shrinkage prior rather than a finding about the"
            " lender. This is why there is no letter grade anywhere in this"
            " interface: a grade would assert a difference the data does not"
            " support.</p>"
            "</section>"
        )

    left, right = st.columns(2, gap="large")

    with left:
        summary = dataset_summary()
        methodology = summary["methodology"]

        st.markdown("#### Lender Complaint Profile")
        st.markdown(methodology["summary"])
        st.markdown(
            '<p class="kyl-note">Each dimension is scored 0&ndash;100 by Method C:'
            " a Beta-Binomial posterior for the lender's complaint rate, referenced"
            " to the fitted peer population for that complaint type. A typical peer"
            " sits at <b>50</b>, which is the tick marked on each scale."
            " Statistical shrinkage pulls thin samples toward that reference, so a"
            " score near 50 usually means little data rather than typical"
            " behaviour.</p>",
            unsafe_allow_html=True,
        )
        st.markdown(
            '<p class="kyl-note">Each row reports one of three verdicts &mdash;'
            " more complaints than typical peers, fewer, or similar &mdash; and"
            " that verdict is the model's own, not a presentational choice. The"
            " score is shown beneath it to preserve the information, but it is"
            " model output on a peer-relative scale, not a grade, and it is not a"
            " quality ranking of the lender. The CFPB has not classified any"
            " lender as safe or unsafe, and neither does this model.</p>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "**Evidence strength** describes how much complaint data supports the"
            " scores for a lender as a whole, not how good or bad that lender is."
            " More complaints usually means more customers, not more misconduct."
        )
        bands = "".join(
            f"<li>{esc(b['label'])} &mdash; {b['min_complaints']}+ complaints</li>"
            for b in sorted(
                methodology["evidence_bands"], key=lambda b: b["min_complaints"]
            )
        )
        st.markdown(f"<ul>{bands}</ul>", unsafe_allow_html=True)
        st.markdown("**Caveats**")
        for caveat in methodology["caveats"]:
            st.markdown(f"- {caveat}")
        st.markdown(
            f'<p class="kyl-fine">Method: {esc(summary["method"])}. Dataset:'
            f' {esc(summary["lender_count"])} lenders,'
            f' {esc(summary["total_complaints"])} complaints. The five dimensions'
            " overlap, which is why they are reported separately and never"
            " combined into a single figure.</p>",
            unsafe_allow_html=True,
        )

    with right:
        ctx = _HOUSEHOLD_CONTEXT
        st.markdown("#### Household Financial Context")
        if ctx:
            st.markdown(
                f'<p class="kyl-note">A gradient-boosted classifier over the'
                f' {esc(ctx["households_modelled"])} households in the'
                f' {esc(ctx["survey"])} ({esc(ctx["survey_year"])}) that estimates'
                f' the survey item &ldquo;{esc(ctx["target"])}&rdquo; as a proxy for'
                f' financial strain. Weighted holdout ROC-AUC'
                f' <b>{ctx["weighted_roc_auc"]:.4f}</b> on an 80/20 stratified'
                f' split, seed {esc(ctx["seed"])}.</p>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<p class="kyl-note">SNAP receipt is a proxy for strain, not a'
                f' benefit calculation. The figure is an association measured'
                f' against a {esc(ctx["survey_year"])} survey and is easy to'
                " over-read as a personal forecast. It is not an eligibility"
                " determination.</p>",
                unsafe_allow_html=True,
            )
            st.markdown("**Caveats**")
            for caveat in ctx.get("caveats", []):
                st.markdown(f"- {caveat}")

        st.markdown("#### Loan Payoff Calculator")
        st.markdown(
            '<p class="kyl-note">Standard amortisation. Monthly interest is'
            " principal &times; APR / 12; payoff time solves the standard annuity"
            " equation and is rounded up to a whole month. It is arithmetic on the"
            " numbers entered &mdash; not a quote, an offer, a rate comparison, or"
            " financial advice, and it ignores fees, missed payments and any rate"
            " change.</p>",
            unsafe_allow_html=True,
        )

        st.markdown("#### Two models, not one")
        st.markdown(
            '<p class="kyl-note">This app scores with an eight-feature prototype.'
            " The FastAPI service behind the production interface serves a"
            " nine-feature model that also uses county poverty share and scores"
            " marginally higher. The two are not interchangeable and their figures"
            " should not be quoted for one another.</p>",
            unsafe_allow_html=True,
        )

        st.markdown("#### Sources")
        st.markdown(
            '<ul class="kyl-list">'
            "<li>CFPB consumer complaint database, payday loan products.</li>"
            "<li>CFPB National Financial Well-Being Survey, public-use file.</li>"
            '<li>Official SNAP program information:'
            f' <a href="{esc(SNAP_OFFICIAL)}" target="_blank"'
            f' rel="noopener noreferrer">USDA Food and Nutrition Service</a>.</li>'
            "</ul>",
            unsafe_allow_html=True,
        )
        st.markdown(
            '<p class="kyl-fine">Complaints are consumer-submitted reports and do'
            " not necessarily indicate verified wrongdoing. Complaint volume is"
            " used to communicate evidence strength; a lender is not penalised for"
            " having more complaints, because lender-level customer and loan-volume"
            " denominators are not available.</p>",
            unsafe_allow_html=True,
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

lender_tab, household_tab, calculator_tab, methodology_tab = st.tabs(
    [
        "Lender Complaint Profile",
        "Household Financial Context",
        "Loan Payoff Calculator",
        "Methodology",
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

    # Search on the left, report on the right, so a profile and the control that
    # produced it are visible at the same time and neither pushes the other down
    # the page. Streamlit stacks the columns on narrow screens by itself.
    search_col, report_col = st.columns([1, 2], gap="large")

    with search_col:
        # A real search field. live=True commits 250ms after typing stops, so
        # results narrow as the user types with no Enter and no dropdown to open.
        # Capped at MAX_MATCHES, nothing shown before searching, and this one
        # field is the only way in: retyping is how you change lenders.
        query = st.text_input(
            "Search for a lender",
            placeholder="Start typing a lender name…",
            key=f"{LENDER_KEY}_query",
            live=True,
        )
        needle = query.strip().lower()
        matches = [r for r in lenders if needle in r["name"].lower()] if needle else []

        if needle and not matches:
            st.html(
                f'<p class="kyl-note" style="margin:.5rem 0 0">No lender matches'
                f" <b>{esc(query.strip())}</b>. Try a shorter fragment.</p>"
            )
        elif matches:
            shown = matches[:MAX_MATCHES]
            caption = (
                f"{len(matches):,} matches — pick one"
                if len(matches) > len(shown)
                else "Pick one"
            )
            st.html(f'<p class="kyl-note" style="margin:.6rem 0 .35rem">{caption}</p>')
            for row in shown:
                if st.button(
                    f"{row['name']}   ·   {plural(row['n_complaints'], 'complaint')}",
                    key=f"{LENDER_KEY}_hit_{row['id']}",
                    width="stretch",
                    type="primary" if row["id"] == picked_id else "secondary",
                ):
                    st.session_state[LENDER_KEY] = row["id"]
                    st.rerun()

    with report_col:
        if picked_id is None:
            section_card(
                "<h3>No lender selected</h3>"
                '<p class="kyl-note">Search for a lender to see its complaint'
                " profile. Each row is one complaint type, compared against modeled"
                " payday peers. Hover a row for the numbers behind the verdict."
                "</p>"
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
        '<p class="kyl-note">Estimated payoff time and total cost for a loan.</p>' 
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


# --------------------------------------------------------------------------
# Footer
# --------------------------------------------------------------------------
st.html(
    '<footer class="kyl-foot">'
    "Know Your Lender &middot; CFPB consumer complaint data and the CFPB National"
    " Financial Well-Being Survey &middot; figures are peer-relative comparisons"
    " and survey associations, not official determinations &middot; see the"
    " Methodology tab.</footer>"
)


# ==========================================================================
# 4. Methodology
# ==========================================================================
with methodology_tab:
    _render_methodology()
