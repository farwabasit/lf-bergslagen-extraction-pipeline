"""Credit Assessment agent: verifies income/expenses, checks the customer's
existing liabilities/exposures with LF, and runs a deterministic retail
credit decision policy. Deliberately rule-based rather than LLM-judged - a
credit decision has to be explainable and reproducible for BASEL/ECB credit
risk oversight, which an LLM's free-form judgment can't guarantee. The LLM
layer (mortgage_agent) narrates this agent's structured result in natural
language; it never overrides the decision itself."""

from .. import audit
from ..knowledge import CREDIT_POLICY, CUSTOMER_TIER_SPREADS_PERCENT, MARKET_BASE_RATE_PERCENT, MOCK_CUSTOMERS
from .loan_calc import calculate_loan_terms, max_loan_amount_for_payment


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

    # Illustrative deterministic credit score (300-850 band, same shape as a
    # real bureau score) - not a real scoring model, just a reproducible
    # function of DTI/LTV so the "credit score" concept in the process spec
    # has a concrete, auditable number behind it. Internal only - the LLM
    # layer is instructed never to surface this, credit_recommendation, or
    # eligible_ltv_percent to the customer; only the decision (approved or
    # not) is customer-facing.
    credit_score = round(850 - (dti_percent * 3) - (max(0, ltv_percent - 50) * 2))
    credit_score = max(300, min(850, credit_score))

    result = {
        "decision": decision,
        "reasons": reasons,
        "dti_percent": dti_percent,
        "ltv_percent": ltv_percent,
        "disposable_income_sek": disposable_income_sek,
        "existing_monthly_debt_sek": existing_monthly_debt,
        "estimated_monthly_mortgage_payment_sek": estimated_monthly_mortgage_payment_sek,
        "credit_score": credit_score,
        "credit_recommendation": decision,
        "eligible_ltv_percent": CREDIT_POLICY["max_ltv_percent"],
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


def assess_loan_promise_eligibility(
    customer_id: str,
    monthly_gross_income_sek: float,
    monthly_expenses_sek: float,
) -> dict:
    """Runs the Loan Promise (Lånelöfte) affordability policy - how much a
    customer could likely borrow BEFORE they've found a specific property,
    so there's no purchase price/LTV to check yet. Deterministic like
    assess_credit above, for the same audit-reproducibility reason: caps the
    affordable monthly mortgage payment by both the DTI policy ceiling and
    by what leaves non-negative disposable income after living expenses,
    then converts that payment ceiling into a maximum loan amount using the
    same conservative (Standard-tier) rate assumption assess_credit uses."""
    customer = _find_customer(customer_id)
    if not customer:
        result = {"decision": "DECLINE", "reasons": [f"Unknown customer_id '{customer_id}'."]}
        audit.record_event(
            agent="credit_agent", action="loan_promise_assessment", customer_id=customer_id,
            decision="DECLINE", details=result,
        )
        return result

    conservative_rate = MARKET_BASE_RATE_PERCENT + CUSTOMER_TIER_SPREADS_PERCENT["Standard"]

    existing_liabilities = customer.get("liabilities", [])
    existing_monthly_debt = sum(l["monthlyPayment"] for l in existing_liabilities)

    reasons: list[str] = []
    decision = "APPROVE"

    if monthly_gross_income_sek < CREDIT_POLICY["min_monthly_income_sek"]:
        decision = "DECLINE"
        reasons.append(
            f"Verified monthly income {monthly_gross_income_sek:.0f} SEK is below the "
            f"minimum {CREDIT_POLICY['min_monthly_income_sek']} SEK required."
        )

    budget_by_dti_sek = (monthly_gross_income_sek * CREDIT_POLICY["max_dti_percent"] / 100) - existing_monthly_debt
    budget_by_disposable_sek = monthly_gross_income_sek - monthly_expenses_sek - existing_monthly_debt
    max_monthly_mortgage_payment_sek = round(min(budget_by_dti_sek, budget_by_disposable_sek), 2)

    if decision != "DECLINE" and max_monthly_mortgage_payment_sek <= 0:
        decision = "DECLINE"
        reasons.append(
            "Existing expenses and debt leave no room for a mortgage payment within the "
            f"{CREDIT_POLICY['max_dti_percent']}% debt-to-income policy."
        )

    max_loan_amount_sek = 0.0
    implied_property_price_sek = 0.0
    if decision == "APPROVE":
        max_loan_amount_sek = round(
            max_loan_amount_for_payment(conservative_rate, max_monthly_mortgage_payment_sek), 2
        )
        implied_property_price_sek = round(max_loan_amount_sek / (CREDIT_POLICY["max_ltv_percent"] / 100), 2)
        reasons.append(
            "Affordable monthly mortgage payment is within both the "
            f"{CREDIT_POLICY['max_dti_percent']}% debt-to-income policy and leaves non-negative "
            "disposable income after living expenses."
        )

    result = {
        "decision": decision,
        "reasons": reasons,
        "max_monthly_mortgage_payment_sek": max_monthly_mortgage_payment_sek,
        "max_loan_amount_sek": max_loan_amount_sek,
        "implied_property_price_sek": implied_property_price_sek,
        "existing_monthly_debt_sek": existing_monthly_debt,
        "conservative_rate_used_percent": conservative_rate,
        "policy_version": CREDIT_POLICY["policy_version"],
    }

    audit.record_event(
        agent="credit_agent",
        action="loan_promise_assessment",
        customer_id=customer_id,
        decision=decision,
        details={
            "inputs": {
                "monthly_gross_income_sek": monthly_gross_income_sek,
                "monthly_expenses_sek": monthly_expenses_sek,
                "existing_liabilities": existing_liabilities,
            },
            "outputs": result,
        },
    )
    return result
