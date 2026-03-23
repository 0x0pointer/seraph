"""
LangGraph ReAct agent with 4 tools, routed through Seraph guardrail proxy.

All LLM calls go through Seraph so that prompt-injection, toxicity,
secrets-leakage and other guardrails are applied transparently.
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

import httpx
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool
def get_weather(city: str) -> str:
    """Get the current weather for a city using the free wttr.in API."""
    try:
        resp = httpx.get(
            f"https://wttr.in/{city}",
            params={"format": "j1"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        current = data["current_condition"][0]
        desc = current["weatherDesc"][0]["value"]
        temp_c = current["temp_C"]
        humidity = current["humidity"]
        wind = current["windspeedKmph"]
        return (
            f"Weather in {city}: {desc}, {temp_c}°C, "
            f"humidity {humidity}%, wind {wind} km/h"
        )
    except Exception as exc:
        return f"Could not fetch weather for {city}: {exc}"


@tool
def search_wikipedia(query: str) -> str:
    """Search Wikipedia and return a short summary of the top result."""
    try:
        resp = httpx.get(
            "https://en.wikipedia.org/api/rest_v1/page/summary/" + query.replace(" ", "_"),
            headers={"User-Agent": "SeraphChatbot/1.0"},
            timeout=10,
            follow_redirects=True,
        )
        if resp.status_code == 404:
            # Fallback: use search API
            search = httpx.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "opensearch",
                    "search": query,
                    "limit": 1,
                    "format": "json",
                },
                timeout=10,
            )
            results = search.json()
            if len(results) >= 4 and results[1]:
                title = results[1][0]
                resp = httpx.get(
                    f"https://en.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '_')}",
                    headers={"User-Agent": "SeraphChatbot/1.0"},
                    timeout=10,
                    follow_redirects=True,
                )
            else:
                return f"No Wikipedia article found for '{query}'."
        resp.raise_for_status()
        data = resp.json()
        return f"{data.get('title', query)}: {data.get('extract', 'No summary available.')}"
    except Exception as exc:
        return f"Wikipedia search failed: {exc}"


@tool
def calculate(expression: str) -> str:
    """Evaluate a mathematical expression. Supports basic arithmetic, powers, sqrt, log, sin, cos, pi, e.

    Examples: "2 + 3 * 4", "sqrt(144)", "log(100)", "sin(pi/2)"
    """
    allowed_names = {
        "sqrt": math.sqrt,
        "log": math.log,
        "log10": math.log10,
        "log2": math.log2,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "pi": math.pi,
        "e": math.e,
        "abs": abs,
        "pow": pow,
        "round": round,
    }
    try:
        result = eval(expression, {"__builtins__": {}}, allowed_names)  # noqa: S307
        return f"{expression} = {result}"
    except Exception as exc:
        return f"Could not evaluate '{expression}': {exc}"


@tool
def get_current_time(timezone_name: str = "UTC") -> str:
    """Get the current date and time in a given timezone.

    Examples: "UTC", "Europe/Amsterdam", "US/Eastern", "Asia/Tokyo"
    """
    try:
        tz = ZoneInfo(timezone_name)
        now = datetime.now(tz)
        return f"Current time in {timezone_name}: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}"
    except Exception as exc:
        return f"Could not get time for timezone '{timezone_name}': {exc}"


# ---------------------------------------------------------------------------
# LangGraph agent
# ---------------------------------------------------------------------------

TOOLS = [get_weather, search_wikipedia, calculate, get_current_time]


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


def build_agent(
    model_name: str = "gpt-4",
    seraph_base_url: str | None = None,
    seraph_api_key: str | None = None,
    upstream_api_key: str | None = None,
) -> StateGraph:
    """Build a LangGraph ReAct agent that routes LLM calls through Seraph."""

    base_url = seraph_base_url or os.getenv("SERAPH_BASE_URL", "http://seraph:8000/v1")
    api_key = upstream_api_key or os.getenv("UPSTREAM_API_KEY", "sk-placeholder")
    seraph_key = seraph_api_key or os.getenv("SERAPH_API_KEY", "sk_seraph_abc123")

    # api_key is used by the OpenAI SDK as the Authorization header.
    # We set it to the Seraph key so Seraph authenticates the request.
    # The real upstream LLM key goes in X-Upstream-Auth for Seraph to forward.
    llm = ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=seraph_key,
        default_headers={
            "X-Upstream-Auth": f"Bearer {api_key}",
        },
        temperature=0,
    )

    llm_with_tools = llm.bind_tools(TOOLS)

    def call_model(state: AgentState) -> dict:
        response = llm_with_tools.invoke(state["messages"])
        return {"messages": [response]}

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return END

    tool_node = ToolNode(TOOLS)

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", tool_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph.compile()
