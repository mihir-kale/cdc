import math
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import xgboost as xgb

# The lender Safety Label is reused from the FastAPI service rather than
# reimplemented, so both surfaces render byte-identical numbers off one
# committed artifact. label_store is standard-library only, so this adds no
# dependency to the Streamlit app. It resolves the artifact relative to its own
# file, so the working directory does not matter.
sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))
from app.label_store import dataset_summary, get_lender, lender_index

# Peer-anchored A-F bands, mirroring frontend/src/lib/grades.ts. Method C puts a
# typical modelled payday peer at exactly 50, so 50 is the C/D boundary; the
# other cuts sit in gaps in the observed distribution rather than at even
# intervals. Across all 2,410 dimension-scores that gives A 18.3%, B 17.6%,
# C 34.7%, D 3.2%, E 5.8%, F 20.4%. Evenly spaced cuts would put 72.9% of every
# dimension in F while the model calls 91% of them indistinguishable from peers.
#
# These are relative and per-dimension. There is deliberately no overall grade,
# because the five dimensions overlap, and no red/green: the CFPB has classified
# no lender as safe or unsafe, so the letter and the descriptor carry the
# meaning. Keep in sync with grades.ts if either changes.
GRADE_BANDS = [
    (65.0, "A", "Much more favorable than peers"),
    (57.5, "B", "More favorable than peers"),
    (50.0, "C", "About average for peers"),
    (40.0, "D", "Somewhat less favorable than peers"),
    (30.0, "E", "Less favorable than peers"),
    (0.0, "F", "Much less favorable than peers"),
]

COMPARISON_TEXT = {
    "more": "More of these complaints than typical payday peers",
    "fewer": "Fewer of these complaints than typical payday peers",
    "similar": "Too close to typical payday peers to tell",
}

MAX_RESULTS = 25

# Session-state key for the lender picker. Declared here because the candidate
# list is rebuilt on every keystroke, and the widget's stored value has to be
# reconciled against it before the widget is created.
LENDER_PICK_KEY = "fp_lender_choice"

# Report-card styling. One hue, six steps: the shade tracks the band and the
# letter carries the meaning. Deliberately not red/green -- the CFPB has not
# classified any lender as safe or unsafe, so a traffic light would assert
# something the data cannot support. Detail is hidden until hover so the card
# reads as five grades at a glance.
REPORT_CARD_CSS = """
<style>
.fp-card-head{display:flex;align-items:baseline;justify-content:space-between;
  gap:1rem;flex-wrap:wrap;margin:.25rem 0 .1rem}
.fp-card-name{font-size:1.45rem;font-weight:700;color:#111827;letter-spacing:-.01em}
.fp-card-meta{font-size:.8rem;color:#6b7280;white-space:nowrap}
.fp-row{display:flex;align-items:center;gap:.75rem;padding:.45rem 0;
  border-bottom:1px solid #f3f4f6;font-size:.82rem;color:#6b7280}
.fp-row:last-of-type{border-bottom:none}
.fp-evidence{flex:1 1 auto;min-width:0}
.fp-bar{flex:0 0 34%;height:.4rem;background:#f3f4f6;border-radius:999px;overflow:hidden}
.fp-bar span{display:block;height:100%;background:#6366f1;border-radius:999px}
.fp-tiles{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));
  gap:.6rem;margin:.9rem 0 .2rem;align-items:start}
.fp-tile{border:1px solid #e5e7eb;border-radius:.6rem;padding:.85rem .4rem .7rem;
  text-align:center;background:#fff;transition:border-color .12s,box-shadow .12s}
.fp-tile:hover{border-color:#6366f1;box-shadow:0 1px 8px rgba(79,70,229,.14)}
.fp-tile-name{font-size:.63rem;line-height:1.25;color:#6b7280;margin-top:.45rem;
  text-transform:uppercase;letter-spacing:.04em}
.fp-letter{font-size:2.1rem;line-height:1;font-weight:700}
.fp-what{font-size:.68rem;line-height:1.3;margin-top:.3rem;min-height:2.4em}
.fp-detail{visibility:hidden;opacity:0;max-height:0;overflow:hidden;
  transition:opacity .12s;margin-top:.5rem;padding-top:.5rem;
  border-top:1px dashed #e5e7eb;font-size:.68rem;line-height:1.45;color:#4b5563;
  text-align:left}
/* :focus mirrors :hover so the numbers are reachable by keyboard and by tap.
   Hover alone would hide them from anyone on a phone, or anyone tabbing. */
.fp-tile:hover .fp-detail,.fp-tile:focus .fp-detail,
.fp-tile:focus-within .fp-detail{visibility:visible;opacity:1;max-height:14rem}
.fp-tile:hover .fp-what,.fp-tile:focus .fp-what{visibility:hidden}
.fp-tile:focus{outline:2px solid #6366f1;outline-offset:2px}
.fp-k{color:#9ca3af}
.fp-foot{margin-top:.9rem;padding-top:.7rem;border-top:1px solid #e5e7eb;
  font-size:.72rem;color:#6b7280;line-height:1.5}
</style>
"""

# Shade per band, light for the weakest. Paired with a readable text colour so
# the letter keeps its contrast on the lighter steps.
BAND_SHADE = {
    "A": ("#e0e7ff", "#3730a3"),
    "B": ("#c7d2fe", "#3730a3"),
    "C": ("#eef2ff", "#4338ca"),
    "D": ("#e0e7ff", "#4338ca"),
    "E": ("#f5f3ff", "#4f46e5"),
    "F": ("#faf5ff", "#5b21b6"),
}


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_report_card(label: dict) -> None:
    """Five grades at a glance; per-grade numbers on hover."""
    st.markdown(REPORT_CARD_CSS, unsafe_allow_html=True)

    tiles = []
    for slug, dim in label["dimensions"].items():
        letter, descriptor = grade_for(dim["score"])
        bg, fg = BAND_SHADE[letter]
        comparison = COMPARISON_TEXT[dim["comparison"]]
        detail = (
            f'<div class="fp-detail">'
            f'<span class="fp-k">Score</span> {dim["score"]:.1f} of 100'
            f' &middot; peer reference 50<br>'
            f'<span class="fp-k">Complaints</span> {dim["complaints"]:,}<br>'
            f'<span class="fp-k">Estimated rate</span> {dim["prevalence"] * 100:.1f}%'
            f' <span class="fp-k">(90% credible interval</span> '
            f'{dim["prevalence_lo90"] * 100:.1f}&ndash;{dim["prevalence_hi90"] * 100:.1f}%<span class="fp-k">)</span><br>'
            f'<span class="fp-k">vs peers</span> {_esc(comparison)}'
            f"</div>"
        )
        tiles.append(
            f'<div class="fp-tile" tabindex="0" '
            f'aria-label="{_esc(dim["label"])}: grade {letter}, {_esc(descriptor)}" '
            f'title="{_esc(comparison)}">'
            f'<div class="fp-letter" style="color:{fg}">{letter}</div>'
            f'<div class="fp-tile-name">{_esc(dim["label"])}</div>'
            f'<div class="fp-what">{_esc(descriptor)}</div>'
            f"{detail}</div>"
        )

    rows = []
    for dim in label["dimensions"].values():
        pct = min(100.0, max(0.0, dim["score"]))
        rows.append(
            f'<div class="fp-row"><span class="fp-evidence">'
            f'{_esc(COMPARISON_TEXT[dim["comparison"]])}</span>'
            f'<span class="fp-bar"><span style="width:{pct:.0f}%"></span></span></div>'
        )

    st.markdown(
        f'<div class="fp-card-head">'
        f'<span class="fp-card-name">{_esc(label["name"])}</span>'
        f'<span class="fp-card-meta">{label["n_complaints"]:,} CFPB payday complaints'
        f' &middot; {_esc(label["evidence"])}</span></div>'
        f'<div class="fp-tiles">{"".join(tiles)}</div>'
        f'<div>{"".join(rows)}</div>'
        f'<div class="fp-foot">Grades are per dimension, and there is no overall grade: '
        f'the five overlap, so one number would hide that. Each letter is a band on a '
        f'shrunk estimate relative to modeled peers, not a verdict &mdash; the CFPB has '
        f'classified no lender as safe or unsafe. Hover a tile for its numbers.'
        f'</div>',
        unsafe_allow_html=True,
    )


def grade_for(score: float) -> tuple[str, str]:
    """Return (letter, descriptor) for a 0-100 score. Out-of-range is clamped."""
    clamped = max(0.0, min(100.0, float(score)))
    for minimum, letter, descriptor in GRADE_BANDS:
        if clamped >= minimum:
            return letter, descriptor
    return "F", GRADE_BANDS[-1][2]


st.set_page_config(
    page_title="PayWatch", 
    page_icon=":clapper:", 
    layout="wide"
    )

st.title("PayWatch")

st.caption(
    "Two independent analyses, neither derived from the other: a CFPB complaint profile for a lender, and a survey position for a household."
)

lender_tab, household_tab, calculator_tab = st.tabs(
    ["Lender Safety Label", "Household Financial Context", "Loan Payoff Calculator"]
)

# ---------------------------------------------------------------- LENDER
with lender_tab:
    st.header("Payday Loan Safety Label")
    st.caption(
        "Each dimension compares this lender\u2019s CFPB complaint pattern with modeled "
        "payday-loan peers. Hover a grade for the numbers behind it."
    )

    summary = dataset_summary()
    all_lenders = lender_index()
    total = len(all_lenders)

    search_col, sort_col = st.columns([3, 1])
    with search_col:
        query = st.text_input(
            f"Search {total} lenders",
            placeholder="Start typing a lender name\u2026",
            label_visibility="collapsed",
        )
    with sort_col:
        order = st.selectbox(
            "Order",
            ["Most complaints", "Name (A\u2013Z)", "Fewest complaints"],
            label_visibility="collapsed",
        )

    needle = query.strip().lower()
    if needle:
        matches = [r for r in all_lenders if needle in r["name"].lower()]
    else:
        matches = list(all_lenders)

    if order == "Name (A\u2013Z)":
        matches.sort(key=lambda r: r["name"].lower())
    elif order == "Fewest complaints":
        matches.sort(key=lambda r: r["n_complaints"])
    else:
        matches.sort(key=lambda r: -r["n_complaints"])

    if not matches:
        st.info(f"No lender matches \u201c{query.strip()}\u201d. Try a shorter fragment.")
    else:
        shown = matches[:MAX_RESULTS]
        if not needle:
            st.caption(
                f"Suggested: the {len(shown)} most-complained of {total}. "
                "Type to search all of them."
            )
        elif len(matches) > len(shown):
            st.caption(f"Showing {len(shown)} of {len(matches):,} matches. Keep typing to narrow.")

        # A list of clickable rows rather than a selectbox. The candidate set
        # changes on every keystroke and every sort change, and a selectbox
        # whose stored value falls out of its own options raises and is left
        # dead -- which is what made the list look like it stopped populating.
        # Buttons carry stable keys, so the selection survives any reordering,
        # and the suggestions are visible instead of hidden in a dropdown.
        picked = st.session_state.get(LENDER_PICK_KEY)
        if picked is None:
            picked = shown[0]["id"]
            st.session_state[LENDER_PICK_KEY] = picked

        with st.container(height=340):
            for row in shown:
                if st.button(
                    f"{row['name']}   ·   {row['n_complaints']:,} complaints",
                    key=f"{LENDER_PICK_KEY}_{row['id']}",
                    width="stretch",
                    type="primary" if row["id"] == picked else "secondary",
                ):
                    st.session_state[LENDER_PICK_KEY] = row["id"]
                    picked = row["id"]
                    st.rerun()

        render_report_card(get_lender(picked))

# ------------------------------------------------------------- HOUSEHOLD
with household_tab:
    st.header('SNAP Eligibility Predictor')

    # Load model
    model = xgb.Booster()
    model.load_model("snap_xgboost.json")

    # Mapping Dictionaries
    agecat_map = {
        "18-24": 1, "25-34": 2, "35-44": 3, "45-54": 4,
        "55-61": 5, "62-69": 6, "70-74": 7, "75+": 8,
    }
    ppeduc_map = {
        "Less than High School": 1, "High School": 2, "Associate's Degree": 3,
        "Bachelor's Degree": 4, "Graduate or Professional Degree": 5,
    }
    ppincimp_map = {
        "Less than $20,000": 1, "$20,000 to $29,999": 2, "$30,000 to $39,999": 3,
        "$40,000 to $49,999": 4, "$50,000 to $59,999": 5, "$60,000 to $74,999": 6,
        "$75,000 to $99,999": 7, "$100,000 to $149,999": 8, "$150,000 or more": 9,
    }
    ppmarit_map = {
        "Married": 1, "Widowed": 2, "Divorced/Separated": 3,
        "Never married": 4, "Living with partner": 5,
    }

    # The complete category set for each categorical feature, in the order xgboost
    # saw them at training time. Declared explicitly because a bare
    # astype("category") on a one-row frame derives its categories from that single
    # row, so a household aged 45-54 would be sent as category code 0 and silently
    # route the prediction through the wrong branches. Same constant and same
    # reasoning as backend/app/financial_impact.py.
    CATEGORICAL_CATEGORIES = {
        "agecat": [1, 2, 3, 4, 5, 6, 7, 8],
        "PPEDUC": [1, 2, 3, 4, 5],
        "PPINCIMP": [1, 2, 3, 4, 5, 6, 7, 8, 9],
        "PPMARIT": [1, 2, 3, 4, 5],
        "PPMSACAT": [0, 1],
    }

    # Layout Columns
    col1, col2 = st.columns([3, 2], gap="large")

    with col1:
        st.subheader("Input Details")

        agecat_selected = st.selectbox(
            "Age Group",
            ["18-24", "25-34", "35-44", "45-54", "55-61", "62-69", "70-74", "75+"]
        )
        ppeduc_selected = st.selectbox(
            "What is your maximum level of education?",
            ["Less than High School", "High School", "Associate's Degree", "Bachelor's Degree", "Graduate or Professional Degree"]
        )
        ppincimp_selected = st.selectbox(
            "Household Income",
            ["Less than $20,000", "$20,000 to $29,999", "$30,000 to $39,999", "$40,000 to $49,999", "$50,000 to $59,999", "$60,000 to $74,999", "$75,000 to $99,999", "$100,000 to $149,999", "$150,000 or more"]
        )
        ppmarit_selected = st.selectbox(
            "Marital Status",
            ["Married", "Widowed", "Divorced/Separated", "Never married", "Living with partner"]
        )
        ppmsacat_selected = st.selectbox("Are you in a city?", ["Yes", "No"])

        c1, c2 = st.columns(2)
        with c1:
            pphhsize = st.number_input("Household Size", min_value=1, value=1)
        with c2:
            total_children = st.number_input("Total Children", min_value=0, value=0)

        # Convert inputs
        child_ratio = total_children / pphhsize
        agecat = agecat_map[agecat_selected]
        ppeduc = ppeduc_map[ppeduc_selected]
        ppincimp = ppincimp_map[ppincimp_selected]
        ppmarit = ppmarit_map[ppmarit_selected]
        ppmsacat = 1 if ppmsacat_selected == "Yes" else 0

    with col2:
        st.subheader("Model Prediction")

        # Styled Card Container for Prediction Results
        with st.container(border=True):
            st.write("Click below to run inference on the selected features.")
            predict_btn = st.button("Generate Prediction", type="primary", use_container_width=True)

            st.divider()

            if predict_btn:
                data = {
                    "agecat": agecat,
                    "PPEDUC": ppeduc,
                    "PPINCIMP": ppincimp,
                    "PPMARIT": ppmarit,
                    "PPMSACAT": ppmsacat,
                    "PPHHSIZE": pphhsize,
                    "total_children": total_children,
                    "child_ratio": child_ratio,
                }
                df = pd.DataFrame([data])
                for name, categories in CATEGORICAL_CATEGORIES.items():
                    df[name] = pd.Categorical(df[name], categories=categories)
                pred = model.predict(xgb.DMatrix(df, enable_categorical=True))[0]

                # Metric Display
                st.metric(
                    label="Predicted Value",
                    value=f"{pred:,.4f}"
                )

                st.success("Prediction calculated successfully!")

                # Input summary view
                with st.expander("View Input Vector"):
                    st.dataframe(df.T.rename(columns={0: "Value"}), use_container_width=True)
            else:
                st.info("Awaiting input submission...")

# ------------------------------------------------------------ CALCULATOR
with calculator_tab:
    st.header("Loan Payoff Timeline Calculator")
    st.write("Enter your loan details below to calculate how long it will take to pay off.")

    st.markdown("---")

    col1, col2 = st.columns([1, 1])

    # Left Column: User Inputs
    with col1:
        st.subheader("Loan Details")
        principal = st.number_input("Loan Amount / Balance ($)", min_value=1.0, value=1000.0, step=50.0)
        apr = st.number_input("Annual Interest Rate / APR (%)", min_value=0.0, max_value=500.0, value=24.0, step=0.5)
        monthly_payment = st.number_input("Monthly Payment ($)", min_value=1.0, value=50.0, step=5.0)

    # Right Column: Instant Results Output
    with col2:
        st.subheader("Payoff Results")

        # Monthly interest calculation
        monthly_rate = (apr / 100.0) / 12.0
        monthly_interest_fee = principal * monthly_rate

        # Check if payment is too low to cover interest
        if monthly_rate > 0 and monthly_payment <= monthly_interest_fee:
            st.error("**Debt Trap Warning!**")
            st.write(
                f"Your monthly payment of **${monthly_payment:,.2f}** is lower than (or equal to) the "
                f"accumulating monthly interest of **${monthly_interest_fee:,.2f}**. "
                "This loan will **never** be paid off at this payment level."
            )
        else:
            # Payoff calculation
            if monthly_rate == 0:
                months = math.ceil(principal / monthly_payment)
            else:
                n_months = -math.log(1 - (monthly_rate * principal) / monthly_payment) / math.log(1 + monthly_rate)
                months = math.ceil(n_months)

            total_paid = monthly_payment * months
            total_interest = total_paid - principal
            years = round(months / 12.0, 1)

            # Output Display
            st.metric("Time to Pay Off", f"{months} Months", delta=f"~{years} Years")

            sub_col1, sub_col2 = st.columns(2)
            with sub_col1:
                st.metric("Total Interest Paid", f"${total_interest:,.2f}")
            with sub_col2:
                st.metric("Total Overall Cost", f"${total_paid:,.2f}")

            if total_paid > 0:
                interest_share = (total_interest / total_paid) * 100
                st.caption(f"**Cost breakdown:** {interest_share:.1f}% of your payments go directly to interest.")
