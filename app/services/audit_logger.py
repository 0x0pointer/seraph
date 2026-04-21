"""
Lightweight audit logger — stdout JSON or optional SQLite.

Replaces the SQLAlchemy-based audit_service with a fire-and-forget logger.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_config


def _json_dumps(obj, **kwargs) -> str:
    """JSON dumps that handles numpy float32/int types."""
    def default(o):
        try:
            return float(o)
        except (TypeError, ValueError):
            raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")
    return json.dumps(obj, default=default, **kwargs)

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
            ip_address TEXT,
            segments TEXT,
            metadata TEXT
        )
    """)
    # Add columns if upgrading from older schema
    for col in ("segments TEXT", "metadata TEXT"):
        try:
            await _sqlite_conn.execute(f"ALTER TABLE audit_logs ADD COLUMN {col}")
        except Exception:
            pass
    await _sqlite_conn.commit()
    return _sqlite_conn


def _serialize_segments(segments: list | None) -> str | None:
    """Serialize segment objects or dicts to a JSON string."""
    if not segments:
        return None
    seg_list = []
    for s in segments:
        if isinstance(s, dict):
            seg_list.append(s)
        else:
            seg_list.append({"role": s.role, "source": s.source, "text": s.text})
    return _json_dumps(seg_list, ensure_ascii=False)


def _build_record(
    timestamp: str,
    direction: str,
    is_valid: bool,
    scanner_results: dict[str, Any],
    violations: list[str],
    on_fail_actions: dict[str, str] | None,
    text_length: int,
    fix_applied: bool,
    ip_address: str | None,
    segments_json: str | None,
    metadata: dict | None,
) -> dict[str, Any]:
    """Build the audit log record dict for stdout output."""
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
    if segments_json:
        record["segments"] = json.loads(segments_json)
    if metadata:
        record["metadata"] = metadata
    return record


async def _write_sqlite(
    timestamp: str,
    direction: str,
    is_valid: bool,
    scanner_results: dict[str, Any],
    violations: list[str],
    on_fail_actions: dict[str, str] | None,
    text_length: int,
    fix_applied: bool,
    ip_address: str | None,
    segments_json: str | None,
    metadata_json: str | None,
) -> None:
    """Write an audit log entry to SQLite."""
    conn = await _get_sqlite_conn()
    if not conn:
        return
    await conn.execute(
        """INSERT INTO audit_logs
           (timestamp, direction, is_valid, scanner_results, violations,
            on_fail_actions, text_length, fix_applied, ip_address,
            segments, metadata)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            timestamp, direction, int(is_valid),
            _json_dumps(scanner_results), _json_dumps(violations),
            _json_dumps(on_fail_actions or {}), text_length,
            int(fix_applied), ip_address, segments_json,
            metadata_json,
        ),
    )
    await conn.commit()


async def log_scan(
    direction: str,
    is_valid: bool,
    scanner_results: dict[str, Any],
    violations: list[str],
    on_fail_actions: dict[str, str] | None = None,
    text_length: int = 0,
    fix_applied: bool = False,
    ip_address: str | None = None,
    segments: list | None = None,
    metadata: dict | None = None,
) -> None:
    """Fire-and-forget audit log entry.

    segments: list of dicts or TextSegment objects with role/source/text.
    metadata: extra fields like request_path, model, duration_ms, tool_calls, etc.
    """
    config = get_config()
    if not config.logging.audit:
        return

    timestamp = datetime.now(timezone.utc).isoformat()
    segments_json = _serialize_segments(segments)
    metadata_json = _json_dumps(metadata, ensure_ascii=False) if metadata else None

    if config.logging.audit_file:
        try:
            await _write_sqlite(
                timestamp, direction, is_valid, scanner_results, violations,
                on_fail_actions, text_length, fix_applied, ip_address,
                segments_json, metadata_json,
            )
        except Exception:
            logger.exception("Failed to write SQLite audit log")
    else:
        record = _build_record(
            timestamp, direction, is_valid, scanner_results, violations,
            on_fail_actions, text_length, fix_applied, ip_address,
            segments_json, metadata,
        )
        print(_json_dumps(record), flush=True)


async def close() -> None:
    """Close SQLite connection if open."""
    global _sqlite_conn
    if _sqlite_conn is not None:
        await _sqlite_conn.close()
        _sqlite_conn = None
