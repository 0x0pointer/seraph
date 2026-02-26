#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "  ┌─────────────────────────────────────────────┐"
echo "  │           Project 73 — starting up           │"
echo "  └─────────────────────────────────────────────┘"
echo ""

# ── Virtual env ────────────────────────────────────────────────────────────
if [ ! -d "venv" ]; then
  echo "  Creating Python virtual environment..."
  python3 -m venv venv
fi

# ── Activate ───────────────────────────────────────────────────────────────
# shellcheck source=/dev/null
source "$SCRIPT_DIR/venv/bin/activate"

# ── Install / update deps ──────────────────────────────────────────────────
echo "  Installing dependencies..."
pip install -q --upgrade pip
pip install -q flask requests openai python-dotenv

# ── Check .env ─────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  echo "  ⚠  No .env file found. Copying from .env.example..."
  cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
  echo "  → Edit chatbot/.env and set TALIX_CONNECTION_KEY and OPENAI_API_KEY, then re-run."
  echo ""
  exit 1
fi

# ── Check Talix backend ────────────────────────────────────────────────────
TALIX_URL="${TALIX_API_URL:-http://localhost:8000}"
if curl -sf "$TALIX_URL/health" > /dev/null 2>&1; then
  echo "  ✓ Project 73 backend detected at $TALIX_URL"
else
  echo "  ⚠  WARNING: Project 73 backend not reachable at $TALIX_URL"
  echo "     Start it first:  cd ../backend && source venv/bin/activate && uvicorn app.main:app --reload"
  echo "     The chatbot will still start but scans will fail open."
  echo ""
fi

echo ""
echo "  ✓ Server starting at  http://localhost:3001"
echo "  Open that URL in your browser to start chatting."
echo "  Press Ctrl+C to stop."
echo ""

python3 "$SCRIPT_DIR/server.py"
