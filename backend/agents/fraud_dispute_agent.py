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
from ..tools import verify_customer_by_personnummer
from .mortgage_agent import AUTH_CHOICE_FORM, AUTH_CHOICE_SUGGESTIONS, BANKID_DEMO_PERSONNUMMER
from .mortgage_agent import _bankid_chosen as bankid_chosen

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

TXN_ID_RE = re.compile(r"TXN-\d{4}-\d{2}", re.IGNORECASE)
# The transaction-select form (below) composes its answer as "Selected
# transactions: TXN-..., TXN-..."; this narrows matching to just that list
# when present, so a stray TXN-shaped substring elsewhere in the message
# can't sneak in. Falls back to scanning the whole message so a customer
# who types one or more IDs by hand (instead of using the checkboxes)
# still works - see _resolve_transactions.
SELECTED_TXN_RE = re.compile(r"selected transactions?:\s*(.+)", re.IGNORECASE)


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


def _resolve_customer(history: list[dict]) -> dict | None:
    """BankID-verified customer for this flow - same deterministic gate as
    the mortgage/portfolio flows (see mortgage_agent._bankid_chosen and
    tools.verify_customer_by_personnummer), not typed personnummer/date of
    birth: reporting fraud or disputing a transaction touches a real
    customer's account just as much as those do, so it gets the same real
    identity check rather than a manual-entry form. Recomputed fresh every
    turn from the raw conversation text - nothing to "forget" between turns."""
    if not bankid_chosen(history):
        return None
    return verify_customer_by_personnummer(BANKID_DEMO_PERSONNUMMER)


def _transactions_already_shown(history: list[dict]) -> bool:
    return any(
        m.get("role") == "assistant"
        and any(marker in (m.get("content") or "").lower() for marker in TRANSACTIONS_SHOWN_MARKERS)
        for m in history
    )


def _dedupe_txn_ids(customer: dict, raw_ids: list[str]) -> list[dict]:
    seen: set[str] = set()
    result = []
    for raw_id in raw_ids:
        txn_id = raw_id.upper()
        if txn_id in seen:
            continue
        found = next((t for t in customer["transactions"] if t["id"] == txn_id), None)
        if found:
            result.append(found)
            seen.add(txn_id)
    return result


def _resolve_transactions(customer: dict, history: list[dict]) -> list[dict]:
    """One or more transactions the customer is disputing/reporting, in the
    order they picked them. Reads the transaction-select form's composed
    answer when present ("Selected transactions: TXN-..., TXN-..."), or
    falls back to scanning the raw message for TXN ids typed by hand."""
    last_user = _last_user_message(history)
    selected_match = SELECTED_TXN_RE.search(last_user)
    source_text = selected_match.group(1) if selected_match else last_user
    return _dedupe_txn_ids(customer, TXN_ID_RE.findall(source_text))


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


TEXT = {
    "en": {
        "ask_identity": (
            "I hear you on that - since this touches your actual account, I first need "
            "to verify your identity via BankID."
        ),
        "txn_intro": (
            "Thanks, {name} - I've verified your identity. Here are your 10 most recent "
            "transactions - check every one that looks wrong to you, then select "
            "\"Dispute selected transactions\" below."
        ),
        "clarify_selection": (
            "Sorry, I couldn't tell which transaction(s) you meant. Please use the checkboxes "
            "above, or reply with the Transaction ID(s), e.g. TXN-1001-05."
        ),
        "form_intro_one": (
            "Got it - transaction {txn_id} ({date}, {merchant}, {amount}). I just need "
            "a few quick details before I open the case:"
        ),
        "form_intro_many": (
            "Got it - {count} transactions selected:\n{lines}\n\nI just need a few quick "
            "details before I open the case:"
        ),
        "form_retry": (
            "I didn't quite catch all three answers - could you fill in the form above, or "
            "reply with all three lines: \"Suspected place of fraud: ...\", \"Block debit "
            "card: Yes/No\", \"Block debits on account: Yes/No\"?"
        ),
        "confirmation_one": (
            "Thanks, {name} - I've opened a {case_type} case for transaction {txn_id} "
            "({date}, {merchant}, {amount}).\n\n"
            "Case ID: {case_id}\n"
            "A Customer Service representative will review it and follow up with you.\n\n"
            "Is there anything else I can help you with today?"
        ),
        "confirmation_many": (
            "Thanks, {name} - I've opened a {case_type} case covering {count} transactions:\n"
            "{lines}\n\n"
            "Case ID: {case_id}\n"
            "A Customer Service representative will review it and follow up with you."
        ),
    },
    "sv": {
        "ask_identity": (
            "Jag förstår - eftersom det här rör ditt faktiska konto behöver jag först "
            "verifiera din identitet via BankID."
        ),
        "txn_intro": (
            "Tack, {name} - jag har verifierat din identitet. Här är dina 10 senaste "
            "transaktioner - kryssa för alla som ser felaktiga ut och välj sedan "
            "\"Bestrid valda transaktioner\" nedan."
        ),
        "clarify_selection": (
            "Jag kunde tyvärr inte avgöra vilken/vilka transaktion(er) du menade. Använd "
            "kryssrutorna ovan, eller svara med transaktions-ID:t/ID:n, t.ex. TXN-1001-05."
        ),
        "form_intro_one": (
            "Uppfattat - transaktion {txn_id} ({date}, {merchant}, {amount}). Jag behöver "
            "bara några snabba detaljer innan jag öppnar ärendet:"
        ),
        "form_intro_many": (
            "Uppfattat - {count} transaktioner valda:\n{lines}\n\nJag behöver bara några "
            "snabba detaljer innan jag öppnar ärendet:"
        ),
        "form_retry": (
            "Jag fick inte med alla tre svar - kan du fylla i formuläret ovan, eller svara "
            "med alla tre rader: \"Suspected place of fraud: ...\", \"Block debit card: "
            "Yes/No\", \"Block debits on account: Yes/No\"?"
        ),
        "confirmation_one": (
            "Tack, {name} - jag har öppnat ett {case_type_sv}-ärende för transaktionen "
            "{txn_id} ({date}, {merchant}, {amount}).\n\n"
            "Ärende-ID: {case_id}\n"
            "En kundtjänstmedarbetare granskar det och återkommer till dig.\n\n"
            "Kan jag hjälpa dig med något annat idag?"
        ),
        "confirmation_many": (
            "Tack, {name} - jag har öppnat ett {case_type_sv}-ärende som omfattar "
            "{count} transaktioner:\n{lines}\n\n"
            "Ärende-ID: {case_id}\n"
            "En kundtjänstmedarbetare granskar det och återkommer till dig."
        ),
    },
}

SUGGESTIONS = {
    "en": {
        "clarify_selection": ["Try TXN-1001-05", "TXN-1001-01 and TXN-1001-09"],
        "form_retry": ["Let me fill it in again"],
    },
    "sv": {
        "clarify_selection": ["Prova TXN-1001-05", "TXN-1001-01 och TXN-1001-09"],
        "form_retry": ["Jag fyller i igen"],
    },
}


def _resolve_selected_transactions_from_assistant(customer: dict, history: list[dict]) -> list[dict]:
    """Once the form has been shown, the customer's next reply is their
    form answers, not a transaction reference - so re-deriving "which
    transaction(s)" from the latest USER message would fail (it has no ID
    in it). Instead, re-derive them from our OWN prior message that showed
    the form, which always states every selected transaction ID literally."""
    for m in reversed(history):
        if m.get("role") != "assistant":
            continue
        content = m.get("content") or ""
        if not any(marker in content for marker in FORM_MARKERS):
            continue
        return _dedupe_txn_ids(customer, TXN_ID_RE.findall(content))
    return []


def run_fraud_dispute_agent(history: list[dict], lang: str | None, case_type: str) -> tuple[str, list[str], dict]:
    key = "sv" if lang == "sv" else "en"
    t = TEXT[key]
    s = SUGGESTIONS[key]

    customer = _resolve_customer(history)

    if customer is None:
        return t["ask_identity"], AUTH_CHOICE_SUGGESTIONS[key], {"form": AUTH_CHOICE_FORM}

    if not _transactions_already_shown(history):
        verified_customer.mark_verified(customer["customer_id"])
        audit.record_event(
            agent="fraud_dispute_agent", action="verify_identity", customer_id=customer["customer_id"],
            decision="VERIFIED", details={"case_type": case_type},
        )
        audit.record_event(
            agent="fraud_dispute_agent", action="list_transactions", customer_id=customer["customer_id"],
            decision="SHOWN", details={"count": len(customer["transactions"])},
        )
        reply = t["txn_intro"].format(name=customer["name"])
        form = {"type": "transaction_select", "transactions": customer["transactions"]}
        return reply, [], {"form": form}

    if _form_already_shown(history):
        # Expecting the customer's form answers now - the transaction(s)
        # were already fixed when the form was shown, re-derive them from
        # there rather than the latest user message (which has no txn ID
        # in it at this point, just the form answers).
        transactions = _resolve_selected_transactions_from_assistant(customer, history)
        if not transactions:
            return t["clarify_selection"], s["clarify_selection"], {}

        answers = _parse_form_answers(history)
        if answers is None:
            return t["form_retry"], s["form_retry"], {"form_retry": True}
    else:
        transactions = _resolve_transactions(customer, history)
        if not transactions:
            return t["clarify_selection"], s["clarify_selection"], {}

        audit.record_event(
            agent="fraud_dispute_agent", action="select_transactions", customer_id=customer["customer_id"],
            decision="SELECTED",
            details={"transactions": [txn["id"] for txn in transactions], "case_type": case_type},
        )
        if len(transactions) == 1:
            txn = transactions[0]
            reply = t["form_intro_one"].format(
                txn_id=txn["id"], date=txn["date"], merchant=txn["merchant"], amount=txn["amount"],
            )
        else:
            lines = "\n".join(
                f"- {txn['id']} — {txn['date']}, {txn['merchant']}, {txn['amount']}" for txn in transactions
            )
            reply = t["form_intro_many"].format(count=len(transactions), lines=lines)
        form = {
            "type": "fraud_dispute_details",
            "transaction_ids": [txn["id"] for txn in transactions],
            "fields": [
                {"name": "place", "label": "Suspected place of fraud", "type": "text"},
                {"name": "block_card", "label": "Block Debit Card?", "type": "yesno"},
                {"name": "block_account", "label": "Block Debits on Account?", "type": "yesno"},
            ],
        }
        return reply, [], {"form": form}

    txn_summary = "; ".join(f"{txn['id']} ({txn['date']}, {txn['merchant']}, {txn['amount']})" for txn in transactions)
    description = (
        f"{case_type.title()} report for {len(transactions)} transaction(s): {txn_summary}. "
        f"Suspected place of fraud: {answers['place']}."
    )
    extra = {
        "transactionIds": ", ".join(txn["id"] for txn in transactions),
        "transactionDetails": "; ".join(f"{txn['date']} — {txn['merchant']} — {txn['amount']}" for txn in transactions),
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

    case_type_sv = "bedrägeri" if case_type == "fraud" else "bestridande"
    if len(transactions) == 1:
        txn = transactions[0]
        reply = t["confirmation_one"].format(
            name=customer["name"], case_type=case_type, case_type_sv=case_type_sv,
            txn_id=txn["id"], date=txn["date"], merchant=txn["merchant"], amount=txn["amount"], case_id=case_id,
        )
    else:
        lines = "\n".join(
            f"- {txn['id']} — {txn['date']}, {txn['merchant']}, {txn['amount']}" for txn in transactions
        )
        reply = t["confirmation_many"].format(
            name=customer["name"], case_type=case_type, case_type_sv=case_type_sv,
            count=len(transactions), lines=lines, case_id=case_id,
        )
    return reply, [], {}
