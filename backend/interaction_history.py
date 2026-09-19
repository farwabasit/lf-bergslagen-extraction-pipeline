"""Turns a customer's raw interaction log (db.py) plus whatever case status
cs-service knows about into the customer-friendly "mini-portfolio" the chat
widget's interaction-history panel renders - what they've talked to Sara
about, how far each thing has gotten, and what still needs attention.

Deliberately does no deciding of its own: topic labels and priority are
read off data other layers already computed (topic_classifier.py's
routing-derived topic, cs-service's case status) - narration over the
existing record, same principle as the LLM layer elsewhere in this app.
"""

from . import cs_client, db

# Customer-facing label for each topic string topic_classifier.py can
# produce - kept here, not there, since that module's job is classification
# for the AI Hub metrics, not wording for a customer-facing panel.
TOPIC_LABELS = {
    "human_contact": "Requested to speak with someone",
    "mortgage_loan_promise": "Mortgage pre-approval",
    "mortgage_loan_offer": "Mortgage application",
    "fraud_report": "Fraud report",
    "transaction_dispute": "Transaction dispute",
    "portfolio_inquiry": "Reviewed your products",
    "callback_request": "Callback request",
    "case_status": "Checked a case status",
    "car_repair": "Car damage claim",
    "home_repair": "Home damage claim",
    "health_care": "Personal injury claim",
    "home_purchase_advisory": "Home purchase advice",
    "general_advisory": "General question",
}

# Case statuses cs-service can return, worded for a customer rather than a
# CS rep - see cs-service's CaseStatus.java for the underlying enum.
STATUS_LABELS = {
    "NEW": "Received",
    "IN_PROGRESS": "In progress",
    "SUBMITTED": "With our team",
    "RESOLVED": "Completed",
}

# Topics that are urgent by nature (money at risk, security), regardless of
# where the underlying case currently stands - the customer-facing "high
# priority" flag other open items don't get.
URGENT_TOPICS = {"fraud_report", "transaction_dispute"}


def _priority(topic: str, status: str | None) -> str:
    if status == "RESOLVED":
        return "done"
    if topic in URGENT_TOPICS:
        return "high"
    if status is not None:
        return "open"
    return "info"


def build_customer_history(customer_id: str, limit: int = 10) -> list[dict]:
    """One item per recent interaction, most recent first, each with a
    friendly label, the underlying case's progress (if any), and a
    priority the panel uses to flag what needs the customer's attention."""
    interactions = db.get_customer_interactions(customer_id, limit=limit)

    case_cache: dict[str, dict | None] = {}
    items = []
    for row in interactions:
        case_id = row["case_id"]
        status = None
        case_type = None
        if case_id:
            if case_id not in case_cache:
                case_cache[case_id] = cs_client.get_case_for_customer(case_id, customer_id)
            case = case_cache[case_id]
            if case:
                status = case.get("status")
                case_type = case.get("type")

        topic = row["topic"]
        items.append({
            "topic": topic,
            "label": TOPIC_LABELS.get(topic, topic.replace("_", " ").capitalize()),
            "date": row["ts"].isoformat() if row["ts"] else None,
            "case_id": case_id,
            "case_type": case_type,
            "status": status,
            "status_label": STATUS_LABELS.get(status) if status else None,
            "priority": _priority(topic, status),
        })

    return items
