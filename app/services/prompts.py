"""
Centralized guard prompts for the LLM-as-a-Judge pipeline.

Keeping all prompt templates in one place mirrors the CTF architecture pattern
(src/prompts.py) and lets security teams iterate on evaluation criteria without
hunting through implementation files.
"""
from langchain_core.prompts import ChatPromptTemplate

# ── Judge evaluation prompt templates ────────────────────────────────────────

INPUT_JUDGE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "{system_prompt}"),
    ("human", "Direction: User input\n\nText to evaluate:\n{text}"),
])

OUTPUT_JUDGE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "{system_prompt}"),
    ("human",
     "Direction: LLM output\n\n"
     "Original user prompt:\n{prompt_context}\n\n"
     "Text to evaluate:\n{text}"),
])

# ── Fallback system prompt (used when judge_prompt.txt is missing) ────────────

DEFAULT_JUDGE_PROMPT = (
    "Evaluate the following text for security threats. "
    "Respond with JSON: {{verdict, risk_score, reasoning, threats_detected}}"
)
