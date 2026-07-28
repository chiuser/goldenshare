from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from orchestrator.defs.asset_guards.stk_mins_prod_readiness import (
    stk_mins_prod_source_ready_for_trade_date,
    validate_stk_mins_prod_completion_reference,
)
from orchestrator.defs.asset_guards.stk_mins_stock_universe import (
    stk_mins_stock_code_set_hash,
)
from orchestrator.defs.prod_db.stk_mins import (
    ProdStkMinsCodeCoverageProbe,
    ProdStkMinsFrequencyCoverage,
    load_prod_stk_mins_code_coverage,
    probe_prod_stk_mins_code_coverage,
)
from orchestrator.defs.prod_db.stk_mins_task_run import (
    PROD_STK_MINS_TASK_RUN_COLUMNS,
    ProdStkMinsTaskRunProbe,
    evaluate_full_market_stk_mins_task_run_rows,
    probe_full_market_stk_mins_task_run,
)
from orchestrator.defs.run_contracts.stk_mins import (
    build_prod_stk_mins_completion_reference,
)


TRADE_DATE = "2026-07-27"
STOCK_CODES = ("000001.SZ", "600000.SH")
FREQUENCIES = (1, 5, 15, 30, 60)


class _FakeCursor:
    def __init__(self, *, rows, columns=()) -> None:
        self._rows = list(rows)
        self.description = tuple(SimpleNamespace(name=column) for column in columns)
        self.sql = ""
        self.params = ()

    def execute(self, sql, params) -> None:
        self.sql = sql
        self.params = tuple(params)

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> bool:
        return False


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self.cursor_instance = cursor

    def cursor(self) -> _FakeCursor:
        return self.cursor_instance


class _FakeProdPostgres:
    def __init__(self, cursor: _FakeCursor) -> None:
        self.connection = _FakeConnection(cursor)

    @contextmanager
    def connect_readonly_transaction(self):
        yield self.connection


def _task_run_row(**overrides):
    row = {
        "id": 818,
        "task_type": "dataset_action",
        "resource_key": "stk_mins",
        "action": "maintain",
        "status": "success",
        "status_reason_code": None,
        "ended_at": "2026-07-27T20:51:33+08:00",
        "unit_total": 5,
        "unit_done": 5,
        "unit_failed": 0,
        "progress_percent": 100.0,
        "rows_fetched": 100,
        "rows_saved": 100,
        "rows_rejected": 0,
        "time_input_json": {"trade_date": TRADE_DATE},
        "filters_json": {"freq": [f"{freq}min" for freq in FREQUENCIES]},
    }
    row.update(overrides)
    return row


def _task_run_probe() -> ProdStkMinsTaskRunProbe:
    return evaluate_full_market_stk_mins_task_run_rows(
        (_task_run_row(),),
        trade_date=TRADE_DATE,
    )


def _coverage_probe(*, ready: bool) -> ProdStkMinsCodeCoverageProbe:
    coverages = tuple(
        ProdStkMinsFrequencyCoverage(
            freq=freq,
            expected_code_count=len(STOCK_CODES),
            present_code_count=len(STOCK_CODES) if ready else len(STOCK_CODES) - 1,
            missing_code_count=0 if ready else 1,
            missing_code_samples=() if ready else ("000001.SZ",),
        )
        for freq in FREQUENCIES
    )
    return ProdStkMinsCodeCoverageProbe(
        ready=ready,
        reason_code=(
            "prod_source_code_coverage_ready"
            if ready
            else "prod_source_code_coverage_incomplete"
        ),
        frequency_coverages=coverages,
        first_missing_freq=None if ready else 1,
        elapsed_ms=1,
    )


def _completion_reference():
    return build_prod_stk_mins_completion_reference(
        task_run_id=818,
        trade_date=TRADE_DATE,
        ended_at="2026-07-27T20:51:33+08:00",
        expected_code_count=len(STOCK_CODES),
        expected_code_hash=stk_mins_stock_code_set_hash(STOCK_CODES),
        frequency_code_counts={freq: len(STOCK_CODES) for freq in FREQUENCIES},
        coverage_observed_at="2026-07-27T20:52:00+08:00",
    )


def test_task_run_requires_closed_full_market_success() -> None:
    ready = evaluate_full_market_stk_mins_task_run_rows(
        (_task_run_row(),),
        trade_date=TRADE_DATE,
    )

    assert ready.ready is True
    assert ready.task_run is not None
    assert ready.task_run.task_run_id == 818

    invalid_rows = (
        _task_run_row(status="running"),
        _task_run_row(filters_json={"freq": ["1min"]}),
        _task_run_row(filters_json={"freq": ["1min", "5min", "15min", "30min", "60min"], "ts_code": ["000001.SZ"]}),
        _task_run_row(rows_rejected=1),
        _task_run_row(unit_done=4),
        _task_run_row(time_input_json={"trade_date": "2026-07-28"}),
        _task_run_row(time_input_json="not-json"),
    )
    for row in invalid_rows:
        result = evaluate_full_market_stk_mins_task_run_rows((row,), trade_date=TRADE_DATE)
        assert result.ready is False
        assert result.task_run is None


def test_task_run_query_uses_explicit_readonly_fields() -> None:
    row = _task_run_row()
    cursor = _FakeCursor(
        rows=[tuple(row[column] for column in PROD_STK_MINS_TASK_RUN_COLUMNS)],
        columns=PROD_STK_MINS_TASK_RUN_COLUMNS,
    )

    result = probe_full_market_stk_mins_task_run(
        prod_postgres=_FakeProdPostgres(cursor),
        trade_date=TRADE_DATE,
    )

    normalized_sql = " ".join(cursor.sql.lower().split())
    assert result.ready is True
    assert "select *" not in normalized_sql
    assert "from ops.task_run" in normalized_sql
    assert "time_input_json ->> 'trade_date'" in normalized_sql
    for column in PROD_STK_MINS_TASK_RUN_COLUMNS:
        assert column in normalized_sql


def test_task_run_probe_fails_closed_on_query_error() -> None:
    class _FailingProd:
        @contextmanager
        def connect_readonly_transaction(self):
            raise RuntimeError("network unavailable")
            yield

    result = probe_full_market_stk_mins_task_run(
        prod_postgres=_FailingProd(),
        trade_date=TRADE_DATE,
    )

    assert result.ready is False
    assert result.reason_code == "prod_ops_task_run_query_error"
    assert result.error_type == "RuntimeError"


def test_coverage_query_uses_primary_key_exists_and_returns_bounded_samples() -> None:
    cursor = _FakeCursor(
        rows=[
            (1, 2, 2, 0, []),
            (5, 2, 1, 1, ["000001.SZ"]),
        ]
    )

    coverage = load_prod_stk_mins_code_coverage(
        prod_postgres=_FakeProdPostgres(cursor),
        trade_date=TRADE_DATE,
        stock_codes=STOCK_CODES,
        freqs=(1, 5),
    )

    normalized_sql = " ".join(cursor.sql.lower().split())
    assert coverage[0].ready is True
    assert coverage[1].missing_code_samples == ("000001.SZ",)
    assert "select *" not in normalized_sql
    assert "exists ( select 1 from raw_tushare.stk_mins" in normalized_sql
    assert "open" not in normalized_sql
    assert "close" not in normalized_sql
    assert "group by ts_code, freq, trade_time" not in normalized_sql
    assert cursor.params[-1] == 3


def test_coverage_probe_fails_closed_on_query_error() -> None:
    class _FailingProd:
        @contextmanager
        def connect_readonly_transaction(self):
            raise RuntimeError("network unavailable")
            yield

    result = probe_prod_stk_mins_code_coverage(
        prod_postgres=_FailingProd(),
        trade_date=TRADE_DATE,
        stock_codes=STOCK_CODES,
    )

    assert result.ready is False
    assert result.reason_code == "prod_source_code_coverage_query_error"
    assert result.error_type == "RuntimeError"


def test_source_readiness_requires_both_task_run_and_coverage() -> None:
    task_run = _task_run_probe()
    with patch(
        "orchestrator.defs.asset_guards.stk_mins_prod_readiness.probe_full_market_stk_mins_task_run",
        return_value=task_run,
    ), patch(
        "orchestrator.defs.asset_guards.stk_mins_prod_readiness.probe_prod_stk_mins_code_coverage",
        return_value=_coverage_probe(ready=True),
    ):
        ready = stk_mins_prod_source_ready_for_trade_date(
            prod_postgres=object(),
            trade_date=TRADE_DATE,
            stock_codes=STOCK_CODES,
            observed_at=datetime.fromisoformat("2026-07-27T20:52:00+08:00"),
        )

    assert ready.ready is True
    assert ready.completion_reference == _completion_reference()

    with patch(
        "orchestrator.defs.asset_guards.stk_mins_prod_readiness.probe_full_market_stk_mins_task_run",
        return_value=task_run,
    ), patch(
        "orchestrator.defs.asset_guards.stk_mins_prod_readiness.probe_prod_stk_mins_code_coverage",
        return_value=_coverage_probe(ready=False),
    ):
        incomplete = stk_mins_prod_source_ready_for_trade_date(
            prod_postgres=object(),
            trade_date=TRADE_DATE,
            stock_codes=STOCK_CODES,
            observed_at=datetime.fromisoformat("2026-07-27T20:52:00+08:00"),
        )

    assert incomplete.ready is False
    assert incomplete.completion_reference is None
    assert incomplete.reason_code == "prod_source_code_coverage_incomplete"


def test_asset_revalidation_rejects_task_run_or_frequency_coverage_change() -> None:
    task_run = _task_run_probe()
    ready_coverage = _coverage_probe(ready=True).frequency_coverages[0]
    with patch(
        "orchestrator.defs.asset_guards.stk_mins_prod_readiness.probe_full_market_stk_mins_task_run_by_id",
        return_value=task_run,
    ), patch(
        "orchestrator.defs.asset_guards.stk_mins_prod_readiness.load_prod_stk_mins_code_coverage",
        return_value=(ready_coverage,),
    ):
        result = validate_stk_mins_prod_completion_reference(
            prod_postgres=object(),
            partition_key=TRADE_DATE,
            freq=1,
            stock_codes=STOCK_CODES,
            completion_reference=_completion_reference(),
        )
    assert result.ready is True

    changed_coverage = ProdStkMinsFrequencyCoverage(
        freq=1,
        expected_code_count=2,
        present_code_count=1,
        missing_code_count=1,
        missing_code_samples=("000001.SZ",),
    )
    with patch(
        "orchestrator.defs.asset_guards.stk_mins_prod_readiness.probe_full_market_stk_mins_task_run_by_id",
        return_value=task_run,
    ), patch(
        "orchestrator.defs.asset_guards.stk_mins_prod_readiness.load_prod_stk_mins_code_coverage",
        return_value=(changed_coverage,),
    ):
        try:
            validate_stk_mins_prod_completion_reference(
                prod_postgres=object(),
                partition_key=TRADE_DATE,
                freq=1,
                stock_codes=STOCK_CODES,
                completion_reference=_completion_reference(),
            )
        except RuntimeError as error:
            assert "source coverage" in str(error)
        else:
            raise AssertionError("changed source coverage must fail before Lake write")
