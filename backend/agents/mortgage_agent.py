"""Mortgage Agent: orchestrates a new-mortgage application once Sara (the
main agent) hands the conversation off to it. Coordinates two further
specialist agents (document_agent for extraction/verification, credit_agent
for the credit decision), plus deterministic rate/term calculations, and
creates real cases in the Customer Service application for both manual
review hand-offs and the final Operations hand-off.

Design choice: conversation and document understanding go through the LLM
(this file's tool-calling loop, and document_agent's extraction call); every
number and decision that actually matters for the loan (income checks, DTI/
LTV, interest rate, monthly payment, the credit decision itself) is
deterministic Python, logged to the audit trail. An LLM should narrate a
mortgage decision, not make one up.
"""

import json
import re

from .. import audit, config, cs_client
from ..knowledge import LF_PAGES, MOCK_CUSTOMERS
from ..link_safety import URL_RE, strip_unverified_links
from ..llm_client import client
from ..suggestions import generate_suggestions
from ..tools import fetch_lf_page, verify_customer_identity
from . import credit_agent, document_agent, loan_calc

MAX_TOOL_ROUNDS = 8

MORTGAGE_KEYWORDS = [
    "apply for a mortgage", "start a mortgage application", "start my mortgage",
    "apply for a home loan", "mortgage application", "want a mortgage",
    "need a mortgage", "get a mortgage", "take out a mortgage",
    "ansöka om bolån", "ansöka om ett bolån", "starta en bolåneansökan",
    "vill ha ett bolån", "behöver ett bolån", "ta ett bolån",
]

# Exact phrases the agent is instructed to include verbatim at each of the
# three possible endpoints of the flow - lets Sara/this file detect from
# plain conversation history whether the mortgage flow already finished,
# without needing separate session state (tool results aren't retained
# between turns - see the note in the system prompt below).
MORTGAGE_RESOLVED_MARKERS = (
    "Loan Promise (Lånelöfte)",
    "sent to a Customer Advisor for manual review",
    "unable to proceed with this mortgage application",
)

ATTACHMENT_RE = re.compile(r"^\[Attached document:\s*(.+?)\]\n\n(.*)$", re.DOTALL)

# The identity ask used to be free-form LLM text, paired with LLM-generated
# suggestion chips like "My full name is..." - which looked like real
# options but were templates the customer needed to complete. Clicking one
# sent it verbatim, which obviously never verifies, and the chips vanished
# after one click so the other two fields couldn't be given at all. A form
# with real input fields is the honest version: fill in your own values,
# submit once. Bypassing the LLM for this one specific step also makes it
# deterministic - same reliability reasoning as the rest of this module.
IDENTITY_FORM = {
    "type": "identity_details",
    "fields": [
        {"name": "full_name", "label": "Full name", "type": "text", "placeholder": "e.g. Anna Andersson"},
        {"name": "personnummer", "label": "Personnummer", "type": "text", "placeholder": "YYYYMMDD-XXXX"},
        {"name": "dob", "label": "Date of birth", "type": "text", "placeholder": "YYYY-MM-DD"},
    ],
}
ASK_IDENTITY_TEXT = {
    "en": (
        "I'm the mortgage specialist Sara connected you with. To start your mortgage "
        "application, I need to verify your identity - please fill in your details below."
    ),
    "sv": (
        "Jag är bolånespecialisten som Sara kopplade dig till. För att starta din "
        "bolåneansökan behöver jag verifiera din identitet - fyll i dina uppgifter nedan."
    ),
}


def wants_mortgage_application(history: list[dict]) -> bool:
    combined = " ".join(m.get("content", "") for m in history if m.get("role") == "user").lower()
    return any(kw in combined for kw in MORTGAGE_KEYWORDS)


INDICATION_KEYWORDS = [
    "indication", "loan offer", "an offer", "get an estimate", "rough estimate",
    "how much can i borrow", "what would i pay", "what would my rate",
    "indikation", "erbjudande", "en uppskattning", "hur mycket kan jag låna",
    "vad skulle jag betala",
]


def _wants_loan_indication(history: list[dict]) -> bool:
    last_user = next((m.get("content", "") for m in reversed(history) if m.get("role") == "user"), "")
    text = last_user.lower()
    return any(kw in text for kw in INDICATION_KEYWORDS)


def mortgage_flow_resolved(history: list[dict]) -> bool:
    return any(
        m.get("role") == "assistant"
        and any(marker in (m.get("content") or "") for marker in MORTGAGE_RESOLVED_MARKERS)
        for m in history
    )


def _extract_attached_documents(history: list[dict]) -> list[dict]:
    documents = []
    for m in history:
        if m.get("role") != "user":
            continue
        match = ATTACHMENT_RE.match((m.get("content") or "").strip())
        if match:
            documents.append({"filename": match.group(1).strip(), "text": match.group(2).strip()})
    return documents


SYSTEM_PROMPT = """You are the Mortgage Agent, a specialist that Sara (LF
Bergslagen's main digital assistant) hands a conversation off to once a
customer wants to apply for a new mortgage. Introduce yourself briefly in
your first reply (e.g. "I'm the mortgage specialist Sara connected you
with") and then run the application process. Reply in the same language the
customer is writing in, matching Sara's own language rule.

THE PROCESS, IN ORDER - do not skip or reorder steps:

1. IDENTITY: if you don't already have the customer's full name, personnummer,
   and date of birth from this conversation, ask for all three together,
   explaining it's needed to verify their identity and pull up their
   account. Don't proceed without it.

LINKS: whenever you cite a URL, always use markdown link syntax
[label](url) - never write a bare URL. Only ever use a URL that appeared in
a fetch_lf_page tool result; never invent, guess, or recall one from
general knowledge, even if it looks plausible.

2. DOCUMENTS: once you have identity info, ask the customer to attach three
   documents to the chat: the purchase agreement (köpekontrakt), an income
   statement or payslip, and a summary of their monthly expenses. Mention,
   briefly and only once, that they can optionally tell you a specific loan
   amount if they don't want the default (85% of the purchase price, the
   statutory maximum loan-to-value in Sweden) - but this is NOT something to
   block on or re-ask about. The purchase price itself comes from the
   purchase agreement document, not from asking the customer directly - once
   it's attached, don't ask them to "confirm" the price separately.
   Don't call any tool yet if fewer than 3 documents are attached - just ask
   for whichever ones are still missing, nothing else.

   LOAN INDICATION / OFFER, BEFORE DOCUMENTS ARE READY: whenever the customer
   asks for a loan indication, an offer, an estimate, or "what would I pay" -
   at any point before all 3 documents are in - do two things in the same
   reply: (a) call fetch_lf_page("home_loan") and share it as the mortgage
   calculator/info link, framed as "you can get a rough estimate yourself
   here: [Räkna på bolån](<the exact URL of the page you just fetched>)" -
   that page's own URL (the one you called fetch_lf_page with, not a link
   found inside its text) IS the correct one to cite here, since that's
   LF Bergslagen's real mortgage/loan page; (b) explain plainly that to get
   an actual indication/offer worked out here in the chat, you need the
   three documents above, and ask for whichever are still missing. Never
   invent or guess at a different URL - only the fetched page's own URL.

3. As soon as identity info AND at least 3 attached documents are present,
   proceed immediately - do NOT ask about purchase price or loan amount
   again first, those are resolved inside the pipeline below (extraction
   gives the price; no stated amount means the 85% default is used
   automatically). Run the rest of the pipeline via tool calls, in order,
   within this same reply:
   a. verify_customer_identity - never assume verified from an earlier turn,
      tool results aren't kept between turns, always call it fresh here.
   b. extract_mortgage_documents - reads every document attached anywhere in
      this conversation (no arguments needed). If its result has
      needs_review = true, STOP: call create_review_case explaining the
      review_reason, then tell the customer plainly:
        - a short, plain-language SUMMARY of what was actually found - if
          purchase_agreement.special_conditions is non-empty, summarize each
          condition in your own words (don't just say "special conditions
          exist" - say what they are, e.g. "the seller hasn't shown full
          title for part of the lot, and the sale is contingent on a
          boundary dispute being resolved"); if needs_review came from
          something else (e.g. unstable employment type), explain that
          instead
        - that because of this, their application needs a Customer Advisor
          to look at it manually
        - the case ID
      End your reply with the exact phrase "sent to a Customer Advisor for
      manual review" somewhere in the sentence. Do not continue to credit
      assessment.
   c. If documents are fine, call run_credit_assessment using the extracted
      monthly_gross_income_sek, the extracted monthly_expenses_total_sek,
      the loan amount (customer-stated or 85% of purchase_price_sek), and
      property_value_sek = purchase_price_sek.
      - If the decision is MANUAL_REVIEW or DECLINE: STOP. Call
        create_review_case with the reasons given, tell the customer plainly
        (don't hide a decline behind vague language), state the case ID, and
        end your reply with the exact phrase "sent to a Customer Advisor for
        manual review" (for MANUAL_REVIEW) or "unable to proceed with this
        mortgage application" (for DECLINE) somewhere in the sentence.
      - If APPROVE: continue.
   d. fetch_interest_rate for this customer.
   e. calculate_loan_terms using the loan amount and the final_interest_rate_percent
      fetch_interest_rate just returned.
   f. Write out a clearly formatted Loan Promise (Lånelöfte) directly in your
      reply - a heading containing the exact phrase "Loan Promise (Lånelöfte)",
      then: applicant name, property address (from the extracted purchase
      agreement), purchase price, loan amount, interest rate (show the market
      base rate + tier spread + final rate breakdown), amortization term in
      years, monthly payment, and a line stating "This loan promise is valid
      for 6 months from today." Use ONLY numbers that came from tool results -
      never estimate or round on your own.
   g. trigger_operations_case to hand off for e-signature, account opening,
      and disbursement. State the case ID it returns and mention these
      operational steps are being progressively automated too.

RULES THROUGHOUT:
- Never invent a case ID, customer_id, interest rate, or any calculated
  figure - only ever state values a tool result actually returned.
- Every decision point above is logged to an audit trail automatically by
  the tools themselves - you don't need to do anything extra for that.
- If the user asks something unrelated to this application, answer briefly
  and steer back to whichever step is still open.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "fetch_lf_page",
            "description": (
                "Fetch a specific LF Bergslagen web page to ground advice in real, current "
                "information - e.g. \"home_loan\" for the mortgage calculator and general "
                "mortgage info page."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "enum": list(LF_PAGES.keys())},
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_customer_identity",
            "description": "Verify the applicant's identity by name, personnummer, and date of birth.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "personnummer": {"type": "string"},
                    "dob": {"type": "string"},
                },
                "required": ["name", "personnummer", "dob"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_mortgage_documents",
            "description": (
                "Extract and verify data from every document the customer has attached "
                "to this conversation (purchase agreement, income statement, expenses). "
                "Takes no arguments - it reads the attachments itself."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_credit_assessment",
            "description": "Run the retail mortgage credit decision policy for a verified customer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                    "monthly_gross_income_sek": {"type": "number"},
                    "monthly_expenses_sek": {"type": "number"},
                    "loan_amount_sek": {"type": "number"},
                    "property_value_sek": {"type": "number"},
                },
                "required": [
                    "customer_id", "monthly_gross_income_sek", "monthly_expenses_sek",
                    "loan_amount_sek", "property_value_sek",
                ],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_interest_rate",
            "description": "Fetch the current market interest rate plus this customer's tier spread.",
            "parameters": {
                "type": "object",
                "properties": {"customer_id": {"type": "string"}},
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_loan_terms",
            "description": "Calculate the monthly payment for a given loan amount and interest rate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                    "loan_amount_sek": {"type": "number"},
                    "annual_rate_percent": {"type": "number"},
                },
                "required": ["customer_id", "loan_amount_sek", "annual_rate_percent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_review_case",
            "description": (
                "Send the application to a Customer Advisor for manual review - use this "
                "for a flagged document, a MANUAL_REVIEW credit decision, or a DECLINE."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                    "customer_name": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["customer_name", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trigger_operations_case",
            "description": "Hand off an approved mortgage to Operations for e-signature, account opening, and disbursement.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                    "customer_name": {"type": "string"},
                    "loan_amount_sek": {"type": "number"},
                    "interest_rate_percent": {"type": "number"},
                    "monthly_payment_sek": {"type": "number"},
                    "property_address": {"type": "string"},
                },
                "required": [
                    "customer_id", "customer_name", "loan_amount_sek",
                    "interest_rate_percent", "monthly_payment_sek",
                ],
            },
        },
    },
]

def _find_customer(customer_id: str) -> dict | None:
    return next((c for c in MOCK_CUSTOMERS if c["customer_id"] == customer_id), None)


def _stringify_extra(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(str(v) for v in value) if value else "None"
    return str(value)


def _build_case_extra(
    last_extraction: dict | None,
    last_credit_assessment: dict | None,
    customer_id: str | None,
    **extra_fields,
) -> dict[str, str]:
    """Merges what the customer provided (documents, via document_agent) and
    what the agents decided (via credit_agent) into the case's extra data,
    so an Advisor/Operations opening this case in the CS app sees the full
    picture, not just a one-line reason - pulled straight from the same
    structured results the pipeline itself just computed, not re-typed by
    the LLM (which could drift from the real numbers)."""
    extra: dict[str, str] = {}

    if last_extraction:
        purchase_agreement = last_extraction.get("purchase_agreement") or {}
        income_statement = last_extraction.get("income_statement") or {}
        expenses = last_extraction.get("expenses") or {}
        extra.update({
            "propertyAddress": _stringify_extra(purchase_agreement.get("property_address")),
            "purchasePriceSek": _stringify_extra(purchase_agreement.get("purchase_price_sek")),
            "sellerName": _stringify_extra(purchase_agreement.get("seller_name")),
            "specialConditions": _stringify_extra(purchase_agreement.get("special_conditions")),
            "employer": _stringify_extra(income_statement.get("employer")),
            "monthlyGrossIncomeSek": _stringify_extra(income_statement.get("monthly_gross_income_sek")),
            "employmentType": _stringify_extra(income_statement.get("employment_type")),
            "monthlyExpensesSek": _stringify_extra(expenses.get("monthly_expenses_total_sek")),
        })

    if last_credit_assessment:
        extra.update({
            "creditDecision": _stringify_extra(last_credit_assessment.get("decision")),
            "creditDecisionReasons": _stringify_extra(last_credit_assessment.get("reasons")),
            "dtiPercent": _stringify_extra(last_credit_assessment.get("dti_percent")),
            "ltvPercent": _stringify_extra(last_credit_assessment.get("ltv_percent")),
        })

    for key, value in extra_fields.items():
        extra[key] = _stringify_extra(value)

    if customer_id:
        extra["auditCustomerId"] = customer_id

    return extra


def run_mortgage_agent(history: list[dict], lang: str | None = None) -> tuple[str, list[str], dict]:
    has_identity_hint = bool(re.search(r"\d{6,8}[-\s]?\d{4}", " ".join(
        m.get("content", "") for m in history if m.get("role") == "user"
    )))

    if not has_identity_hint:
        key = "sv" if lang == "sv" else "en"
        return ASK_IDENTITY_TEXT[key], [], {"form": IDENTITY_FORM}

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)

    documents_attached = len(_extract_attached_documents(history))

    if documents_attached >= 3:
        messages.append({
            "role": "system",
            "content": (
                "All prerequisites are present (identity details and 3 attached documents). "
                "In THIS reply, run the full pipeline via tool calls as described in step 3 of "
                "your instructions, ending with either a Loan Promise, a review hand-off, or a "
                "decline. Do NOT ask the customer to confirm the purchase price or a loan "
                "amount first - extract_mortgage_documents will give you the price, and if no "
                "specific loan amount was stated anywhere in this conversation, use 85% of "
                "that price automatically. Do not just ask another clarifying question. If "
                "extraction comes back needs_review=true, your reply must summarize the actual "
                "special_conditions in plain language, not just say 'special conditions exist'."
            ),
        })
    else:
        # Identity is already confirmed present (handled above, before the
        # LLM is even called) - only documents can still be missing here.
        reminder = (
            f"Still missing: attached documents ({documents_attached}/3 so far). Ask for "
            "whichever are still missing - do not call extract_mortgage_documents, "
            "run_credit_assessment, or any later tool yet."
        )
        if _wants_loan_indication(history):
            reminder += (
                " The customer is asking for a loan indication/offer/estimate - in THIS reply, "
                "call fetch_lf_page(\"home_loan\") and share the real calculator link from its "
                "results, AND explain that an actual indication/offer here in chat needs the "
                "documents above."
            )
        messages.append({"role": "system", "content": reminder})

    last_extraction: dict | None = None
    last_credit_assessment: dict | None = None
    seen_urls: set[str] = set()

    for round_index in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=config.OPENROUTER_MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.3,
        )
        choice = response.choices[0].message
        tool_calls = choice.tool_calls or []

        assistant_msg = {"role": "assistant", "content": choice.content or ""}
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.function.name, "arguments": call.function.arguments},
                }
                for call in tool_calls
            ]
        messages.append(assistant_msg)

        if not tool_calls:
            reply = strip_unverified_links(choice.content or "", seen_urls)
            last_user_message = next(
                (m.get("content", "") for m in reversed(history) if m.get("role") == "user"), ""
            )
            return reply, generate_suggestions(last_user_message, reply), {}

        for call in tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            name = call.function.name
            if name == "fetch_lf_page":
                topic = args.get("topic", "")
                result = fetch_lf_page(topic)
                seen_urls.update(URL_RE.findall(result))
                if topic in LF_PAGES:
                    # The page's own URL never appears inside the fetched
                    # text itself (self-links are filtered out) - add it to
                    # the verified set AND spell it out in the text so the
                    # model has a real string to copy, not just an entry on
                    # an allowlist it can't see.
                    seen_urls.add(LF_PAGES[topic])
                    result += f"\n\n(This page's own URL: {LF_PAGES[topic]})"
            elif name == "verify_customer_identity":
                result = verify_customer_identity(
                    args.get("name", ""), args.get("personnummer", ""), args.get("dob", "")
                )
            elif name == "extract_mortgage_documents":
                docs = _extract_attached_documents(history)
                last_extraction = document_agent.extract_and_verify(docs)
                result = json.dumps(last_extraction, ensure_ascii=False)
            elif name == "run_credit_assessment":
                last_credit_assessment = credit_agent.assess_credit(
                    args.get("customer_id", ""),
                    float(args.get("monthly_gross_income_sek", 0) or 0),
                    float(args.get("monthly_expenses_sek", 0) or 0),
                    float(args.get("loan_amount_sek", 0) or 0),
                    float(args.get("property_value_sek", 0) or 0),
                )
                result = json.dumps(last_credit_assessment, ensure_ascii=False)
            elif name == "fetch_interest_rate":
                customer_id = args.get("customer_id", "")
                customer = _find_customer(customer_id)
                tier = customer["tier"] if customer else "Standard"
                result = json.dumps(loan_calc.get_interest_rate(customer_id, tier), ensure_ascii=False)
            elif name == "calculate_loan_terms":
                result = json.dumps(
                    loan_calc.calculate_loan_terms(
                        args.get("customer_id", ""),
                        float(args.get("loan_amount_sek", 0) or 0),
                        float(args.get("annual_rate_percent", 0) or 0),
                    ),
                    ensure_ascii=False,
                )
            elif name == "create_review_case":
                customer_id = args.get("customer_id") or ""
                extra = _build_case_extra(
                    last_extraction, last_credit_assessment, customer_id or None,
                    reason=args.get("reason", ""),
                )
                case_id, status = cs_client.create_case_with_fallback(
                    "mortgage_review",
                    args.get("customer_name", ""),
                    customer_id or None,
                    args.get("reason", "Mortgage application flagged for manual review."),
                    extra,
                )
                audit.record_event(
                    agent="mortgage_agent", action="route_to_customer_advisor",
                    customer_id=customer_id or None, decision="MANUAL_REVIEW",
                    details={"case_id": case_id, "reason": args.get("reason", ""), "extra": extra},
                )
                result = f"Case created.\nCase ID: {case_id}\nStatus: {status}"
            elif name == "trigger_operations_case":
                customer_id = args.get("customer_id", "")
                description = (
                    f"Approved mortgage for {args.get('customer_name', '')}: "
                    f"{args.get('loan_amount_sek')} SEK at {args.get('interest_rate_percent')}%, "
                    f"monthly payment {args.get('monthly_payment_sek')} SEK. "
                    f"Property: {args.get('property_address', 'n/a')}. "
                    "Next: e-signature, account opening, disbursement."
                )
                extra = _build_case_extra(
                    last_extraction, last_credit_assessment, customer_id or None,
                    loanAmountSek=args.get("loan_amount_sek", ""),
                    interestRatePercent=args.get("interest_rate_percent", ""),
                    monthlyPaymentSek=args.get("monthly_payment_sek", ""),
                )
                case_id, status = cs_client.create_case_with_fallback(
                    "mortgage_operations",
                    args.get("customer_name", ""),
                    customer_id or None,
                    description,
                    extra,
                )
                audit.record_event(
                    agent="mortgage_agent", action="trigger_operations_case",
                    customer_id=customer_id or None, decision="APPROVED_TO_OPERATIONS",
                    details={"case_id": case_id, **args, "extra": extra},
                )
                result = f"Operations case created.\nCase ID: {case_id}\nStatus: {status}"
            else:
                result = f"Unknown tool '{name}'."

            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

    fallback = (
        "I wasn't able to finish processing your mortgage application in this pass - "
        "could you confirm the details you've given so far, or try again?"
    )
    return fallback, [], {}
