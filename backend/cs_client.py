"""HTTP client for the separate Customer Service (CS) workflow application
(a Java Spring Boot service - see /cs-service). This Python app is the AI
assistant; the CS app is where a human agent works cases and picks up live
chat hand-offs. If the CS app isn't running, calls fail soft (return None)
so the assistant still works standalone, just without real case tracking."""

import os
import random

import requests

CS_APP_BASE_URL = os.environ.get("CS_APP_BASE_URL", "http://localhost:8080")
TIMEOUT_SECONDS = 5

# Local fallback store, used only if the Java CS app is unreachable, so the
# demo still works standalone. Resets whenever the Python process restarts.
_FALLBACK_CASES: dict[str, dict] = {}


def create_case(
    case_type: str,
    customer_name: str,
    customer_id: str | None,
    description: str,
    extra: dict[str, str] | None = None,
) -> dict | None:
    try:
        response = requests.post(
            f"{CS_APP_BASE_URL}/api/cases",
            json={
                "type": case_type,
                "customerName": customer_name,
                "customerId": customer_id,
                "description": description,
                "extra": extra or {},
            },
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None


def get_case(case_id: str) -> dict | None:
    """Returns the case dict, {"not_found": True}, or None if the CS app is
    unreachable AND no local fallback record exists either."""
    try:
        response = requests.get(f"{CS_APP_BASE_URL}/api/cases/{case_id}", timeout=TIMEOUT_SECONDS)
        if response.status_code == 404:
            return {"not_found": True}
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return _FALLBACK_CASES.get(case_id)


def create_case_with_fallback(
    case_type: str,
    customer_name: str,
    customer_id: str | None,
    description: str,
    extra: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Tries the real Customer Service application first; if it's not
    running, falls back to a local mock case so the demo still works
    standalone. Returns (case_id, status)."""
    result = create_case(case_type.upper(), customer_name, customer_id, description, extra)
    if result:
        return result["id"], result.get("status", "NEW")

    case_id = f"CASE-{random.randint(100000, 999999)}"
    _FALLBACK_CASES[case_id] = {
        "id": case_id,
        "type": case_type.upper(),
        "status": "NEW",
        "customerName": customer_name,
        "customerId": customer_id,
        "description": description,
        "extra": extra or {},
    }
    return case_id, "NEW (local fallback - Customer Service app unreachable)"


def notify_chat_request(session_id: str, customer_summary: str, transcript: list[dict]) -> bool:
    try:
        response = requests.post(
            f"{CS_APP_BASE_URL}/api/chat-requests",
            json={
                "sessionId": session_id,
                "customerSummary": customer_summary,
                "transcript": transcript,
            },
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return True
    except requests.RequestException:
        return False
