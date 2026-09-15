"""Deterministic interest-rate and repayment calculations for the mortgage
agent. Intentionally NOT LLM-driven - a BASEL/ECB-relevant number like a
customer's interest rate or monthly payment must come from a reproducible
formula an auditor can re-run, not from a language model's arithmetic."""

from .. import audit
from ..knowledge import CUSTOMER_TIER_SPREADS_PERCENT, MARKET_BASE_RATE_PERCENT


def get_interest_rate(customer_id: str, tier: str) -> dict:
    """Fetches the current market base rate and applies the customer's
    tier spread. Returns the full breakdown, not just the final number, so
    the calculation is self-documenting for an audit."""
    spread = CUSTOMER_TIER_SPREADS_PERCENT.get(tier, CUSTOMER_TIER_SPREADS_PERCENT["Standard"])
    final_rate = round(MARKET_BASE_RATE_PERCENT + spread, 2)

    result = {
        "market_base_rate_percent": MARKET_BASE_RATE_PERCENT,
        "customer_tier": tier,
        "tier_spread_percent": spread,
        "final_interest_rate_percent": final_rate,
    }
    audit.record_event(
        agent="loan_calc",
        action="fetch_interest_rate",
        customer_id=customer_id,
        decision="CALCULATED",
        details=result,
    )
    return result


def calculate_loan_terms(
    customer_id: str,
    loan_amount_sek: float,
    annual_rate_percent: float,
    amortization_years: int = 50,
) -> dict:
    """Standard annuity-style monthly payment calculation, plus the
    statutory-style amortization rate a Swedish mortgage would require
    (simplified banding by LTV is handled by the credit agent; here we just
    compute the payment given a term). All inputs/outputs are logged so the
    exact formula and figures used are reconstructable later."""
    monthly_rate = (annual_rate_percent / 100) / 12
    n_payments = amortization_years * 12

    if monthly_rate == 0:
        monthly_payment = loan_amount_sek / n_payments
    else:
        monthly_payment = (
            loan_amount_sek
            * monthly_rate
            * (1 + monthly_rate) ** n_payments
            / ((1 + monthly_rate) ** n_payments - 1)
        )

    monthly_interest_only = loan_amount_sek * monthly_rate

    result = {
        "loan_amount_sek": round(loan_amount_sek, 2),
        "annual_rate_percent": annual_rate_percent,
        "amortization_years": amortization_years,
        "monthly_payment_sek": round(monthly_payment, 2),
        "monthly_interest_only_sek": round(monthly_interest_only, 2),
    }
    audit.record_event(
        agent="loan_calc",
        action="calculate_loan_terms",
        customer_id=customer_id,
        decision="CALCULATED",
        details=result,
    )
    return result


def max_loan_amount_for_payment(
    annual_rate_percent: float,
    max_monthly_payment_sek: float,
    amortization_years: int = 50,
) -> float:
    """Inverse of calculate_loan_terms' annuity formula: given the biggest
    monthly payment a customer can carry, returns the loan amount that
    produces exactly that payment. Used by the Loan Promise (Lånelöfte) flow,
    where there's no specific property yet to size the loan from - only an
    income-based affordability ceiling."""
    monthly_rate = (annual_rate_percent / 100) / 12
    n_payments = amortization_years * 12

    if monthly_rate == 0:
        return max_monthly_payment_sek * n_payments

    return (
        max_monthly_payment_sek
        * ((1 + monthly_rate) ** n_payments - 1)
        / (monthly_rate * (1 + monthly_rate) ** n_payments)
    )
