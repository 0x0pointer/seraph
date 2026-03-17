"""Unit tests for app/services/audit_logger.py — stdout and SQLite audit logging."""
import json
import os
import pytest
from unittest.mock import patch

from app.services import audit_logger


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

    async def test_log_scan_prints_json_to_stdout(self, capsys):
        await audit_logger.log_scan(
            direction="input",
            is_valid=True,
            scanner_results={"Toxicity": 0.1},
            violations=[],
            text_length=42,
        )
        captured = capsys.readouterr()
        record = json.loads(captured.out.strip())
        assert record["direction"] == "input"
        assert record["is_valid"] is True
        assert record["scanner_results"]["Toxicity"] == 0.1
        assert record["violations"] == []
        assert record["text_length"] == 42
        assert "timestamp" in record

    async def test_log_scan_includes_violations(self, capsys):
        await audit_logger.log_scan(
            direction="output",
            is_valid=False,
            scanner_results={"PromptInjection": 0.95},
            violations=["PromptInjection"],
            on_fail_actions={"PromptInjection": "blocked"},
            text_length=100,
            fix_applied=False,
            ip_address="10.0.0.1",
        )
        captured = capsys.readouterr()
        record = json.loads(captured.out.strip())
        assert record["is_valid"] is False
        assert "PromptInjection" in record["violations"]
        assert record["on_fail_actions"]["PromptInjection"] == "blocked"
        assert record["ip_address"] == "10.0.0.1"

    async def test_log_scan_includes_fix_applied(self, capsys):
        await audit_logger.log_scan(
            direction="input",
            is_valid=True,
            scanner_results={"Secrets": 0.99},
            violations=[],
            on_fail_actions={"Secrets": "fixed"},
            text_length=50,
            fix_applied=True,
        )
        captured = capsys.readouterr()
        record = json.loads(captured.out.strip())
        assert record["fix_applied"] is True

    async def test_log_scan_omits_ip_when_none(self, capsys):
        await audit_logger.log_scan(
            direction="input",
            is_valid=True,
            scanner_results={},
            violations=[],
        )
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

    async def test_log_scan_does_nothing_when_disabled(self, capsys):
        await audit_logger.log_scan(
            direction="input",
            is_valid=True,
            scanner_results={},
            violations=[],
        )
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
        # Reset the module-level connection
        audit_logger._sqlite_conn = None
        yield tmp_path / "audit.db"
        config.logging.audit = saved_audit
        config.logging.audit_file = saved_file
        audit_logger._sqlite_conn = None

    async def test_log_scan_writes_to_sqlite(self, _setup_sqlite):
        db_path = _setup_sqlite
        await audit_logger.log_scan(
            direction="input",
            is_valid=True,
            scanner_results={"Toxicity": 0.05},
            violations=[],
            text_length=10,
            ip_address="127.0.0.1",
        )
        # Verify the file was created
        assert db_path.exists()

        # Read it back
        import aiosqlite
        async with aiosqlite.connect(str(db_path)) as conn:
            cursor = await conn.execute("SELECT * FROM audit_logs")
            rows = await cursor.fetchall()
            assert len(rows) == 1
            # Column order: id, timestamp, direction, is_valid, scanner_results, violations, on_fail_actions, text_length, fix_applied, ip_address
            assert rows[0][2] == "input"  # direction
            assert rows[0][3] == 1  # is_valid (True as int)
            assert rows[0][7] == 10  # text_length
            assert rows[0][9] == "127.0.0.1"  # ip_address

    async def test_multiple_writes_to_sqlite(self, _setup_sqlite):
        db_path = _setup_sqlite
        for i in range(3):
            await audit_logger.log_scan(
                direction="input",
                is_valid=i % 2 == 0,
                scanner_results={},
                violations=[],
            )

        import aiosqlite
        async with aiosqlite.connect(str(db_path)) as conn:
            cursor = await conn.execute("SELECT COUNT(*) FROM audit_logs")
            count = (await cursor.fetchone())[0]
            assert count == 3


class TestAuditLoggerClose:
    async def test_close_when_no_connection(self):
        audit_logger._sqlite_conn = None
        await audit_logger.close()  # should not raise
        assert audit_logger._sqlite_conn is None
