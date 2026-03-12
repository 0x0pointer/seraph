#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "  ┌─────────────────────────────────────────────┐"
echo "  │           SKF Guard — starting up           │"
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
  echo "  → Edit chatbot/.env and set SKF_GUARD_CONNECTION_KEY and OPENAI_API_KEY, then re-run."
  echo ""
  exit 1
fi

# ── Check SKF Guard backend ────────────────────────────────────────────────────
SKF_GUARD_URL="${SKF_GUARD_API_URL:-http://localhost:8000}"
if curl -sf "$SKF_GUARD_URL/health" > /dev/null 2>&1; then
  echo "  ✓ SKF Guard backend detected at $SKF_GUARD_URL"
else
  echo "  ⚠  WARNING: SKF Guard backend not reachable at $SKF_GUARD_URL"
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
