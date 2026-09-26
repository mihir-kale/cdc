import pandas as pd
import numpy as np
import streamlit as st
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