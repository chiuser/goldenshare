from __future__ import annotations

from pathlib import Path


RUNBOOK = Path("scripts/sql/etf-basic-downstream-readonly-audit.sql")


def test_etf_basic_downstream_audit_runbook_is_read_only_and_bounded() -> None:
    source = RUNBOOK.read_text(encoding="utf-8")
    normalized = source.upper()

    assert "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY" in normalized
    assert "SET LOCAL STATEMENT_TIMEOUT = '180S'" in normalized
    assert "SET LOCAL LOCK_TIMEOUT = '5S'" in normalized
    assert normalized.rstrip().endswith("ROLLBACK;")
    assert "SELECT *" not in normalized
    for forbidden in ("INSERT ", "UPDATE ", "DELETE ", "TRUNCATE ", "DROP ", "ALTER ", "CREATE "):
        assert forbidden not in normalized


def test_etf_basic_downstream_audit_runbook_has_expected_classifications_and_protections() -> None:
    source = RUNBOOK.read_text(encoding="utf-8")

    for reason_code in (
        "NON_EXCHANGE_ETF_SUFFIX",
        "CODE_NOT_IN_ETF_MASTER",
        "EXCHANGE_MISMATCH",
        "BEFORE_CURRENT_LIST_DATE",
        "PENDING_ETF_HAS_FACT",
        "LISTED_WITHOUT_LIST_DATE_HAS_FACT",
        "MONITOR_CONFIG_NOT_REQUESTABLE",
    ):
        assert reason_code in source

    for protected_table in (
        "raw_tushare.fund_daily",
        "raw_tushare.fund_adj",
        "core.fund_adj_factor",
        "raw_tushare.etf_share_size",
        "ops.etf_realtime_alert",
        "ops.etf_realtime_minute_stat",
    ):
        assert protected_table in source
