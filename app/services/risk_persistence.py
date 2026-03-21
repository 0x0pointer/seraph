"""
Risk event persistence — async SQLite sink for risk assessment history.

Fire-and-forget: persistence failure never changes runtime decisions.
Follows the same pattern as audit_logger.py.

Schema created lazily on first write.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_sqlite_conn = None
_failure_count = 0
_last_warning_time = 0.0


async def _get_conn(db_path: str):
    """Lazy SQLite connection with schema creation."""
    global _sqlite_conn
    if _sqlite_conn is not None:
        return _sqlite_conn

    import aiosqlite
    _sqlite_conn = await aiosqlite.connect(db_path)
    await _sqlite_conn.execute("""
        CREATE TABLE IF NOT EXISTS risk_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            correlation_id TEXT NOT NULL,
            scope_type TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            direction TEXT NOT NULL,
            request_fingerprint TEXT,
            upstream_target TEXT,
            streaming_flag INTEGER DEFAULT 0,
            severity REAL,
            confidence REAL,
            evidence_tags TEXT,
            signal_attributes TEXT,
            scanner_scores TEXT,
            attack_patterns TEXT,
            policy_decision TEXT NOT NULL,
            reason_codes TEXT,
            scan_tier TEXT,
            trigger_scope_type TEXT,
            trigger_scope_id TEXT,
            trigger_window TEXT,
            decision_confidence REAL,
            similarity_group_id TEXT,
            mitigation_source TEXT,
            response_latency_ms INTEGER,
            inspected_bytes_ratio REAL
        )
    """)
    await _sqlite_conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_risk_scope ON risk_events(scope_type, scope_id, timestamp)"
    )
    await _sqlite_conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_risk_decision ON risk_events(policy_decision, timestamp)"
    )
    await _sqlite_conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_risk_correlation ON risk_events(correlation_id)"
    )
    await _sqlite_conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_risk_fingerprint ON risk_events(request_fingerprint, timestamp)"
    )
    await _sqlite_conn.commit()
    return _sqlite_conn


def _json_safe(obj: Any) -> str:
    """JSON-serialize with float32 safety."""
    if isinstance(obj, dict):
        obj = {k: float(v) if hasattr(v, 'item') else v for k, v in obj.items()}
    if isinstance(obj, set):
        obj = sorted(str(x) for x in obj)
    if isinstance(obj, (list, tuple)):
        obj = [str(x) if not isinstance(x, (str, int, float, bool, type(None))) else x for x in obj]
    return json.dumps(obj)


async def persist_event(
    db_path: str | None,
    correlation_id: str,
    scope_type: str,
    scope_id: str,
    direction: str,
    severity: float,
    confidence: float,
    evidence_tags: set | list,
    signal_attributes: set | list,
    scanner_scores: dict,
    attack_patterns: list,
    policy_decision: str,
    reason_codes: list,
    scan_tier: str = "",
    trigger_scope_type: str = "",
    trigger_scope_id: str = "",
    trigger_window: str = "",
    decision_confidence: float = 0.0,
    request_fingerprint: str = "",
    upstream_target: str = "",
    streaming_flag: bool = False,
    similarity_group_id: str = "",
    mitigation_source: str = "",
    response_latency_ms: int = 0,
    inspected_bytes_ratio: float = 1.0,
) -> None:
    """Fire-and-forget persistence of a risk event.

    Failure increments counter and emits throttled warning (1/60s).
    Never raises, never blocks runtime decisions.
    """
    global _failure_count, _last_warning_time

    if not db_path:
        return

    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        conn = await _get_conn(db_path)
        if conn:
            await conn.execute(
                """INSERT INTO risk_events
                   (timestamp, correlation_id, scope_type, scope_id, direction,
                    request_fingerprint, upstream_target, streaming_flag,
                    severity, confidence, evidence_tags, signal_attributes,
                    scanner_scores, attack_patterns,
                    policy_decision, reason_codes, scan_tier,
                    trigger_scope_type, trigger_scope_id, trigger_window,
                    decision_confidence, similarity_group_id, mitigation_source,
                    response_latency_ms, inspected_bytes_ratio)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    timestamp, correlation_id, scope_type, scope_id, direction,
                    request_fingerprint, upstream_target, int(streaming_flag),
                    float(severity), float(confidence),
                    _json_safe(evidence_tags), _json_safe(signal_attributes),
                    _json_safe(scanner_scores), _json_safe(attack_patterns),
                    policy_decision, _json_safe(reason_codes), scan_tier,
                    trigger_scope_type, trigger_scope_id, trigger_window,
                    float(decision_confidence), similarity_group_id, mitigation_source,
                    response_latency_ms, float(inspected_bytes_ratio),
                ),
            )
            await conn.commit()
            _failure_count = 0
    except Exception:
        _failure_count += 1
        import time
        now = time.monotonic()
        if now - _last_warning_time > 60.0:
            logger.warning(
                "Failed to write risk event to SQLite (failures=%d)", _failure_count
            )
            _last_warning_time = now


async def close() -> None:
    """Close SQLite connection if open."""
    global _sqlite_conn
    if _sqlite_conn is not None:
        await _sqlite_conn.close()
        _sqlite_conn = None
