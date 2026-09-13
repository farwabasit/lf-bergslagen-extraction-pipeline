"""Credit Assessment agent: verifies income/expenses, checks the customer's
existing liabilities/exposures with LF, and runs a deterministic retail
credit decision policy. Deliberately rule-based rather than LLM-judged - a
credit decision has to be explainable and reproducible for BASEL/ECB credit
risk oversight, which an LLM's free-form judgment can't guarantee. The LLM
layer (mortgage_agent) narrates this agent's structured result in natural
language; it never overrides the decision itself."""

from .. import audit
from ..knowledge import CREDIT_POLICY, CUSTOMER_TIER_SPREADS_PERCENT, MARKET_BASE_RATE_PERCENT, MOCK_CUSTOMERS
from .loan_calc import calculate_loan_terms


def _find_customer(customer_id: str) -> dict | None:
    return next((c for c in MOCK_CUSTOMERS if c["customer_id"] == customer_id), None)


def assess_credit(
    customer_id: str,
    monthly_gross_income_sek: float,
    monthly_expenses_sek: float,
    loan_amount_sek: float,
    property_value_sek: float,
) -> dict:
    """Runs the retail mortgage credit decision policy and returns a
    structured recommendation (APPROVE / MANUAL_REVIEW / DECLINE) with the
    reasoning behind it. Every input and the full policy version used is
    logged to the audit trail alongside the decision.

    The exact tier-priced interest rate isn't known yet at this stage of the
    pipeline (that's the next step), so this uses a conservative estimate -
    the market base rate plus the highest (Standard-tier) spread - to size
    the affordability check. That's deliberately cautious: a customer who
    passes this estimate will also pass at their real, likely-lower rate."""
    customer = _find_customer(customer_id)
    if not customer:
        result = {"decision": "DECLINE", "reasons": [f"Unknown customer_id '{customer_id}'."]}
        audit.record_event(
            agent="credit_agent", action="credit_assessment", customer_id=customer_id,
            decision="DECLINE", details=result,
        )
        return result

    conservative_rate = MARKET_BASE_RATE_PERCENT + CUSTOMER_TIER_SPREADS_PERCENT["Standard"]
    estimated_terms = calculate_loan_terms(customer_id, loan_amount_sek, conservative_rate)
    estimated_monthly_mortgage_payment_sek = estimated_terms["monthly_payment_sek"]

    existing_liabilities = customer.get("liabilities", [])
    existing_monthly_debt = sum(l["monthlyPayment"] for l in existing_liabilities)
    total_monthly_debt = existing_monthly_debt + estimated_monthly_mortgage_payment_sek

    dti_percent = round((total_monthly_debt / monthly_gross_income_sek) * 100, 1) if monthly_gross_income_sek else 999
    ltv_percent = round((loan_amount_sek / property_value_sek) * 100, 1) if property_value_sek else 999
    disposable_income_sek = round(monthly_gross_income_sek - monthly_expenses_sek - total_monthly_debt, 2)

    reasons: list[str] = []
    decision = "APPROVE"

    if monthly_gross_income_sek < CREDIT_POLICY["min_monthly_income_sek"]:
        decision = "DECLINE"
        reasons.append(
            f"Verified monthly income {monthly_gross_income_sek:.0f} SEK is below the "
            f"minimum {CREDIT_POLICY['min_monthly_income_sek']} SEK required."
        )

    if ltv_percent > CREDIT_POLICY["max_ltv_percent"]:
        decision = "DECLINE"
        reasons.append(
            f"Loan-to-value {ltv_percent}% exceeds the statutory maximum "
            f"{CREDIT_POLICY['max_ltv_percent']}%."
        )

    if decision != "DECLINE":
        if dti_percent > CREDIT_POLICY["manual_review_dti_percent"]:
            decision = "DECLINE"
            reasons.append(
                f"Debt-to-income {dti_percent}% exceeds the manual-review ceiling "
                f"{CREDIT_POLICY['manual_review_dti_percent']}%."
            )
        elif dti_percent > CREDIT_POLICY["max_dti_percent"]:
            decision = "MANUAL_REVIEW"
            reasons.append(
                f"Debt-to-income {dti_percent}% is above the automatic-approval threshold "
                f"{CREDIT_POLICY['max_dti_percent']}% but within the manual-review band "
                f"({CREDIT_POLICY['manual_review_dti_percent']}%)."
            )

    if disposable_income_sek < 0 and decision == "APPROVE":
        decision = "MANUAL_REVIEW"
        reasons.append("Estimated disposable income after this loan would be negative.")

    if decision == "APPROVE" and not reasons:
        reasons.append("Income, DTI, and LTV are all within the automatic-approval policy.")

    result = {
        "decision": decision,
        "reasons": reasons,
        "dti_percent": dti_percent,
        "ltv_percent": ltv_percent,
        "disposable_income_sek": disposable_income_sek,
        "existing_monthly_debt_sek": existing_monthly_debt,
        "estimated_monthly_mortgage_payment_sek": estimated_monthly_mortgage_payment_sek,
        "policy_version": CREDIT_POLICY["policy_version"],
    }

    audit.record_event(
        agent="credit_agent",
        action="credit_assessment",
        customer_id=customer_id,
        decision=decision,
        details={
            "inputs": {
                "monthly_gross_income_sek": monthly_gross_income_sek,
                "monthly_expenses_sek": monthly_expenses_sek,
                "loan_amount_sek": loan_amount_sek,
                "property_value_sek": property_value_sek,
                "existing_liabilities": existing_liabilities,
            },
            "outputs": result,
        },
    )
    return result
