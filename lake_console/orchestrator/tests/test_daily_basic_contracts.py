"""Static identity and dependency constraints for the raw-only release."""

import ast
from pathlib import Path

import pytest

from orchestrator.defs.daily_basic_contract import DAILY_BASIC_FIELDS, DAILY_BASIC_TYPES
from orchestrator.defs.run_contracts.configs import (
    build_raw_daily_basic_update_job_run_config,
)


def test_exact_source_fields_and_decimal_units():
    assert DAILY_BASIC_FIELDS == (
        "ts_code",
        "trade_date",
        "close",
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "pe",
        "pe_ttm",
        "pb",
        "ps",
        "ps_ttm",
        "dv_ratio",
        "dv_ttm",
        "total_share",
        "float_share",
        "free_share",
        "total_mv",
        "circ_mv",
    )
    assert DAILY_BASIC_TYPES["close"] == "DECIMAL(18,4)"
    assert DAILY_BASIC_TYPES["turnover_rate"] == "DECIMAL(12,4)"
    assert DAILY_BASIC_TYPES["total_share"] == "DECIMAL(20,4)"
    assert DAILY_BASIC_TYPES["circ_mv"] == "DECIMAL(20,4)"
    assert build_raw_daily_basic_update_job_run_config("2026-09-14", "replace")["ops"][
        "raw_tushare_daily_basic"
    ]["config"] == {"write_mode": "replace"}
    with pytest.raises(ValueError):
        build_raw_daily_basic_update_job_run_config("2026-09-14", "append")


def test_no_history_or_prod_dependency_and_no_report_cursor():
    base = Path(__file__).resolve().parents[1] / "src/orchestrator/defs"
    for relative in (
        "assets/daily_basic.py",
        "checks/daily_basic_checks.py",
        "asset_guards/daily_basic_readiness.py",
        "sensors/daily_basic_sensor.py",
        "sensors/daily_basic_trade_day_sensor.py",
        "daily_basic_raw_io.py",
        "source_readiness/daily_basic.py",
    ):
        source = (base / relative).read_text()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom):
                assert "bootstrap" not in (node.module or "")
                assert "prod_db" not in (node.module or "")
            if relative.startswith("sensors/") and isinstance(node, ast.Attribute):
                assert node.attr != "to_cursor_details"
        assert "PROD_POSTGRES" not in source
    assert (base / "checks/daily_basic_checks.py").read_text().count(
        "@dg.asset_check("
    ) == 2
