import pandas as pd
import numpy as np
import streamlit as st
import xgboost as xgb
import math

st.set_page_config(
    page_title="PayWatch", 
    page_icon=":clapper:", 
    layout="wide"
    )

st.title("PayWatch")

# MODULE: LOAN PAYOFF CALCULATOR
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


st.header('SNAP Elgibility Predictor')

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
            pred = model.predict(xgb.DMatrix(df))[0]

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