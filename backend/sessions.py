"""Chat session store - a thin wrapper over db.py's ChatSession/ChatMessage
tables (see there), kept as its own module because it's a distinct concept
from the NBA data db.py also stores. Used to be a plain in-memory dict here,
which reset on every server restart (including a dev `--reload`) - a chat
listed in the sidebar would silently 404 the next time someone tried to
reopen it. Backed by the same SQLite/Postgres db.py already uses, so it
survives restarts like everything else there."""

from . import db


class SessionStore:
    def get_or_create(self, session_id: str) -> dict:
        return db.get_or_create_chat_session(session_id)

    def add_message(self, session_id: str, role: str, content: str, agent_name: str | None = None) -> int:
        return db.add_chat_message(session_id, role, content, agent_name)

    def request_human(self, session_id: str) -> None:
        db.set_chat_needs_human(session_id)

    def assign_agent(self, session_id: str, agent_name: str) -> None:
        db.set_chat_assigned_agent(session_id, agent_name)

    def messages_after(self, session_id: str, after: int) -> list[dict]:
        return db.get_chat_messages_after(session_id, after)

    def get(self, session_id: str) -> dict | None:
        return db.get_chat_session(session_id)

    def delete(self, session_id: str) -> bool:
        return db.delete_chat_session(session_id)

    def list_summaries(self) -> list[dict]:
        return db.list_chat_session_summaries()


sessions = SessionStore()
