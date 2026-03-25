"""
FastAPI server that exposes the LangGraph agent as a chat API.

Serves both the chat UI and a /chat endpoint that the frontend calls.
The agent routes all LLM calls through Seraph for guardrail scanning.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from agent import build_agent

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL = os.getenv("LLM_MODEL", "gpt-4")
SERAPH_BASE_URL = os.getenv("SERAPH_BASE_URL", "http://seraph:8000/v1")
SERAPH_API_KEY = os.getenv("SERAPH_API_KEY", "sk_seraph_abc123")
UPSTREAM_API_KEY = os.getenv("UPSTREAM_API_KEY", "")
SERAPH_HEALTH_URL = os.getenv("SERAPH_HEALTH_URL", "http://seraph:8000/health")

# ---------------------------------------------------------------------------
# Build agent once at startup
# ---------------------------------------------------------------------------

agent = build_agent(
    model_name=MODEL,
    seraph_base_url=SERAPH_BASE_URL,
    seraph_api_key=SERAPH_API_KEY,
    upstream_api_key=UPSTREAM_API_KEY,
)

# In-memory session store (conversation history per session)
sessions: dict[str, list] = {}

app = FastAPI(title="Seraph LangGraph Chatbot")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    tool_calls: list[dict] | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/")
async def index():
    """Serve the chat UI."""
    html_path = Path(__file__).parent / "chat.html"
    return HTMLResponse(html_path.read_text())


@app.get("/health")
async def health():
    """Health check — also pings Seraph."""
    seraph_ok = False
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(SERAPH_HEALTH_URL, timeout=5)
            seraph_ok = r.status_code == 200
    except Exception:
        pass
    return {
        "status": "ok",
        "app": "langgraph-chatbot",
        "seraph": "connected" if seraph_ok else "disconnected",
        "model": MODEL,
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Send a message to the LangGraph agent and return the response.

    The agent may call tools (weather, wikipedia, calculator, time) before
    producing a final answer. All LLM calls pass through Seraph.
    """
    session_id = req.session_id or str(uuid.uuid4())

    # Retrieve or create conversation history
    history = sessions.setdefault(session_id, [])
    history.append(HumanMessage(content=req.message))

    try:
        result = agent.invoke({"messages": history})
    except Exception as exc:
        error_msg = str(exc)
        # Detect Seraph guardrail blocks (HTTP 400 from proxy)
        if "400" in error_msg:
            raise HTTPException(status_code=400, detail=f"Blocked by Seraph guardrails: {error_msg}")
        raise HTTPException(status_code=502, detail=f"Agent error: {error_msg}")

    # Extract the final assistant message and any tool calls
    new_messages = result["messages"][len(history) - 1 :]  # messages added by agent
    history.clear()
    history.extend(result["messages"])

    # Find the final AI response
    reply_text = ""
    tool_calls_log = []
    for msg in new_messages:
        if isinstance(msg, AIMessage):
            if msg.content:
                reply_text = msg.content
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_calls_log.append({
                        "tool": tc["name"],
                        "args": tc["args"],
                    })

    if not reply_text:
        reply_text = "I wasn't able to generate a response."

    return ChatResponse(
        reply=reply_text,
        session_id=session_id,
        tool_calls=tool_calls_log if tool_calls_log else None,
    )


@app.post("/reset")
async def reset(req: ChatRequest | None = None):
    """Reset a conversation session."""
    if req and req.session_id and req.session_id in sessions:
        del sessions[req.session_id]
    return {"status": "ok"}
