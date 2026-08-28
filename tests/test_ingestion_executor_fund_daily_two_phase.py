from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from src.foundation.dao.etf_basic_dao import (
    EtfRequestabilitySnapshot,
    EtfRequestTarget,
)
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.errors import IngestionError
from src.foundation.ingestion.execution_plan import (
    PlanUnitSnapshot,
    ValidatedDatasetActionRequest,
)
from src.foundation.ingestion.executor import IngestionExecutor
from src.foundation.ingestion.normalizer import NormalizedBatch
from src.foundation.ingestion.source_client import SourceFetchResult
from src.foundation.models.core.fund_daily_bar import FundDailyBar
from src.foundation.models.raw.raw_fund_daily import RawFundDaily


ELIGIBILITY_AS_OF = date(2026, 8, 28)
TRADE_DATE = date(2026, 8, 19)


class _TransactionalSession:
    def __init__(self, *, fail_commit_attempts: set[int] | None = None) -> None:
        self.fail_commit_attempts = set(fail_commit_attempts or ())
        self.commit_attempts = 0
        self.rollback_count = 0
        self.pending: dict[str, dict[tuple[object, object], dict]] = {}
        self.durable: dict[str, dict[tuple[object, object], dict]] = {}

    def stage(self, table: str, rows: list[dict]) -> int:
        bucket = self.pending.setdefault(table, {})
        for row in rows:
            bucket[(row["ts_code"], row["trade_date"])] = dict(row)
        return len({(row["ts_code"], row["trade_date"]) for row in rows})

    def commit(self) -> None:
        self.commit_attempts += 1
        if self.commit_attempts in self.fail_commit_attempts:
            raise RuntimeError(f"commit {self.commit_attempts} failed")
        for table, rows in self.pending.items():
            self.durable.setdefault(table, {}).update(rows)
        self.pending.clear()

    def rollback(self) -> None:
        self.rollback_count += 1
        self.pending.clear()


class _TransactionalDao:
    def __init__(
        self,
        session: _TransactionalSession,
        *,
        table: str,
        model,
        failure: Exception | None = None,
    ) -> None:  # type: ignore[no-untyped-def]
        self.session = session
        self.table = table
        self.model = model
        self.failure = failure
        self.bulk_upsert_calls = 0

    def bulk_upsert(self, rows: list[dict], conflict_columns=None):  # type: ignore[no-untyped-def]
        self.bulk_upsert_calls += 1
        if self.failure is not None:
            raise self.failure
        return self.session.stage(self.table, rows)


class _StubNormalizer:
    def __init__(self) -> None:
        self.normalize_count = 0

    def normalize(self, *, fetch_result, **_kwargs):  # type: ignore[no-untyped-def]
        self.normalize_count += 1
        return NormalizedBatch(
            unit_id=fetch_result.unit_id,
            rows_normalized=[dict(row) for row in fetch_result.rows_raw],
            rows_rejected=0,
            rejected_reasons={},
        )

    @staticmethod
    def raise_if_all_rejected(_batch) -> None:  # type: ignore[no-untyped-def]
        return None


def _row(ts_code: str, trade_date: date = TRADE_DATE) -> dict:
    return {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "open": 1,
        "high": 2,
        "low": 1,
        "close": 2,
        "pre_close": 1,
        "change": 1,
        "change_amount": 1,
        "pct_chg": 1,
        "vol": 10,
        "amount": 100,
    }


def _rows() -> list[dict]:
    return [
        _row("510300.SH"),
        _row("160706.SZ"),
        _row("508000.SH"),
        _row("159999.SZ"),
    ]


def _snapshot(*targets: EtfRequestTarget) -> EtfRequestabilitySnapshot:
    return EtfRequestabilitySnapshot(
        as_of_date=ELIGIBILITY_AS_OF,
        exchange=None,
        targets=targets,
        serving_row_count=len(targets),
        requestable_count=len(targets),
        excluded_reason_counts={},
    )


def _default_snapshot() -> EtfRequestabilitySnapshot:
    return _snapshot(
        EtfRequestTarget("510300.SH", date(2012, 5, 28), "SH"),
        EtfRequestTarget("159999.SZ", date(2026, 8, 20), "SZ"),
    )


def _request() -> ValidatedDatasetActionRequest:
    return ValidatedDatasetActionRequest(
        request_id="fund-daily-two-phase",
        dataset_key="fund_daily",
        action="maintain",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=TRADE_DATE,
    )


def _unit(unit_id: str = "fund-daily-unit") -> PlanUnitSnapshot:
    return PlanUnitSnapshot(
        unit_id=unit_id,
        dataset_key="fund_daily",
        source_key="tushare",
        trade_date=TRADE_DATE,
        request_params={"trade_date": "20260819"},
        progress_context={},
        pagination_policy="offset_limit",
        page_limit=5000,
    )


def _build_executor(
    mocker,
    *,
    snapshot=None,  # type: ignore[no-untyped-def]
    raw_failure: Exception | None = None,
    serving_failure: Exception | None = None,
    fail_commit_attempts: set[int] | None = None,
):  # type: ignore[no-untyped-def]
    session = _TransactionalSession(fail_commit_attempts=fail_commit_attempts)
    raw_dao = _TransactionalDao(
        session,
        table="raw",
        model=RawFundDaily,
        failure=raw_failure,
    )
    serving_dao = _TransactionalDao(
        session,
        table="serving",
        model=FundDailyBar,
        failure=serving_failure,
    )
    resolved_snapshot = _default_snapshot() if snapshot is None else snapshot
    etf_basic = SimpleNamespace(
        load_requestability_snapshot=mocker.Mock(
            side_effect=resolved_snapshot if isinstance(resolved_snapshot, Exception) else None,
            return_value=None if isinstance(resolved_snapshot, Exception) else resolved_snapshot,
        )
    )
    dao = SimpleNamespace(
        raw_fund_daily=raw_dao,
        fund_daily_bar=serving_dao,
        etf_basic=etf_basic,
    )
    mocker.patch("src.foundation.ingestion.writer.DAOFactory", return_value=dao)
    executor = IngestionExecutor(session)
    executor.source_client = SimpleNamespace(
        fetch=lambda **kwargs: SourceFetchResult(
            unit_id=kwargs["unit"].unit_id,
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=_rows(),
        )
    )
    executor.normalizer = _StubNormalizer()  # type: ignore[assignment]
    current_date = mocker.patch.object(
        executor,
        "_current_china_date",
        return_value=ELIGIBILITY_AS_OF,
    )
    return executor, session, dao, current_date


def test_fund_daily_two_phase_commits_full_raw_then_filtered_serving(mocker) -> None:
    executor, session, dao, current_date = _build_executor(mocker)

    summary = executor.run(
        request=_request(),
        definition=get_dataset_definition("fund_daily"),
        units=(_unit(),),
    )

    assert session.commit_attempts == 2
    assert set(key[0] for key in session.durable["raw"]) == {
        "510300.SH",
        "160706.SZ",
        "508000.SH",
        "159999.SZ",
    }
    assert set(key[0] for key in session.durable["serving"]) == {"510300.SH"}
    assert summary.rows_written == 1
    assert summary.rows_committed == 1
    assert summary.unit_done == 1
    assert summary.unit_failed == 0
    assert summary.ingestion_diagnostics["persistence"] == {
        "immutable_fact": {
            "rows_normalized_before_dedupe": 4,
            "rows_inserted_new": 0,
            "rows_matched_existing": 0,
            "scope_existing_count": 0,
            "scope_source_unique_count": 0,
            "final_scope_count": 0,
        },
        "raw": {"rows_upserted": 4, "committed": True},
        "serving": {"eligible_rows": 1, "rows_upserted": 1, "committed": True},
        "eligibility_as_of": "2026-08-28",
        "excluded_reason_counts": {
            "CODE_NOT_REQUESTABLE_AT_PUBLISH": 2,
            "BEFORE_CURRENT_LIST_DATE": 1,
        },
    }
    dao.etf_basic.load_requestability_snapshot.assert_called_once_with(
        as_of_date=ELIGIBILITY_AS_OF
    )
    current_date.assert_called_once_with()
    assert executor.normalizer.normalize_count == 1


@pytest.mark.parametrize(
    ("snapshot", "serving_failure", "fail_commit_attempts", "expected_phase"),
    (
        (_snapshot(), None, None, "selector_empty"),
        (RuntimeError("selector failed"), None, None, "selector"),
        (None, RuntimeError("serving upsert failed"), None, "serving_upsert"),
        (None, None, {2}, "serving_commit"),
    ),
)
def test_fund_daily_serving_failure_keeps_raw_and_fails_unit(
    mocker,
    snapshot,
    serving_failure,
    fail_commit_attempts,
    expected_phase: str,
) -> None:  # type: ignore[no-untyped-def]
    executor, session, _dao, _current_date = _build_executor(
        mocker,
        snapshot=snapshot,
        serving_failure=serving_failure,
        fail_commit_attempts=fail_commit_attempts,
    )
    captured = []

    with pytest.raises(IngestionError) as exc_info:
        executor.run(
            request=_request(),
            definition=get_dataset_definition("fund_daily"),
            units=(_unit(),),
            progress_reporter=lambda snapshot, message: captured.append((snapshot, message)),
        )

    error = exc_info.value.structured_error
    assert error.error_code == "fund_daily_serving_publish_failed"
    assert error.details["failure_phase"] == expected_phase
    assert error.details["raw_committed"] is True
    assert error.details["raw_rows_committed"] == 4
    assert len(session.durable["raw"]) == 4
    assert session.durable.get("serving", {}) == {}
    assert session.rollback_count == 1
    assert captured[-1][0].unit_done == 0
    assert captured[-1][0].unit_failed == 1
    assert captured[-1][0].rows_written == 0
    persistence = captured[-1][0].ingestion_diagnostics["persistence"]
    assert persistence["raw"] == {"rows_upserted": 4, "committed": True}
    assert persistence["serving"]["committed"] is False


@pytest.mark.parametrize(
    ("raw_failure", "fail_commit_attempts", "expected_code"),
    (
        (RuntimeError("raw upsert failed"), None, "write_failed"),
        (None, {1}, "internal_error"),
    ),
)
def test_fund_daily_raw_failure_rolls_back_and_never_starts_serving(
    mocker,
    raw_failure,
    fail_commit_attempts,
    expected_code: str,
) -> None:  # type: ignore[no-untyped-def]
    executor, session, dao, _current_date = _build_executor(
        mocker,
        raw_failure=raw_failure,
        fail_commit_attempts=fail_commit_attempts,
    )

    with pytest.raises(IngestionError) as exc_info:
        executor.run(
            request=_request(),
            definition=get_dataset_definition("fund_daily"),
            units=(_unit(),),
        )

    assert exc_info.value.structured_error.error_code == expected_code
    assert session.durable.get("raw", {}) == {}
    assert session.durable.get("serving", {}) == {}
    assert dao.fund_daily_bar.bulk_upsert_calls == 0
    dao.etf_basic.load_requestability_snapshot.assert_not_called()


def test_fund_daily_retry_replays_raw_idempotently_then_publishes_serving(mocker) -> None:
    executor, session, dao, _current_date = _build_executor(
        mocker,
        serving_failure=RuntimeError("temporary serving failure"),
    )

    with pytest.raises(IngestionError):
        executor.run(
            request=_request(),
            definition=get_dataset_definition("fund_daily"),
            units=(_unit(),),
        )
    assert len(session.durable["raw"]) == 4
    dao.fund_daily_bar.failure = None

    summary = executor.run(
        request=_request(),
        definition=get_dataset_definition("fund_daily"),
        units=(_unit(),),
    )

    assert len(session.durable["raw"]) == 4
    assert set(key[0] for key in session.durable["serving"]) == {"510300.SH"}
    assert summary.unit_done == 1
    assert summary.rows_committed == 1


def test_fund_daily_task_fixes_china_date_once_across_units(mocker) -> None:
    executor, session, dao, current_date = _build_executor(mocker)

    summary = executor.run(
        request=_request(),
        definition=get_dataset_definition("fund_daily"),
        units=(_unit("fund-daily-unit-1"), _unit("fund-daily-unit-2")),
    )

    current_date.assert_called_once_with()
    assert dao.etf_basic.load_requestability_snapshot.call_count == 2
    assert all(
        call.kwargs == {"as_of_date": ELIGIBILITY_AS_OF}
        for call in dao.etf_basic.load_requestability_snapshot.call_args_list
    )
    assert session.commit_attempts == 4
    assert summary.unit_done == 2
    persistence = summary.ingestion_diagnostics["persistence"]
    assert persistence["raw"] == {"rows_upserted": 8, "committed": True}
    assert persistence["serving"] == {
        "eligible_rows": 2,
        "rows_upserted": 2,
        "committed": True,
    }
    assert persistence["excluded_reason_counts"] == {
        "CODE_NOT_REQUESTABLE_AT_PUBLISH": 4,
        "BEFORE_CURRENT_LIST_DATE": 2,
    }
