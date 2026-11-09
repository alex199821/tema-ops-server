# Checks the AI's tools against the real database.
# Needs AI_DATABASE_URL; on the Mac, the tunnel must be open.
from pathlib import Path

from tema_ops.agent.tools import get_wolt_report, run_sql


def test_run_sql_reads():
    assert "(3 rows)" in run_sql.invoke("SELECT id, name FROM branches")


def test_run_sql_cannot_delete():
    assert "read-only transaction" in run_sql.invoke("DELETE FROM wolt.orders")


def test_run_sql_refuses_two_statements():
    assert "multiple commands" in run_sql.invoke("SET statement_timeout = 0; SELECT 1")


def test_get_wolt_report_returns_file():
    msg = get_wolt_report.invoke({"type": "tool_call", "id": "1", "name": "get_wolt_report", "args": {}})
    assert Path(msg.artifact).exists()