#!/usr/bin/env bash
# lab.sh — Launch an LLM security lab behind Seraph's guardrail proxy
#
# Usage:
#   ./lab.sh          # interactive menu
#   ./lab.sh 3        # launch level 3 directly
#
# Prerequisites:
#   - Seraph dependencies installed (.venv with Python 3.10-3.12)
#   - OPENAI_API_KEY set in env or in the level's .env file

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TUTOR_DIR="$SCRIPT_DIR/Tutor-main/LLM"
SERAPH_PORT=8000
SERAPH_PID=""
APP_PID=""

# Level descriptions — format: "number|port|description"
LEVELS=(
    "1|6001|Basic RAG"
    "2|5002|Guard Rails"
    "3|5003|IP-Based Guards"
    "4|5004|Tool Misuse Agent"
    "5|5005|Calendar Webhook Agent"
    "6|5006|Multi-Modal Vision Injection"
    "7|5055|Memory Poisoning"
    "8|5055|Schema Confusion"
    "9|5055|Customer Support Indirect Injection"
    "10|5010|Multi-Agent Email Poisoning"
)

cleanup() {
    echo ""
    echo "[lab] Shutting down..."
    [[ -n "$APP_PID" ]] && kill "$APP_PID" 2>/dev/null || true
    [[ -n "$SERAPH_PID" ]] && kill "$SERAPH_PID" 2>/dev/null || true
    wait 2>/dev/null || true
    echo "[lab] Done."
}
trap cleanup EXIT INT TERM

get_level_info() {
    local level="$1"
    for entry in "${LEVELS[@]}"; do
        local num="${entry%%|*}"
        if [[ "$num" == "$level" ]]; then
            echo "$entry"
            return
        fi
    done
    echo ""
}

resolve_openai_key() {
    local level="$1"
    # 1. Check env var
    if [[ -n "${OPENAI_API_KEY:-}" ]]; then
        echo "$OPENAI_API_KEY"
        return
    fi
    # 2. Check level's .env file
    local env_file="$TUTOR_DIR/level-$level/.env"
    if [[ -f "$env_file" ]]; then
        local key
        key=$(grep -E '^OPENAI_API_KEY=' "$env_file" 2>/dev/null | head -1 | cut -d= -f2-)
        if [[ -n "$key" ]]; then
            echo "$key"
            return
        fi
    fi
    echo ""
}

show_menu() {
    echo ""
    echo "=============================================="
    echo "  Seraph Lab - LLM Security Challenge Launcher"
    echo "=============================================="
    echo ""
    for entry in "${LEVELS[@]}"; do
        IFS='|' read -r num port desc <<< "$entry"
        printf "  %2s) %-45s [:%s]\n" "$num" "$desc" "$port"
    done
    echo ""
    echo "   0) Quit"
    echo ""
    read -rp "Select level [1-10]: " choice
    echo "$choice"
}

start_seraph() {
    local openai_key="$1"

    # Force-kill any old Seraph process and clear caches
    pkill -9 -f "uvicorn app.main" 2>/dev/null || true
    sleep 1

    # Wait until port is actually free
    local port_retries=10
    while lsof -i ":$SERAPH_PORT" >/dev/null 2>&1; do
        port_retries=$((port_retries - 1))
        if [[ $port_retries -le 0 ]]; then
            echo "[lab] ERROR: Port $SERAPH_PORT still in use after killing Seraph"
            exit 1
        fi
        sleep 0.5
    done

    # Clear Python bytecode cache to ensure fresh code loads
    find "$SCRIPT_DIR/app" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

    echo "[lab] Starting Seraph on port $SERAPH_PORT (clean start)..."
    cd "$SCRIPT_DIR"

    # Use .venv if available, otherwise fall back to poetry run
    if [[ -f "$SCRIPT_DIR/.venv/bin/uvicorn" ]]; then
        SERAPH_RUN="$SCRIPT_DIR/.venv/bin/python -m"
    else
        SERAPH_RUN="poetry run"
    fi

    SERAPH_CONFIG="$SCRIPT_DIR/config.lab.yaml" \
    UPSTREAM_API_KEY="$openai_key" \
        $SERAPH_RUN uvicorn app.main:app \
        --host 127.0.0.1 --port "$SERAPH_PORT" \
        --log-level warning &
    SERAPH_PID=$!

    # Wait for Seraph to be ready (first run downloads ~2GB of ML models)
    local retries=240
    echo -n "[lab] Waiting for Seraph"
    while ! curl -sf "http://localhost:$SERAPH_PORT/health" >/dev/null 2>&1; do
        if ! kill -0 "$SERAPH_PID" 2>/dev/null; then
            echo ""
            echo "[lab] ERROR: Seraph process died during startup. Check logs above."
            SERAPH_PID=""
            exit 1
        fi
        retries=$((retries - 1))
        if [[ $retries -le 0 ]]; then
            echo ""
            echo "[lab] ERROR: Seraph timed out waiting for health check (120s)."
            exit 1
        fi
        echo -n "."
        sleep 0.5
    done
    echo " ready!"
}

start_level() {
    local level="$1"
    local openai_key="$2"
    local port="$3"
    local desc="$4"
    local level_dir="$TUTOR_DIR/level-$level"

    if [[ ! -d "$level_dir" ]]; then
        echo "[lab] ERROR: $level_dir not found"
        exit 1
    fi

    # Check level app dependencies are installed
    if [[ -f "$level_dir/.venv/bin/python" ]]; then
        if ! "$level_dir/.venv/bin/python" -c "import flask" 2>/dev/null; then
            echo "[lab] ERROR: Level $level dependencies not installed."
            echo "       Run: cd $level_dir && poetry install"
            exit 1
        fi
    elif ! command -v poetry &>/dev/null || ! (cd "$level_dir" && poetry run python -c "import flask" 2>/dev/null); then
        echo "[lab] ERROR: Level $level dependencies not installed."
        echo "       Run: cd $level_dir && python3 -m venv .venv && source .venv/bin/activate && poetry install"
        exit 1
    fi

    # Proxy URL — the proxy is now at the root (/{path:path}), so base_url
    # points directly at Seraph. The OpenAI SDK appends /chat/completions.
    local base_url="http://localhost:$SERAPH_PORT/v1"

    echo ""
    echo "=============================================="
    echo "  Level $level: $desc"
    echo ""
    echo "  LLM App:    http://localhost:$port"
    echo "  Seraph:     http://localhost:$SERAPH_PORT/health"
    echo "  Audit DB:   $SCRIPT_DIR/audit.db"
    echo ""
    echo "  All LLM traffic is routed through Seraph."
    echo "  Try sending prompt injections to test the guardrails!"
    echo "=============================================="
    echo ""

    if [[ "$level" == "5" ]]; then
        echo "[lab] NOTE: Level 5 has a webhook service that needs to run separately."
        echo "           See Tutor-main/LLM/level-5/docker-compose.yml"
        echo ""
    fi

    cd "$level_dir"

    # Use .venv if available, otherwise fall back to poetry run
    if [[ -f "$level_dir/.venv/bin/python" ]]; then
        LEVEL_PYTHON="$level_dir/.venv/bin/python"
    else
        LEVEL_PYTHON="poetry run python"
    fi

    OPENAI_BASE_URL="$base_url" \
    OPENAI_API_KEY="$openai_key" \
    FLASK_PORT="$port" \
        $LEVEL_PYTHON app.py
}

main() {
    local level="${1:-}"

    if [[ -z "$level" ]]; then
        level=$(show_menu)
    fi

    if [[ "$level" == "0" || "$level" == "q" ]]; then
        exit 0
    fi

    if ! [[ "$level" =~ ^[0-9]+$ ]] || [[ "$level" -lt 1 || "$level" -gt 10 ]]; then
        echo "[lab] Invalid level: $level"
        exit 1
    fi

    local info
    info=$(get_level_info "$level")
    if [[ -z "$info" ]]; then
        echo "[lab] Level $level not found"
        exit 1
    fi

    IFS='|' read -r _ port desc <<< "$info"

    local openai_key
    openai_key=$(resolve_openai_key "$level")
    if [[ -z "$openai_key" ]]; then
        echo "[lab] ERROR: No OpenAI API key found."
        echo "       Set OPENAI_API_KEY env var or add it to $TUTOR_DIR/level-$level/.env"
        exit 1
    fi

    echo "[lab] OpenAI key: ${openai_key:0:12}...${openai_key: -4}"

    start_seraph "$openai_key"
    start_level "$level" "$openai_key" "$port" "$desc"
}

main "$@"
