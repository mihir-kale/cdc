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
    st.write(
        "How does a lender\u2019s CFPB complaint profile compare with modeled payday-loan peers?"
    )

    summary = dataset_summary()
    st.caption(
        f"Method {summary['method']} \u00b7 {summary['lender_count']:,} lenders \u00b7 {summary['total_complaints']:,} complaints in this dataset"
    )

    query = st.text_input("Search lenders by name", placeholder="Start typing a name\u2026")
    index = lender_index()
    if query.strip():
        needle = query.strip().lower()
        index = [row for row in index if needle in row["name"].lower()]
    else:
        index = index[:MAX_RESULTS]

    if not index:
        st.info("No lender matches that name.")
    else:
        if not query.strip():
            st.caption(
                f"Showing the first {len(index)} of {len(lender_index()):,}. Type to narrow the list."
            )
        by_name = {row["name"]: row for row in index}
        chosen = st.selectbox(
            "Lender",
            list(by_name),
            format_func=lambda n: f"{n}  —  {by_name[n]['n_complaints']:,} complaints",
        )
        label = get_lender(by_name[chosen]["id"])

        st.subheader(chosen)
        st.caption(label["methodology"]["direction"])

        ev1, ev2, ev3 = st.columns(3)
        with ev1:
            st.metric("CFPB complaints", f"{label['n_complaints']:,}")
        with ev2:
            st.metric("Evidence strength", label["evidence"])
        with ev3:
            st.metric("Dimensions scored", str(len(label["dimensions"])))

        st.caption(
            "Evidence strength describes how much complaint data supports the grades below, not how good or bad the lender is. More complaints usually means more customers, not more misconduct."
        )

        for slug, dim in label["dimensions"].items():
            letter, descriptor = grade_for(dim["score"])
            grade_col, text_col = st.columns([1, 4])
            with grade_col:
                st.metric(dim["label"], letter)
                st.caption(descriptor)
            with text_col:
                st.caption(dim["summary"])
                st.progress(min(100.0, max(0.0, dim["score"])) / 100.0)
                st.caption(
                    f"{COMPARISON_TEXT[dim['comparison']]} \u2014 "
                    f"{dim['complaints']:,} complaints, estimated rate "
                    f"{dim['prevalence'] * 100:.1f}% "
                    f"(90% credible interval "
                    f"{dim['prevalence_lo90'] * 100:.1f}\u2013{dim['prevalence_hi90'] * 100:.1f}%)"
                )

        st.divider()
        st.caption(
            "Grades are per dimension on purpose. There is no overall grade, because the five dimensions overlap and combining them would hide that. Each letter is a band on a shrunk, peer-relative estimate, not a verdict about the lender."
        )

        with st.expander("How this is calculated"):
            st.write(label["methodology"]["summary"])
            for caveat in label["methodology"]["caveats"]:
                st.caption(f"\u2022 {caveat}")
            st.caption(f"Method: {label['method']}")

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
