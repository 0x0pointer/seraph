import os
import logging

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from openai import OpenAI
import requests

load_dotenv()

API_URL = os.getenv("SERAPH_API_URL", "http://localhost:8000")
API_KEY = os.getenv("SERAPH_CONNECTION_KEY", "")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder=".")
openai_client = OpenAI(api_key=OPENAI_KEY)

SYSTEM_PROMPT = (
    "You are a helpful, friendly AI assistant. "
    "Answer clearly and concisely. "
    "All messages are screened by Seraph guardrails for safety."
)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }


def is_chatbot_enabled() -> bool:
    """Check whether the chatbot is enabled via platform settings."""
    try:
        resp = requests.get(f"{API_URL}/api/public/platform-info", timeout=5)
        resp.raise_for_status()
        return resp.json().get("chatbot_enabled", True)
    except requests.RequestException as exc:
        logger.warning("Could not fetch platform-info: %s — defaulting to enabled", exc)
        return True


def scan_input(text: str) -> dict:
    """Run the user message through Seraph input guardrails."""
    try:
        resp = requests.post(
            f"{API_URL}/api/scan/prompt",
            json={"text": text},
            headers=_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.error("Input scan failed: %s", exc)
        # Fail open — let the message through but log the error
        return {"is_valid": True, "sanitized_text": text, "violation_scanners": [], "scanner_results": {}}


def scan_output(text: str, prompt: str) -> dict:
    """Run the AI response through Seraph output guardrails."""
    try:
        resp = requests.post(
            f"{API_URL}/api/scan/output",
            json={"text": text, "prompt": prompt},
            headers=_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.error("Output scan failed: %s", exc)
        return {"is_valid": True, "sanitized_text": text, "violation_scanners": [], "scanner_results": {}}


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/status")
def status():
    """Returns whether the chatbot is currently enabled."""
    return jsonify({"chatbot_enabled": is_chatbot_enabled()})


@app.route("/chat", methods=["POST"])
def chat():
    if not is_chatbot_enabled():
        return jsonify({"error": "The chatbot is currently offline. Please try again later."}), 503

    body = request.get_json(force=True)
    user_message: str = (body.get("message") or "").strip()
    history: list = body.get("history") or []

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    # ── 1. Scan user input ────────────────────────────────────────────────────
    input_scan = scan_input(user_message)
    if not input_scan.get("is_valid", True):
        logger.info("Input blocked: %s", input_scan.get("violation_scanners"))
        return jsonify({
            "blocked": True,
            "direction": "input",
            "violations": input_scan.get("violation_scanners", []),
            "scanner_results": input_scan.get("scanner_results", {}),
            "message": "Your message was blocked by Seraph guardrails.",
        })

    # Use sanitized text if it was modified
    safe_message = input_scan.get("sanitized_text") or user_message

    # ── 2. Build conversation and call OpenAI ─────────────────────────────────
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for entry in history:
        role = entry.get("role")
        content = entry.get("content", "")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": safe_message})

    try:
        completion = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
        )
    except Exception as exc:
        logger.error("OpenAI call failed: %s", exc)
        return jsonify({"error": "The AI service is temporarily unavailable. Please try again."}), 502

    ai_response: str = completion.choices[0].message.content or ""

    # ── 3. Scan AI output ─────────────────────────────────────────────────────
    output_scan = scan_output(ai_response, safe_message)
    if not output_scan.get("is_valid", True):
        logger.info("Output blocked: %s", output_scan.get("violation_scanners"))
        return jsonify({
            "blocked": True,
            "direction": "output",
            "violations": output_scan.get("violation_scanners", []),
            "scanner_results": output_scan.get("scanner_results", {}),
            "message": "The AI response was blocked by Seraph guardrails.",
        })

    final_response = output_scan.get("sanitized_text") or ai_response

    return jsonify({
        "blocked": False,
        "response": final_response,
        "input_scan": {
            "violations": input_scan.get("violation_scanners", []),
        },
        "output_scan": {
            "violations": output_scan.get("violation_scanners", []),
        },
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 3001))
    logger.info("Seraph chatbot running on http://localhost:%d", port)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
