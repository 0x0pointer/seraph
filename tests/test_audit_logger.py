"""Unit tests for app/services/audit_logger.py — stdout and SQLite audit logging."""
import asyncio
import json
import sqlite3
import pytest

from app.services import audit_logger


def _run(coro):
    """Run an async function synchronously."""
    return asyncio.run(coro)


class TestStdoutAuditLogger:
    @pytest.fixture(autouse=True)
    def _enable_audit(self):
        from app.core.config import get_config
        config = get_config()
        saved_audit = config.logging.audit
        saved_file = config.logging.audit_file
        config.logging.audit = True
        config.logging.audit_file = None
        yield
        config.logging.audit = saved_audit
        config.logging.audit_file = saved_file

    def test_log_scan_prints_json_to_stdout(self, capsys):
        _run(audit_logger.log_scan(
            direction="input",
            is_valid=True,
            scanner_results={"Toxicity": 0.1},
            violations=[],
            text_length=42,
        ))
        captured = capsys.readouterr()
        record = json.loads(captured.out.strip())
        assert record["direction"] == "input"
        assert record["is_valid"] is True
        assert record["scanner_results"]["Toxicity"] == 0.1
        assert record["violations"] == []
        assert record["text_length"] == 42
        assert "timestamp" in record

    def test_log_scan_includes_violations(self, capsys):
        _run(audit_logger.log_scan(
            direction="output",
            is_valid=False,
            scanner_results={"PromptInjection": 0.95},
            violations=["PromptInjection"],
            on_fail_actions={"PromptInjection": "blocked"},
            text_length=100,
            fix_applied=False,
            ip_address="10.0.0.1",
        ))
        captured = capsys.readouterr()
        record = json.loads(captured.out.strip())
        assert record["is_valid"] is False
        assert "PromptInjection" in record["violations"]
        assert record["on_fail_actions"]["PromptInjection"] == "blocked"
        assert record["ip_address"] == "10.0.0.1"

    def test_log_scan_includes_fix_applied(self, capsys):
        _run(audit_logger.log_scan(
            direction="input",
            is_valid=True,
            scanner_results={"Secrets": 0.99},
            violations=[],
            on_fail_actions={"Secrets": "fixed"},
            text_length=50,
            fix_applied=True,
        ))
        captured = capsys.readouterr()
        record = json.loads(captured.out.strip())
        assert record["fix_applied"] is True

    def test_log_scan_omits_ip_when_none(self, capsys):
        _run(audit_logger.log_scan(
            direction="input",
            is_valid=True,
            scanner_results={},
            violations=[],
        ))
        captured = capsys.readouterr()
        record = json.loads(captured.out.strip())
        assert "ip_address" not in record


class TestAuditDisabled:
    @pytest.fixture(autouse=True)
    def _disable_audit(self):
        from app.core.config import get_config
        config = get_config()
        saved = config.logging.audit
        config.logging.audit = False
        yield
        config.logging.audit = saved

    def test_log_scan_does_nothing_when_disabled(self, capsys):
        _run(audit_logger.log_scan(
            direction="input",
            is_valid=True,
            scanner_results={},
            violations=[],
        ))
        captured = capsys.readouterr()
        assert captured.out == ""


class TestSqliteAuditLogger:
    @pytest.fixture(autouse=True)
    def _setup_sqlite(self, tmp_path):
        from app.core.config import get_config
        config = get_config()
        saved_audit = config.logging.audit
        saved_file = config.logging.audit_file
        config.logging.audit = True
        config.logging.audit_file = str(tmp_path / "audit.db")
        audit_logger._sqlite_conn = None
        yield tmp_path / "audit.db"
        # Properly close the connection to kill the worker thread
        _run(audit_logger.close())
        config.logging.audit = saved_audit
        config.logging.audit_file = saved_file

    def test_log_scan_writes_to_sqlite(self, _setup_sqlite):
        db_path = _setup_sqlite
        _run(audit_logger.log_scan(
            direction="input",
            is_valid=True,
            scanner_results={"Toxicity": 0.05},
            violations=[],
            text_length=10,
            ip_address="127.0.0.1",
        ))
        assert db_path.exists()

        # Read back with stdlib sqlite3 (no extra threads)
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT * FROM audit_logs").fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0][2] == "input"       # direction
        assert rows[0][3] == 1             # is_valid (True as int)
        assert rows[0][7] == 10            # text_length
        assert rows[0][9] == "127.0.0.1"   # ip_address

    def test_multiple_writes_to_sqlite(self, _setup_sqlite):
        for i in range(3):
            _run(audit_logger.log_scan(
                direction="input",
                is_valid=i % 2 == 0,
                scanner_results={},
                violations=[],
            ))

        db_path = _setup_sqlite
        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
        conn.close()
        assert count == 3


class TestAuditLoggerClose:
    def test_close_when_no_connection(self):
        audit_logger._sqlite_conn = None
        _run(audit_logger.close())
        assert audit_logger._sqlite_conn is None


class TestSqliteAuditErrors:
    @pytest.fixture(autouse=True)
    def _setup_broken_sqlite(self, tmp_path):
        from app.core.config import get_config
        config = get_config()
        saved_audit = config.logging.audit
        saved_file = config.logging.audit_file
        config.logging.audit = True
        # Point to a directory instead of a file — will cause sqlite error
        config.logging.audit_file = str(tmp_path / "nonexistent_dir" / "audit.db")
        audit_logger._sqlite_conn = None
        yield
        audit_logger._sqlite_conn = None
        config.logging.audit = saved_audit
        config.logging.audit_file = saved_file

    def test_sqlite_write_failure_does_not_raise(self):
        """SQLite errors are caught and logged, not propagated."""
        _run(audit_logger.log_scan(
            direction="input",
            is_valid=True,
            scanner_results={},
            violations=[],
        ))
        # Should not raise — error is caught internally
