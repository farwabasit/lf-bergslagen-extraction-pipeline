import re
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import audit, cs_client, db, interaction_context, interaction_history, metrics, nba_engine, roles, verified_customer
from .agent import run_agent
from .sessions import sessions
from .topic_classifier import classify_topic
from .uploads import extract_text

CASE_ID_RE = re.compile(r"CASE-\d{6}")

app = FastAPI(title="Life Transition Navigator")
db.init_db()

# Lets the separate Customer Service (Java) app poll a session's transcript
# directly from its own browser page after picking up a chat hand-off - a
# different origin/port, demo-permissive like the CS app's own CORS config.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

MAX_UPLOAD_BYTES = 5 * 1024 * 1024

ALLOWED_UPLOAD_EXTENSIONS = {
    ".pdf",
    ".txt",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
}


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    session_id: str | None = None
    lang: str | None = None


class HumanMessage(BaseModel):
    content: str
    agent_name: str | None = None


class CustomerMessage(BaseModel):
    content: str


class AssignAgent(BaseModel):
    agent_name: str


class RatingRequest(BaseModel):
    rating: int


class OfferClickRequest(BaseModel):
    customer_id: str
    offer_code: str


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    history = [m.model_dump() for m in req.messages]
    verified_customer.get_and_clear()  # discard any stale value from an earlier request

    # Classified from the input history (never the reply, so this is safe
    # to compute before run_agent) and stashed in a contextvar so
    # llm_client.py's instrumented wrapper can attribute each LLM call this
    # turn makes to this topic/session - see interaction_context.py and the
    # AI Analytics dashboard's per-topic token trend (metrics.py).
    topic = classify_topic(history)
    interaction_context.set_context(topic, req.session_id)

    reply, suggestions, extra = run_agent(history, lang=req.lang)

    if req.session_id and history:
        sessions.add_message(req.session_id, "user", history[-1]["content"])
        sessions.add_message(req.session_id, "assistant", reply)

    case_match = CASE_ID_RE.search(reply)
    case_id = case_match.group(0) if case_match else None
    metrics.record_interaction(
        session_id=req.session_id, topic=topic, lang=req.lang,
        case_created=bool(case_match), case_id=case_id,
    )

    # Next Best Action offers: only ever surfaced right after this exact
    # turn identity-verified a customer (see verified_customer.py) - never
    # for an unverified chat. Stored centrally (db.py) so "previous
    # interactions" and "offers clicked/not clicked" persist across
    # restarts and across everyone running this app, not just this process.
    customer_id = verified_customer.get_and_clear()
    if customer_id:
        db.record_interaction(customer_id, req.session_id, topic, case_id)
        if req.session_id:
            sessions.set_verified_customer(req.session_id, customer_id)
        # Lets the chat widget open the interaction-history panel right on
        # the turn that verified the customer, without waiting for the next
        # message - independent of whether an NBA offer happens to fire.
        extra["verified_customer_id"] = customer_id
        # Never pitch marketing offers mid fraud report or transaction
        # dispute - the customer is dealing with a security problem, not
        # browsing products, and `topic` stays "fraud_report"/
        # "transaction_dispute" for the whole flow (see
        # fraud_dispute_agent.wants_fraud_or_dispute), not just its first turn.
        if topic not in ("fraud_report", "transaction_dispute"):
            offers = nba_engine.get_offers_for_customer(customer_id, topic)
            if offers:
                extra["offers"] = offers
                extra["offers_customer_id"] = customer_id

    return {"role": "assistant", "content": reply, "suggestions": suggestions, **extra}


@app.post("/api/offers/click")
def click_offer(body: OfferClickRequest) -> dict:
    ok = nba_engine.record_click(body.customer_id, body.offer_code)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Unknown offer_code '{body.offer_code}'")
    return {"ok": True}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    filename = file.filename or "document"
    extension = Path(filename).suffix.lower()
    if extension and extension not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. Please attach a PDF, Word, Excel, text, or image file.",
        )

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 5MB)")
    text = extract_text(filename, data)
    return {"filename": filename, "text": text}


@app.post("/api/sessions/{session_id}/request-human")
def request_human(session_id: str) -> dict:
    sessions.request_human(session_id)

    session = sessions.get(session_id) or {}
    transcript = [
        {"role": m["role"], "content": m["content"]}
        for m in session.get("messages", [])
        if m["role"] in ("user", "assistant", "human")
    ]
    first_user_msg = next((m["content"] for m in transcript if m["role"] == "user"), "")
    customer_summary = first_user_msg[:80] if first_user_msg else "Customer chat"
    notified = cs_client.notify_chat_request(session_id, customer_summary, transcript)

    metrics.record_handoff(session_id, classify_topic(transcript))

    return {"ok": True, "cs_app_notified": notified}


@app.post("/api/sessions/{session_id}/rating")
def rate_session(session_id: str, body: RatingRequest) -> dict:
    """Customer satisfaction rating for the AI Hub dashboard - 1 to 5,
    submitted from the chat widget at any point in (or after) a conversation.
    Not required, not forced - just recorded if given."""
    if body.rating < 1 or body.rating > 5:
        raise HTTPException(status_code=422, detail="rating must be between 1 and 5")
    metrics.record_rating(session_id, body.rating)
    return {"ok": True}


@app.get("/api/sessions/{session_id}/poll")
def poll_session(session_id: str, after: int = 0) -> dict:
    new_messages = sessions.messages_after(session_id, after)
    total = after + len(new_messages)
    session = sessions.get(session_id) or {}
    return {
        "messages": new_messages,
        "next_after": total,
        "assigned_agent": session.get("assigned_agent"),
    }


@app.post("/api/sessions/{session_id}/customer-message")
def send_customer_message(session_id: str, body: CustomerMessage) -> dict:
    """Appends a customer message to a session that's already been handed
    off to a human - does NOT invoke the AI agent, unlike /api/chat."""
    count = sessions.add_message(session_id, "user", body.content)
    return {"ok": True, "message_count": count}


@app.post("/api/sessions/{session_id}/assign-agent")
def assign_agent(session_id: str, body: AssignAgent) -> dict:
    sessions.assign_agent(session_id, body.agent_name)
    return {"ok": True}


@app.get("/api/sessions/{session_id}/interaction-history")
def get_interaction_history(session_id: str) -> dict:
    """The chat widget's left-panel mini-portfolio: what this customer has
    talked to Sara about, and how far each thing has gotten. Keyed by
    session_id, not a customer_id the client could pass directly - only a
    session that actually verified as a customer (via verify_customer_identity
    earlier in THIS chat) gets that customer's data back, so one browser
    tab can't fetch another customer's history by guessing an id."""
    customer_id = sessions.get_verified_customer(session_id)
    if not customer_id:
        return {"verified": False, "items": []}
    return {"verified": True, "customer_id": customer_id, "items": interaction_history.build_customer_history(customer_id)}


@app.get("/api/sessions")
def list_sessions() -> dict:
    return {"sessions": sessions.list_summaries()}


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown session")
    return session


@app.post("/api/sessions/{session_id}/human-message")
def send_human_message(session_id: str, body: HumanMessage) -> dict:
    count = sessions.add_message(session_id, "human", body.content, agent_name=body.agent_name)
    return {"ok": True, "message_count": count}


# Metrics/summary keys that belong to each RBAC-gated dashboard section -
# see roles.py. /api/metrics/summary spans both sections in one payload
# (they're computed from the same event log in one pass), so the endpoint
# itself decides which keys to include rather than gating the whole call
# to a single section like the audit endpoints below do.
INTERACTIONS_SUMMARY_KEYS = {
    "interactions", "topics", "avg_session_duration_seconds",
    "handoffs", "cases_triggered", "satisfaction",
}
AI_ANALYTICS_SUMMARY_KEYS = {
    "tokens", "technical", "token_trend_by_topic", "satisfaction_latency_correlation",
}


@app.get("/api/metrics/summary")
def get_metrics_summary(days: int = 14, x_dashboard_role: str | None = Header(default=None)) -> dict:
    """Everything the AI Hub monitoring dashboard renders - interaction
    volumes, topics, handoffs, cases, satisfaction, and token consumption.
    RBAC (self-declared X-Dashboard-Role, same demo-scope caveat as
    cs-service's X-CS-Role): MANAGER sees the interactions section,
    AI_ENGINEER sees AI Analytics (technical/token data) - a role with
    access to neither gets a 403, not a trimmed-but-still-200 response."""
    role = roles.parse_role(x_dashboard_role)
    summary = metrics.build_summary(days=days)

    result = {"generated_at": summary["generated_at"]}
    if roles.can_access(role, "interactions"):
        result.update({k: v for k, v in summary.items() if k in INTERACTIONS_SUMMARY_KEYS})
    if roles.can_access(role, "ai_analytics"):
        result.update({k: v for k, v in summary.items() if k in AI_ANALYTICS_SUMMARY_KEYS})

    if len(result) == 1:
        raise HTTPException(status_code=403, detail=f"{role} is not authorized for any dashboard analytics section.")
    return result


@app.get("/api/audit/recent")
def get_recent_audit_events(limit: int = 50, x_dashboard_role: str | None = Header(default=None)) -> dict:
    """Concise, cross-customer feed of recent agent actions/decisions for
    the AI Hub dashboard's Audit History section. MANAGER and AUDITOR only."""
    roles.require_role(x_dashboard_role, "audit_trail")
    return {"events": audit.read_recent_events(limit=limit)}


@app.get("/api/audit/verify")
def verify_audit_chain(x_dashboard_role: str | None = Header(default=None)) -> dict:
    """Recomputes the hash chain over the whole audit log and reports
    whether it's intact - the check an auditor would run first."""
    roles.require_role(x_dashboard_role, "audit_trail")
    return audit.verify_chain()


@app.get("/api/audit/{customer_id}")
def get_audit_trail(customer_id: str, x_dashboard_role: str | None = Header(default=None)) -> dict:
    """Every logged agent decision for one customer_id, in order - the
    underlying data behind any mortgage/credit/document decision made about
    them. MANAGER and AUDITOR only."""
    roles.require_role(x_dashboard_role, "audit_trail")
    return {"customer_id": customer_id, "events": audit.read_events(customer_id)}


class OfferTierRulesRequest(BaseModel):
    offer_code: str
    tiers: list[str]


class CooldownRequest(BaseModel):
    cooldown_seconds: int


@app.get("/api/contact-rules")
def get_contact_rules(x_dashboard_role: str | None = Header(default=None)) -> dict:
    """Everything the Marketing team's Contact Rules panel edits: the
    offer-click cooldown, and each offer's current tier targeting. MARKETING
    role only - see roles.py and nba_engine.get_offers_for_customer for
    where these settings actually take effect."""
    roles.require_role(x_dashboard_role, "contact_rules")
    return {
        "cooldown_seconds": db.get_cooldown_seconds(),
        "valid_tiers": nba_engine.VALID_TIERS,
        "offers": nba_engine.list_offers_for_admin(),
    }


@app.post("/api/contact-rules/cooldown")
def set_contact_rules_cooldown(body: CooldownRequest, x_dashboard_role: str | None = Header(default=None)) -> dict:
    roles.require_role(x_dashboard_role, "contact_rules")
    if body.cooldown_seconds < 0 or body.cooldown_seconds > 86400:
        raise HTTPException(status_code=422, detail="cooldown_seconds must be between 0 and 86400 (24h).")
    db.set_cooldown_seconds(body.cooldown_seconds)
    return {"ok": True, "cooldown_seconds": body.cooldown_seconds}


@app.post("/api/contact-rules/offer-tiers")
def set_contact_rules_offer_tiers(body: OfferTierRulesRequest, x_dashboard_role: str | None = Header(default=None)) -> dict:
    roles.require_role(x_dashboard_role, "contact_rules")
    if body.offer_code not in nba_engine._BY_CODE:
        raise HTTPException(status_code=404, detail=f"Unknown offer_code '{body.offer_code}'.")
    unknown_tiers = set(body.tiers) - set(nba_engine.VALID_TIERS)
    if unknown_tiers:
        raise HTTPException(status_code=422, detail=f"Unknown tier(s): {', '.join(sorted(unknown_tiers))}.")
    db.set_offer_tier_restrictions(body.offer_code, body.tiers)
    return {"ok": True, "offer_code": body.offer_code, "tiers": body.tiers}


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
