from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent import run_agent

app = FastAPI(title="Life Transition Navigator")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    history = [m.model_dump() for m in req.messages]
    reply = run_agent(history)
    return {"role": "assistant", "content": reply}


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
