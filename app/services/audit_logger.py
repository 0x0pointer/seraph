"""
Lightweight audit logger — stdout JSON or optional SQLite.

Replaces the SQLAlchemy-based audit_service with a fire-and-forget logger.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_config

logger = logging.getLogger(__name__)

_sqlite_conn = None


async def _get_sqlite_conn():
    global _sqlite_conn
    if _sqlite_conn is not None:
        return _sqlite_conn

    import aiosqlite
    config = get_config()
    path = config.logging.audit_file
    if not path:
        return None

    _sqlite_conn = await aiosqlite.connect(path)
    await _sqlite_conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            direction TEXT NOT NULL,
            is_valid INTEGER NOT NULL,
            scanner_results TEXT,
            violations TEXT,
            on_fail_actions TEXT,
            text_length INTEGER,
            fix_applied INTEGER DEFAULT 0,
            ip_address TEXT
        )
    """)
    await _sqlite_conn.commit()
    return _sqlite_conn


async def log_scan(
    direction: str,
    is_valid: bool,
    scanner_results: dict[str, float],
    violations: list[str],
    on_fail_actions: dict[str, str] | None = None,
    text_length: int = 0,
    fix_applied: bool = False,
    ip_address: str | None = None,
) -> None:
    """Fire-and-forget audit log entry."""
    config = get_config()
    if not config.logging.audit:
        return

    timestamp = datetime.now(timezone.utc).isoformat()

    record: dict[str, Any] = {
        "timestamp": timestamp,
        "direction": direction,
        "is_valid": is_valid,
        "scanner_results": scanner_results,
        "violations": violations,
        "on_fail_actions": on_fail_actions or {},
        "text_length": text_length,
        "fix_applied": fix_applied,
    }
    if ip_address:
        record["ip_address"] = ip_address

    if config.logging.audit_file:
        try:
            conn = await _get_sqlite_conn()
            if conn:
                await conn.execute(
                    """INSERT INTO audit_logs
                       (timestamp, direction, is_valid, scanner_results, violations,
                        on_fail_actions, text_length, fix_applied, ip_address)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        timestamp, direction, int(is_valid),
                        json.dumps(scanner_results), json.dumps(violations),
                        json.dumps(on_fail_actions or {}), text_length,
                        int(fix_applied), ip_address,
                    ),
                )
                await conn.commit()
        except Exception:
            logger.exception("Failed to write SQLite audit log")
    else:
        # Stdout JSON Lines
        print(json.dumps(record), flush=True)


async def close() -> None:
    """Close SQLite connection if open."""
    global _sqlite_conn
    if _sqlite_conn is not None:
        await _sqlite_conn.close()
        _sqlite_conn = None
