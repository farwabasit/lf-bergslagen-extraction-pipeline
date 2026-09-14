"""Operational/BI telemetry for the AI Hub monitoring dashboard - distinct
from audit.py, which is a compliance/decision trail scoped to one customer.
This log is anonymized (session_id only, never a customer_id or personnummer)
and answers a different question: how is Sara performing as a system, across
everyone, over time.

Append-only JSONL, same "just a file" honesty as audit.py: good enough for a
hackathon demo (single process), not a real metrics warehouse. A production
deployment would ship these events to whatever the AI Hub already uses
(a time-series DB, an events pipeline) instead of a local file.
"""

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock

METRICS_LOG_PATH = Path(__file__).resolve().parent / "metrics_log.jsonl"

_lock = Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _write(event: dict) -> None:
    event.setdefault("ts", _now().isoformat())
    with _lock:
        METRICS_LOG_PATH.parent.mkdir(exist_ok=True)
        with METRICS_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")


def record_interaction(
    session_id: str | None,
    topic: str,
    lang: str | None,
    case_created: bool,
    case_id: str | None,
) -> None:
    """One event per /api/chat turn - the unit "interaction volumes" and
    "topics covered" are counted from."""
    _write({
        "type": "interaction",
        "session_id": session_id,
        "topic": topic,
        "lang": lang or "en",
        "case_created": case_created,
        "case_id": case_id,
    })


def record_handoff(session_id: str | None, topic: str) -> None:
    """A customer actually asked to be connected to a human agent (not just
    that Sara offered the option) - the request-human endpoint records this."""
    _write({"type": "handoff", "session_id": session_id, "topic": topic})


def record_rating(session_id: str | None, rating: int) -> None:
    _write({"type": "rating", "session_id": session_id, "rating": rating})


def record_llm_usage(
    model: str | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None,
    duration_ms: float | None,
) -> None:
    """Logged automatically for every LLM call, from a single wrapper point
    in llm_client.py - see the note there. Deliberately not attributed to a
    session/topic: that would require threading session context through
    every agent's tool-calling loop, which none of them currently take as a
    parameter. Global token-consumption rollups (day/week/month/year) don't
    need that attribution; per-topic cost breakdown would be a follow-up."""
    _write({
        "type": "llm_call",
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "duration_ms": round(duration_ms, 1) if duration_ms is not None else None,
    })


def read_events(event_type: str | None = None) -> list[dict]:
    if not METRICS_LOG_PATH.exists():
        return []
    events = []
    with METRICS_LOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            entry = json.loads(line)
            if event_type is None or entry.get("type") == event_type:
                events.append(entry)
    return events


TOPIC_LABELS = {
    "mortgage_loan_promise": "Loan Promise application",
    "mortgage_loan_offer": "Loan Offer application",
    "fraud_report": "Fraud report",
    "transaction_dispute": "Transaction dispute",
    "portfolio_inquiry": "Product portfolio lookup",
    "callback_request": "Callback request",
    "case_status": "Case status lookup",
    "human_contact": "Ask to talk to a human",
    "car_repair": "Car damage / repair",
    "home_repair": "Home damage / repair",
    "health_care": "Accident / health claim",
    "home_purchase_advisory": "Buying a home - general advice",
    "general_advisory": "General advisory",
}


def _parse_ts(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _tokens_bucket(llm_events: list[dict], since: datetime | None) -> dict:
    bucket = [e for e in llm_events if since is None or _parse_ts(e["ts"]) >= since]
    prompt = sum(e.get("prompt_tokens") or 0 for e in bucket)
    completion = sum(e.get("completion_tokens") or 0 for e in bucket)
    total = sum(e.get("total_tokens") or (e.get("prompt_tokens") or 0) + (e.get("completion_tokens") or 0) for e in bucket)
    return {"calls": len(bucket), "prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}


def build_summary(days: int = 14) -> dict:
    """Everything the AI Hub dashboard renders, computed fresh from the
    event log on every call - there are no separate read/write models to
    keep in sync, and the log is small enough (JSONL, append-only) that a
    full scan per request is simple and fast enough for a demo."""
    now = _now()
    interactions = read_events("interaction")
    handoffs = read_events("handoff")
    ratings = read_events("rating")
    llm_calls = read_events("llm_call")

    # --- Interaction volumes, by day -------------------------------------
    by_day_counts: Counter[str] = Counter()
    for e in interactions:
        day = _parse_ts(e["ts"]).date().isoformat()
        by_day_counts[day] += 1
    by_day = []
    for i in range(days - 1, -1, -1):
        day = (now - timedelta(days=i)).date().isoformat()
        by_day.append({"date": day, "count": by_day_counts.get(day, 0)})

    session_ids = {e.get("session_id") for e in interactions if e.get("session_id")}

    # --- Topics -------------------------------------------------------------
    topic_counts = Counter(e.get("topic", "general_advisory") for e in interactions)
    total_interactions = len(interactions) or 1
    topics = [
        {
            "topic": topic,
            "label": TOPIC_LABELS.get(topic, topic.replace("_", " ").title()),
            "count": count,
            "pct": round(count / total_interactions * 100, 1),
        }
        for topic, count in topic_counts.most_common()
    ]

    # --- Average time spent per session (first-to-last interaction) --------
    session_span: dict[str, list[datetime]] = {}
    for e in interactions:
        sid = e.get("session_id")
        if not sid:
            continue
        ts = _parse_ts(e["ts"])
        span = session_span.setdefault(sid, [ts, ts])
        span[0] = min(span[0], ts)
        span[1] = max(span[1], ts)
    durations = [(end - start).total_seconds() for start, end in session_span.values() if end > start]
    avg_duration_seconds = round(sum(durations) / len(durations), 1) if durations else 0.0

    # --- Manual handoffs ------------------------------------------------
    handoff_sessions = {e.get("session_id") for e in handoffs if e.get("session_id")}
    handoff_topic_counts = Counter(e.get("topic", "general_advisory") for e in handoffs)

    # --- Cases triggered ---------------------------------------------------
    case_events = [e for e in interactions if e.get("case_created")]
    case_topic_counts = Counter(e.get("topic", "general_advisory") for e in case_events)

    # --- Satisfaction --------------------------------------------------
    rating_values = [e["rating"] for e in ratings if isinstance(e.get("rating"), int)]
    rating_distribution = {str(n): rating_values.count(n) for n in range(1, 6)}
    avg_rating = round(sum(rating_values) / len(rating_values), 2) if rating_values else None

    # --- Token consumption rollups -----------------------------------------
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tokens = {
        "today": _tokens_bucket(llm_calls, today_start),
        "last_7d": _tokens_bucket(llm_calls, now - timedelta(days=7)),
        "last_30d": _tokens_bucket(llm_calls, now - timedelta(days=30)),
        "last_365d": _tokens_bucket(llm_calls, now - timedelta(days=365)),
        "all_time": _tokens_bucket(llm_calls, None),
    }
    latencies = [e["duration_ms"] for e in llm_calls if isinstance(e.get("duration_ms"), (int, float))]
    avg_latency_ms = round(sum(latencies) / len(latencies), 1) if latencies else None
    models_used = Counter(e.get("model") or "unknown" for e in llm_calls)

    return {
        "generated_at": now.isoformat(),
        "interactions": {
            "total": len(interactions),
            "total_sessions": len(session_ids),
            "by_day": by_day,
        },
        "topics": topics,
        "avg_session_duration_seconds": avg_duration_seconds,
        "handoffs": {
            "sessions": len(handoff_sessions),
            "pct_of_sessions": round(len(handoff_sessions) / len(session_ids) * 100, 1) if session_ids else 0.0,
            "by_topic": [
                {"topic": t, "label": TOPIC_LABELS.get(t, t.replace("_", " ").title()), "count": c}
                for t, c in handoff_topic_counts.most_common()
            ],
        },
        "cases_triggered": {
            "count": len(case_events),
            "pct_of_interactions": round(len(case_events) / total_interactions * 100, 1),
            "by_topic": [
                {"topic": t, "label": TOPIC_LABELS.get(t, t.replace("_", " ").title()), "count": c}
                for t, c in case_topic_counts.most_common()
            ],
        },
        "satisfaction": {
            "count": len(rating_values),
            "average": avg_rating,
            "distribution": rating_distribution,
        },
        "tokens": tokens,
        "technical": {
            "total_llm_calls": len(llm_calls),
            "avg_latency_ms": avg_latency_ms,
            "avg_tokens_per_call": round(tokens["all_time"]["total_tokens"] / len(llm_calls), 1) if llm_calls else 0,
            "models_used": dict(models_used),
        },
    }
