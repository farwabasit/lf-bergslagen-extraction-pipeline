"""Classifies which topic a /api/chat turn belongs to, for the AI Hub
dashboard's "topics covered" metric. Deliberately reuses the exact same
detector functions agent.py/mortgage_agent.py/fraud_dispute_agent.py already
use to ROUTE each turn - so the classification can never drift from what the
app actually did with the message, and adding a new specialist flow doesn't
require updating a second, separate classifier."""

from . import agent
from .agents import fraud_dispute_agent, mortgage_agent


def classify_topic(history: list[dict]) -> str:
    if agent.wants_human_contact(history):
        return "human_contact"

    if mortgage_agent.wants_loan_promise_application(history):
        return "mortgage_loan_promise"

    if mortgage_agent.wants_loan_offer_application(history):
        return "mortgage_loan_offer"

    fraud_or_dispute = fraud_dispute_agent.wants_fraud_or_dispute(history)
    if fraud_or_dispute == "fraud":
        return "fraud_report"
    if fraud_or_dispute == "dispute":
        return "transaction_dispute"

    identity_flow = agent._detect_identity_flow(history)
    if identity_flow == "portfolio":
        return "portfolio_inquiry"

    if agent._wants_callback(history):
        return "callback_request"

    if agent._wants_case_status(history):
        return "case_status"

    service_category = agent._detect_service_category(history)
    if service_category:
        return service_category

    if agent._home_purchase_stage_unclear(history) or any(
        kw in " ".join(m.get("content", "") for m in history if m.get("role") == "user").lower()
        for kw in agent.HOME_PURCHASE_KEYWORDS
    ):
        return "home_purchase_advisory"

    return "general_advisory"
