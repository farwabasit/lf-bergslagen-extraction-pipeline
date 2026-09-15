"""Fraud/Dispute Agent: a fully deterministic state machine, not an LLM
tool-calling loop. This flow used to live inside Sara's general-purpose
loop and was unreliable in practice - the model sometimes "forgot" identity
already given earlier in the conversation, or failed to recognize a
transaction ID the customer had typed verbatim. Neither of those is
actually a language-understanding problem; both are pattern-matching
against fixed formats (a personnummer, a TXN-xxxx-xx id, a row number 1-10),
which regex does perfectly and an LLM does only probabilistically. So this
flow is re-derived from the raw conversation history on every single turn
(no session state, matching the app's existing stateless-per-request
design) using plain string/regex matching - it can't "forget" anything
because it never remembers anything; it just re-reads the transcript.

Every step is logged to the audit trail, same discipline as the mortgage
agent (see backend/audit.py)."""

import re

from .. import audit, cs_client, verified_customer
from ..knowledge import MOCK_CUSTOMERS

FRAUD_KEYWORDS = [
    "report fraud", "reporting fraud", "i want to report fraud", "it's fraud",
    "anmäla bedrägeri", "anmäl bedrägeri", "jag vill anmäla ett bedrägeri", "bedrägeri",
]
DISPUTE_KEYWORDS = [
    "dispute a transaction", "dispute transaction", "i want to dispute",
    "bestrida en transaktion", "bestrid en transaktion", "bestrida transaktion",
]

# Kept as tuples (one marker per UI language) since the reply text itself
# is localized - a substring check against a single English marker would
# silently never match a Swedish reply. Same pattern used by the other
# flows in agent.py.
RESOLVED_MARKERS = ("Case ID:", "Ärende-ID:")
TRANSACTIONS_SHOWN_MARKERS = ("most recent transactions", "senaste transaktioner")
FORM_MARKERS = ("a few quick details", "några snabba detaljer")

PNR_RE = re.compile(r"\d{6,8}[-\s]?\d{4}")
TXN_ID_RE = re.compile(r"TXN-\d{4}-\d{2}", re.IGNORECASE)
ROW_NUMBER_RE = re.compile(
    r"(?:number|row|transaction|#)\s*\b(10|[1-9])\b|^\s*(10|[1-9])\s*$|\b(10|[1-9])(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)


def wants_fraud_or_dispute(history: list[dict]) -> str | None:
    combined = " ".join(m.get("content", "") for m in history if m.get("role") == "user").lower()
    if any(kw in combined for kw in FRAUD_KEYWORDS):
        return "fraud"
    if any(kw in combined for kw in DISPUTE_KEYWORDS):
        return "dispute"
    return None


def fraud_dispute_flow_resolved(history: list[dict]) -> bool:
    return any(
        m.get("role") == "assistant"
        and any(marker in (m.get("content") or "") for marker in RESOLVED_MARKERS)
        for m in history
    )


def _last_user_message(history: list[dict]) -> str:
    return next((m.get("content", "") for m in reversed(history) if m.get("role") == "user"), "")


def _all_user_text(history: list[dict]) -> str:
    return " ".join(m.get("content", "") for m in history if m.get("role") == "user")


def _resolve_customer(history: list[dict]) -> dict | None:
    """Deterministically re-derives which (mock) customer this is from the
    raw conversation text - personnummer digits must match exactly, and the
    customer's name must appear somewhere in the conversation too. Recomputed
    fresh every turn, so there's nothing to "forget" between turns."""
    combined = _all_user_text(history)
    pnr_match = PNR_RE.search(combined)
    if not pnr_match:
        return None
    pnr_digits = re.sub(r"\D", "", pnr_match.group(0))

    combined_lower = combined.lower()
    for customer in MOCK_CUSTOMERS:
        record_digits = re.sub(r"\D", "", customer["personnummer"])
        if pnr_digits != record_digits:
            continue
        name_parts = customer["name"].lower().split()
        if any(part in combined_lower for part in name_parts):
            return customer
    return None


def _transactions_already_shown(history: list[dict]) -> bool:
    return any(
        m.get("role") == "assistant"
        and any(marker in (m.get("content") or "").lower() for marker in TRANSACTIONS_SHOWN_MARKERS)
        for m in history
    )


def _resolve_transaction(customer: dict, history: list[dict]) -> dict | None:
    last_user = _last_user_message(history)

    id_match = TXN_ID_RE.search(last_user)
    if id_match:
        txn_id = id_match.group(0).upper()
        found = next((t for t in customer["transactions"] if t["id"] == txn_id), None)
        if found:
            return found

    row_match = ROW_NUMBER_RE.search(last_user)
    if row_match:
        digits = next(g for g in row_match.groups() if g)
        idx = int(digits) - 1
        if 0 <= idx < len(customer["transactions"]):
            return customer["transactions"][idx]

    return None


def _form_already_shown(history: list[dict]) -> bool:
    return any(
        m.get("role") == "assistant"
        and any(marker in (m.get("content") or "") for marker in FORM_MARKERS)
        for m in history
    )


FORM_ANSWER_RE = {
    "place": re.compile(r"place of fraud:\s*(.+)", re.IGNORECASE),
    "block_card": re.compile(r"block debit card:\s*(yes|no)", re.IGNORECASE),
    "block_account": re.compile(r"block debits? on account:\s*(yes|no)", re.IGNORECASE),
}


def _parse_form_answers(history: list[dict]) -> dict | None:
    last_user = _last_user_message(history)
    place_m = FORM_ANSWER_RE["place"].search(last_user)
    card_m = FORM_ANSWER_RE["block_card"].search(last_user)
    account_m = FORM_ANSWER_RE["block_account"].search(last_user)
    if not (place_m and card_m and account_m):
        return None
    return {
        "place": place_m.group(1).strip().splitlines()[0],
        "block_card": card_m.group(1).strip().capitalize(),
        "block_account": account_m.group(1).strip().capitalize(),
    }


# Shown instead of "fill in the blank" suggestion chips - those looked like
# real options but were actually templates the customer needed to complete
# ("My name is...", clicked, sent literally as-is, which obviously never
# verifies). A form with real input fields is the honest version of that:
# the customer visibly fills in their own values before anything is sent.
IDENTITY_FORM = {
    "type": "identity_details",
    "fields": [
        {"name": "full_name", "label": "Full name", "type": "text", "placeholder": "e.g. Anna Andersson"},
        {"name": "personnummer", "label": "Personnummer", "type": "text", "placeholder": "YYYYMMDD-XXXX"},
        {"name": "dob", "label": "Date of birth", "type": "text", "placeholder": "YYYY-MM-DD"},
    ],
}


TEXT = {
    "en": {
        "ask_identity": (
            "I hear you on that - I just need to verify your identity first. Could you "
            "give me your full name, personnummer, and date of birth?"
        ),
        "not_verified": (
            "I couldn't verify your identity with those details. Could you double-check "
            "your name and personnummer? A typo in the personnummer is the most common cause."
        ),
        "txn_intro": (
            "Thanks, {name} - I've verified your identity. Here are your 10 most recent "
            "transactions. Reply with either the row number or the Transaction ID of the one "
            "you mean:\n\n"
        ),
        "txn_outro": "",
        "clarify_selection": (
            "Sorry, I couldn't tell which transaction you meant. Please reply with either the "
            "row number (1-10) or the Transaction ID (e.g. TXN-1001-05) from the list above."
        ),
        "form_intro": (
            "Got it - transaction {txn_id} ({date}, {merchant}, {amount}). I just need "
            "a few quick details before I open the case:"
        ),
        "form_retry": (
            "I didn't quite catch all three answers - could you fill in the form above, or "
            "reply with all three lines: \"Suspected place of fraud: ...\", \"Block debit "
            "card: Yes/No\", \"Block debits on account: Yes/No\"?"
        ),
        "confirmation": (
            "Thanks, {name} - I've opened a {case_type} case for transaction {txn_id} "
            "({date}, {merchant}, {amount}).\n\n"
            "Case ID: {case_id}\n"
            "A Customer Service representative will review it and follow up with you."
        ),
    },
    "sv": {
        "ask_identity": (
            "Jag förstår - jag behöver bara verifiera din identitet först. Kan du ge mig "
            "ditt fullständiga namn, personnummer och födelsedatum?"
        ),
        "not_verified": (
            "Jag kunde inte verifiera din identitet med de uppgifterna. Kan du dubbelkolla "
            "namn och personnummer? Ett skrivfel i personnumret är den vanligaste orsaken."
        ),
        "txn_intro": (
            "Tack, {name} - jag har verifierat din identitet. Här är dina 10 senaste "
            "transaktioner. Svara med antingen radnumret eller transaktions-ID:t för den du menar:\n\n"
        ),
        "txn_outro": "",
        "clarify_selection": (
            "Jag kunde tyvärr inte avgöra vilken transaktion du menade. Svara gärna med "
            "radnumret (1-10) eller transaktions-ID:t (t.ex. TXN-1001-05) från listan ovan."
        ),
        "form_intro": (
            "Uppfattat - transaktion {txn_id} ({date}, {merchant}, {amount}). Jag behöver "
            "bara några snabba detaljer innan jag öppnar ärendet:"
        ),
        "form_retry": (
            "Jag fick inte med alla tre svar - kan du fylla i formuläret ovan, eller svara "
            "med alla tre rader: \"Suspected place of fraud: ...\", \"Block debit card: "
            "Yes/No\", \"Block debits on account: Yes/No\"?"
        ),
        "confirmation": (
            "Tack, {name} - jag har öppnat ett {case_type_sv}-ärende för transaktionen "
            "{txn_id} ({date}, {merchant}, {amount}).\n\n"
            "Ärende-ID: {case_id}\n"
            "En kundtjänstmedarbetare granskar det och återkommer till dig."
        ),
    },
}

SUGGESTIONS = {
    "en": {
        "clarify_selection": ["It was number 10", "Try TXN-1001-05"],
        "form_retry": ["Let me fill it in again"],
    },
    "sv": {
        "clarify_selection": ["Det var nummer 10", "Prova TXN-1001-05"],
        "form_retry": ["Jag fyller i igen"],
    },
}


def _txn_line(idx: int, t: dict) -> str:
    return f"{idx + 1}. **{t['id']}** — {t['date']}, {t['merchant']}, {t['amount']}"


def _resolve_selected_transaction_from_assistant(customer: dict, history: list[dict]) -> dict | None:
    """Once the form has been shown, the customer's next reply is their
    form answers, not a transaction reference - so re-deriving "which
    transaction" from the latest USER message would fail (it has no ID or
    number in it). Instead, re-derive it from our OWN prior message that
    showed the form, which always states the transaction ID literally."""
    for m in reversed(history):
        if m.get("role") != "assistant":
            continue
        content = m.get("content") or ""
        if not any(marker in content for marker in FORM_MARKERS):
            continue
        id_match = TXN_ID_RE.search(content)
        if id_match:
            txn_id = id_match.group(0).upper()
            return next((t for t in customer["transactions"] if t["id"] == txn_id), None)
    return None


def run_fraud_dispute_agent(history: list[dict], lang: str | None, case_type: str) -> tuple[str, list[str], dict]:
    key = "sv" if lang == "sv" else "en"
    t = TEXT[key]
    s = SUGGESTIONS[key]

    customer = _resolve_customer(history)

    if customer is None:
        pnr_present = bool(PNR_RE.search(_all_user_text(history)))
        if not pnr_present:
            return t["ask_identity"], [], {"form": IDENTITY_FORM}
        audit.record_event(
            agent="fraud_dispute_agent", action="verify_identity", customer_id=None,
            decision="NOT_VERIFIED", details={"case_type": case_type},
        )
        return t["not_verified"], [], {"form": IDENTITY_FORM}

    if not _transactions_already_shown(history):
        verified_customer.mark_verified(customer["customer_id"])
        audit.record_event(
            agent="fraud_dispute_agent", action="verify_identity", customer_id=customer["customer_id"],
            decision="VERIFIED", details={"case_type": case_type},
        )
        listing = "\n".join(_txn_line(i, txn) for i, txn in enumerate(customer["transactions"]))
        audit.record_event(
            agent="fraud_dispute_agent", action="list_transactions", customer_id=customer["customer_id"],
            decision="SHOWN", details={"count": len(customer["transactions"])},
        )
        reply = t["txn_intro"].format(name=customer["name"]) + listing + t["txn_outro"]
        return reply, [], {}

    if _form_already_shown(history):
        # Expecting the customer's form answers now - the transaction was
        # already fixed when the form was shown, re-derive it from there.
        transaction = _resolve_selected_transaction_from_assistant(customer, history)
        if transaction is None:
            return t["clarify_selection"], s["clarify_selection"], {}

        answers = _parse_form_answers(history)
        if answers is None:
            return t["form_retry"], s["form_retry"], {"form_retry": True}
    else:
        transaction = _resolve_transaction(customer, history)
        if transaction is None:
            return t["clarify_selection"], s["clarify_selection"], {}

        audit.record_event(
            agent="fraud_dispute_agent", action="select_transaction", customer_id=customer["customer_id"],
            decision="SELECTED", details={"transaction": transaction, "case_type": case_type},
        )
        reply = t["form_intro"].format(
            txn_id=transaction["id"], date=transaction["date"],
            merchant=transaction["merchant"], amount=transaction["amount"],
        )
        form = {
            "type": "fraud_dispute_details",
            "transaction_id": transaction["id"],
            "fields": [
                {"name": "place", "label": "Suspected place of fraud", "type": "text"},
                {"name": "block_card", "label": "Block Debit Card?", "type": "yesno"},
                {"name": "block_account", "label": "Block Debits on Account?", "type": "yesno"},
            ],
        }
        return reply, [], {"form": form}

    description = (
        f"{case_type.title()} report for transaction {transaction['id']} "
        f"({transaction['date']}, {transaction['merchant']}, {transaction['amount']}). "
        f"Suspected place of fraud: {answers['place']}."
    )
    extra = {
        "transactionId": transaction["id"],
        "transactionDetails": f"{transaction['date']} — {transaction['merchant']} — {transaction['amount']}",
        "suspectedPlaceOfFraud": answers["place"],
        "blockDebitCard": answers["block_card"],
        "blockDebitsOnAccount": answers["block_account"],
    }
    case_id, status = cs_client.create_case_with_fallback(
        case_type, customer["name"], customer["customer_id"], description, extra,
    )
    audit.record_event(
        agent="fraud_dispute_agent", action="create_case", customer_id=customer["customer_id"],
        decision=case_type.upper(), details={"case_id": case_id, "status": status, **extra},
    )

    reply = t["confirmation"].format(
        name=customer["name"], case_type=case_type, case_type_sv=("bedrägeri" if case_type == "fraud" else "bestridande"),
        txn_id=transaction["id"], date=transaction["date"], merchant=transaction["merchant"],
        amount=transaction["amount"], case_id=case_id,
    )
    return reply, [], {}
