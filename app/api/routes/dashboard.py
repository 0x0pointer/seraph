"""
Security dashboard — real-time attack visibility and gap analysis.

Serves a single HTML page with Chart.js visualizations that auto-refresh.
Data comes from SQLite (audit_logs + risk_events) and live risk engine state.

All endpoints are read-only. No authentication required in lab mode.
"""

import json
import sqlite3
import time
import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.core.config import get_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

TEMPLATE_DIR = Path(__file__).parent.parent.parent / "templates"


def _get_db() -> sqlite3.Connection | None:
    """Get read-only SQLite connection to audit DB."""
    config = get_config()
    db_path = config.logging.audit_file
    if not db_path or not Path(db_path).exists():
        return None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        # Check if tables exist
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "audit_logs" not in tables:
            conn.close()
            return None
        return conn
    except Exception:
        return None


def _safe_json_loads(s: str | None) -> list | dict:
    if not s:
        return []
    try:
        return json.loads(s)
    except Exception:
        return []


# ── HTML Dashboard ───────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def dashboard_page():
    """Serve the security dashboard HTML page."""
    template_path = TEMPLATE_DIR / "dashboard.html"
    if not template_path.exists():
        return HTMLResponse("<h1>Dashboard template not found</h1>", status_code=500)
    return HTMLResponse(template_path.read_text())


# ── API: Live Event Feed ─────────────────────────────────────────────────────

@router.get("/api/feed")
async def feed(limit: int = 50):
    """Last N scan events with risk data."""
    conn = _get_db()
    if not conn:
        return JSONResponse({"events": [], "error": "No audit database"})

    try:
        # Join audit_logs with risk_events on timestamp proximity
        rows = conn.execute("""
            SELECT
                a.id, a.timestamp, a.direction, a.is_valid, a.violations,
                a.on_fail_actions, a.text_length, a.ip_address, a.scanner_results,
                r.severity, r.confidence, r.evidence_tags, r.policy_decision,
                r.reason_codes, r.scan_tier, r.correlation_id
            FROM audit_logs a
            LEFT JOIN risk_events r ON a.timestamp = r.timestamp AND a.direction = r.direction
            ORDER BY a.id DESC
            LIMIT ?
        """, (limit,)).fetchall()

        events = []
        for row in rows:
            violations = _safe_json_loads(row["violations"])
            on_fail = _safe_json_loads(row["on_fail_actions"])
            scanner_results = _safe_json_loads(row["scanner_results"])
            evidence = _safe_json_loads(row["evidence_tags"]) if row["evidence_tags"] else []
            reasons = _safe_json_loads(row["reason_codes"]) if row["reason_codes"] else []

            # Determine display action
            if row["policy_decision"]:
                action = row["policy_decision"]
            elif not row["is_valid"]:
                action = "blocked"
            elif any(v == "fixed" for v in (on_fail.values() if isinstance(on_fail, dict) else [])):
                action = "fixed"
            elif any(v == "monitored" for v in (on_fail.values() if isinstance(on_fail, dict) else [])):
                action = "monitored"
            else:
                action = "allowed"

            events.append({
                "id": row["id"],
                "timestamp": row["timestamp"],
                "direction": row["direction"],
                "action": action,
                "violations": violations,
                "evidence": evidence,
                "reasons": reasons,
                "severity": row["severity"] or 0,
                "confidence": row["confidence"] or 0,
                "scan_tier": row["scan_tier"] or "standard",
                "ip": row["ip_address"] or "",
                "text_length": row["text_length"] or 0,
                "scanner_scores": scanner_results,
                "correlation_id": row["correlation_id"] or "",
            })

        return JSONResponse({"events": events})
    finally:
        conn.close()


# ── API: Evidence Class Breakdown ────────────────────────────────────────────

@router.get("/api/evidence_breakdown")
async def evidence_breakdown():
    """Distribution of evidence classes across all risk events."""
    conn = _get_db()
    if not conn:
        return JSONResponse({"breakdown": {}})

    try:
        rows = conn.execute(
            "SELECT evidence_tags FROM risk_events WHERE evidence_tags IS NOT NULL"
        ).fetchall()

        counts: dict[str, int] = {}
        for row in rows:
            tags = _safe_json_loads(row["evidence_tags"])
            for tag in tags:
                counts[tag] = counts.get(tag, 0) + 1

        return JSONResponse({"breakdown": counts})
    finally:
        conn.close()


# ── API: Scanner Effectiveness Matrix ────────────────────────────────────────

@router.get("/api/scanner_matrix")
async def scanner_matrix():
    """Scanner effectiveness: how many times each scanner blocked/fixed/monitored."""
    conn = _get_db()
    if not conn:
        return JSONResponse({"matrix": {}})

    try:
        rows = conn.execute(
            "SELECT violations, on_fail_actions, scanner_results FROM audit_logs"
        ).fetchall()

        matrix: dict[str, dict[str, int]] = {}

        for row in rows:
            violations = _safe_json_loads(row["violations"])
            on_fail = _safe_json_loads(row["on_fail_actions"])
            scanner_results = _safe_json_loads(row["scanner_results"])

            # Count each scanner's outcome
            for scanner, score in (scanner_results.items() if isinstance(scanner_results, dict) else []):
                base = scanner.split(" (")[0] if " (" in scanner else scanner
                if base not in matrix:
                    matrix[base] = {"triggered": 0, "blocked": 0, "fixed": 0, "monitored": 0, "passed": 0}

                if score > 0:
                    matrix[base]["triggered"] += 1
                    action = on_fail.get(scanner, "") if isinstance(on_fail, dict) else ""
                    if action == "blocked" or scanner in violations:
                        matrix[base]["blocked"] += 1
                    elif action == "fixed":
                        matrix[base]["fixed"] += 1
                    elif action == "monitored":
                        matrix[base]["monitored"] += 1
                    else:
                        matrix[base]["passed"] += 1

        return JSONResponse({"matrix": matrix})
    finally:
        conn.close()


# ── API: OWASP Coverage ─────────────────────────────────────────────────────

@router.get("/api/owasp_coverage")
async def owasp_coverage():
    """OWASP LLM Top 10 event counts from risk_events."""
    conn = _get_db()
    if not conn:
        return JSONResponse({"coverage": {}})

    try:
        # Get OWASP categories from risk_scoring
        from app.services.risk_scoring import SCANNER_PROFILES, OwaspCategory

        # Initialize all categories
        coverage = {cat.value: 0 for cat in OwaspCategory}

        rows = conn.execute(
            "SELECT scanner_scores, evidence_tags FROM risk_events WHERE severity > 0.3"
        ).fetchall()

        for row in rows:
            scores = _safe_json_loads(row["scanner_scores"])
            if isinstance(scores, dict):
                for scanner_name, score in scores.items():
                    if score > 0:
                        base = scanner_name.split(" (")[0]
                        profile = SCANNER_PROFILES.get(base)
                        if profile:
                            for owasp in profile.owasp:
                                coverage[owasp.value] += 1

        return JSONResponse({"coverage": coverage})
    finally:
        conn.close()


# ── API: Risk Timeline ───────────────────────────────────────────────────────

@router.get("/api/risk_timeline")
async def risk_timeline():
    """Risk events per minute for the last hour."""
    conn = _get_db()
    if not conn:
        return JSONResponse({"timeline": []})

    try:
        rows = conn.execute("""
            SELECT
                strftime('%Y-%m-%dT%H:%M', timestamp) as minute,
                policy_decision,
                COUNT(*) as count,
                AVG(severity) as avg_severity
            FROM risk_events
            WHERE timestamp > datetime('now', '-1 hour')
            GROUP BY minute, policy_decision
            ORDER BY minute
        """).fetchall()

        timeline: dict[str, dict] = {}
        for row in rows:
            minute = row["minute"]
            if minute not in timeline:
                timeline[minute] = {"minute": minute, "total": 0, "blocked": 0, "allowed": 0, "avg_severity": 0}
            timeline[minute]["total"] += row["count"]
            timeline[minute]["avg_severity"] = max(timeline[minute]["avg_severity"], row["avg_severity"] or 0)
            if row["policy_decision"] in ("hard_block", "tarpit", "rate_limit"):
                timeline[minute]["blocked"] += row["count"]
            else:
                timeline[minute]["allowed"] += row["count"]

        return JSONResponse({"timeline": list(timeline.values())})
    finally:
        conn.close()


# ── API: Client Risk Scoreboard ──────────────────────────────────────────────

@router.get("/api/client_scoreboard")
async def client_scoreboard():
    """Top 10 riskiest clients from live in-memory state."""
    from app.services.risk_engine import get_risk_engine
    from app.services.risk_state import determine_risk_level

    engine = get_risk_engine()
    if not engine:
        return JSONResponse({"clients": []})

    now = time.monotonic()
    clients = []

    for scope_id, state in list(engine.principals._states.items())[:50]:
        fast = state.fast_window.current(now)
        slow = state.slow_window.current(now)
        level = determine_risk_level(fast, slow)
        clients.append({
            "client_id": scope_id,
            "fast_score": round(fast, 3),
            "slow_score": round(slow, 3),
            "risk_level": level,
            "total_requests": state.total_requests,
            "total_violations": state.total_violations,
            "blocked": state.is_blocked(now),
            "evidence_families": dict(state.evidence_families_seen),
            "scanners_probed": len(state.scanner_families_probed),
        })

    # Sort by slow score descending
    clients.sort(key=lambda c: c["slow_score"], reverse=True)
    return JSONResponse({"clients": clients[:10]})


# ── API: Policy Action Distribution ──────────────────────────────────────────

@router.get("/api/policy_actions")
async def policy_actions():
    """Distribution of policy actions across all risk events."""
    conn = _get_db()
    if not conn:
        return JSONResponse({"actions": {}})

    try:
        rows = conn.execute("""
            SELECT policy_decision, COUNT(*) as count
            FROM risk_events
            GROUP BY policy_decision
            ORDER BY count DESC
        """).fetchall()

        actions = {row["policy_decision"]: row["count"] for row in rows}
        return JSONResponse({"actions": actions})
    finally:
        conn.close()


# ── API: Bypass Detection ────────────────────────────────────────────────────

@router.get("/api/bypasses")
async def bypasses(limit: int = 20):
    """Requests where input passed but output caught something = potential bypass."""
    conn = _get_db()
    if not conn:
        return JSONResponse({"bypasses": []})

    try:
        # Find output violations (is_valid=0, direction=output)
        # that have a corresponding input pass (is_valid=1, direction=input)
        # within the same second (approximate correlation)
        rows = conn.execute("""
            SELECT
                o.id, o.timestamp, o.violations as output_violations,
                o.scanner_results as output_scores,
                o.on_fail_actions as output_actions,
                i.scanner_results as input_scores,
                i.ip_address
            FROM audit_logs o
            JOIN audit_logs i ON
                i.direction = 'input'
                AND o.direction = 'output'
                AND i.is_valid = 1
                AND o.is_valid = 0
                AND abs(julianday(o.timestamp) - julianday(i.timestamp)) < 0.0001
            ORDER BY o.id DESC
            LIMIT ?
        """, (limit,)).fetchall()

        bypasses_list = []
        for row in rows:
            bypasses_list.append({
                "id": row["id"],
                "timestamp": row["timestamp"],
                "ip": row["ip_address"] or "",
                "output_violations": _safe_json_loads(row["output_violations"]),
                "output_actions": _safe_json_loads(row["output_actions"]),
                "input_scores": _safe_json_loads(row["input_scores"]),
                "output_scores": _safe_json_loads(row["output_scores"]),
            })

        return JSONResponse({"bypasses": bypasses_list})
    finally:
        conn.close()


# ── API: Summary Stats ───────────────────────────────────────────────────────

@router.get("/api/stats")
async def stats():
    """Quick summary stats for the dashboard header."""
    conn = _get_db()
    if not conn:
        return JSONResponse({"stats": {}})

    try:
        total = conn.execute("SELECT COUNT(*) as c FROM audit_logs").fetchone()["c"]
        blocked = conn.execute("SELECT COUNT(*) as c FROM audit_logs WHERE is_valid = 0").fetchone()["c"]
        risk_events_count = 0
        try:
            risk_events_count = conn.execute("SELECT COUNT(*) as c FROM risk_events").fetchone()["c"]
        except Exception:
            pass  # risk_events table may not exist

        return JSONResponse({
            "stats": {
                "total_scans": total,
                "blocked": blocked,
                "allowed": total - blocked,
                "block_rate": round(blocked / max(total, 1) * 100, 1),
                "risk_events": risk_events_count,
            }
        })
    finally:
        conn.close()
