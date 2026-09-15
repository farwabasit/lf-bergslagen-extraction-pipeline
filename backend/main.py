import re
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import audit, cs_client, metrics
from .agent import run_agent
from .sessions import sessions
from .topic_classifier import classify_topic
from .uploads import extract_text

CASE_ID_RE = re.compile(r"CASE-\d{6}")

app = FastAPI(title="Life Transition Navigator")

# Lets the separate Customer Service (Java) app poll a session's transcript
# directly from its own browser page after picking up a chat hand-off - a
# different origin/port, demo-permissive like the CS app's own CORS config.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_cache_frontend(request, call_next):
    """Without this, a browser can end up with an updated style.css/app.js
    but a stale cached index.html (or vice versa) after a frontend change -
    each file revalidates independently, so a page reload doesn't guarantee
    a *consistent* set. That mismatch is exactly what produced a real bug
    once: a leftover flex rule from new CSS applied to old HTML markup
    ballooned a button's height. `no-cache` forces every frontend file to
    revalidate with the server on each load (still fast via 304s - this
    doesn't disable caching, just the "trust it without asking" part), so
    the files in a page load are always from the same version."""
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache"
    return response


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


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    history = [m.model_dump() for m in req.messages]
    reply, suggestions, extra = run_agent(history, lang=req.lang)

    if req.session_id and history:
        sessions.add_message(req.session_id, "user", history[-1]["content"])
        sessions.add_message(req.session_id, "assistant", reply)

    case_match = CASE_ID_RE.search(reply)
    metrics.record_interaction(
        session_id=req.session_id,
        topic=classify_topic(history),
        lang=req.lang,
        case_created=bool(case_match),
        case_id=case_match.group(0) if case_match else None,
    )

    return {"role": "assistant", "content": reply, "suggestions": suggestions, **extra}


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


@app.get("/api/metrics/summary")
def get_metrics_summary(days: int = 14) -> dict:
    """Everything the AI Hub monitoring dashboard renders - interaction
    volumes, topics, handoffs, cases, satisfaction, and token consumption.
    Demo-only: a real deployment would put real access control (internal
    AI Hub staff only) in front of this endpoint, same caveat as /api/audit."""
    return metrics.build_summary(days=days)


@app.get("/api/audit/verify")
def verify_audit_chain() -> dict:
    """Recomputes the hash chain over the whole audit log and reports
    whether it's intact - the check an auditor would run first."""
    return audit.verify_chain()


@app.get("/api/audit/{customer_id}")
def get_audit_trail(customer_id: str) -> dict:
    """Every logged agent decision for one customer_id, in order - the
    underlying data behind any mortgage/credit/document decision made about
    them. Demo-only: a real deployment would put real access control (only
    auditors/compliance, not any caller) in front of this endpoint."""
    return {"customer_id": customer_id, "events": audit.read_events(customer_id)}


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
