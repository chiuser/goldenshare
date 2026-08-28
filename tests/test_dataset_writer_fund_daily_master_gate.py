from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from src.foundation.dao.etf_basic_dao import (
    EtfRequestabilitySnapshot,
    EtfRequestTarget,
)
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.errors import IngestionWriteError
from src.foundation.ingestion.normalizer import NormalizedBatch
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.core.fund_daily_bar import FundDailyBar
from src.foundation.models.raw.raw_fund_daily import RawFundDaily


ELIGIBILITY_AS_OF = date(2026, 8, 28)


class _StubDao:
    def __init__(self, *, model=None, failure: Exception | None = None) -> None:  # type: ignore[no-untyped-def]
        self.model = model
        self.failure = failure
        self.bulk_upsert_calls: list[list[dict]] = []

    def bulk_upsert(self, rows: list[dict], conflict_columns=None):  # type: ignore[no-untyped-def]
        if self.failure is not None:
            raise self.failure
        self.bulk_upsert_calls.append(rows)
        return len({(row["ts_code"], row["trade_date"]) for row in rows})


class _NoCommitSession:
    def commit(self) -> None:
        raise AssertionError("writer phase 不得自行 commit")


def _fund_daily_row(ts_code: str, trade_date: date) -> dict:
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


def _batch(rows: list[dict]) -> NormalizedBatch:
    return NormalizedBatch(
        unit_id="u-fund-daily",
        rows_normalized=rows,
        rows_rejected=0,
        rejected_reasons={},
    )


def _snapshot(*targets: EtfRequestTarget) -> EtfRequestabilitySnapshot:
    return EtfRequestabilitySnapshot(
        as_of_date=ELIGIBILITY_AS_OF,
        exchange=None,
        targets=targets,
        serving_row_count=len(targets),
        requestable_count=len(targets),
        excluded_reason_counts={},
    )


def _writer(mocker, *, snapshot, raw_failure=None, serving_failure=None):  # type: ignore[no-untyped-def]
    raw_dao = _StubDao(model=RawFundDaily, failure=raw_failure)
    serving_dao = _StubDao(model=FundDailyBar, failure=serving_failure)
    etf_basic = SimpleNamespace(
        load_requestability_snapshot=mocker.Mock(
            side_effect=snapshot if isinstance(snapshot, Exception) else None,
            return_value=None if isinstance(snapshot, Exception) else snapshot,
        )
    )
    dao = SimpleNamespace(
        raw_fund_daily=raw_dao,
        fund_daily_bar=serving_dao,
        etf_basic=etf_basic,
    )
    mocker.patch("src.foundation.ingestion.writer.DAOFactory", return_value=dao)
    return DatasetWriter(_NoCommitSession()), dao


def test_fund_daily_raw_phase_keeps_full_source_market(mocker) -> None:
    writer, dao = _writer(mocker, snapshot=_snapshot())
    rows = [
        _fund_daily_row("510300.SH", date(2026, 8, 28)),
        _fund_daily_row("160706.SZ", date(2026, 8, 28)),
        _fund_daily_row("508000.SH", date(2026, 8, 28)),
    ]

    result = writer.write_raw_phase(
        definition=get_dataset_definition("fund_daily"),
        batch=_batch(rows),
    )

    assert [[row["ts_code"] for row in call] for call in dao.raw_fund_daily.bulk_upsert_calls] == [
        ["510300.SH", "160706.SZ", "508000.SH"]
    ]
    assert result.rows_upserted == 3
    assert dao.fund_daily_bar.bulk_upsert_calls == []
    dao.etf_basic.load_requestability_snapshot.assert_not_called()


def test_fund_daily_serving_phase_uses_basic_and_list_date_without_rejecting_raw_rows(mocker) -> None:
    writer, dao = _writer(
        mocker,
        snapshot=_snapshot(
            EtfRequestTarget("510300.SH", date(2012, 5, 28), "SH"),
            EtfRequestTarget("159999.SZ", date(2026, 8, 20), "SZ"),
        ),
    )
    rows = [
        _fund_daily_row("510300.SH", date(2026, 8, 28)),
        _fund_daily_row("160706.SZ", date(2026, 8, 28)),
        _fund_daily_row("508000.SH", date(2026, 8, 28)),
        _fund_daily_row("159999.SZ", date(2026, 8, 19)),
    ]

    result = writer.write_serving_phase(
        definition=get_dataset_definition("fund_daily"),
        batch=_batch(rows),
        eligibility_as_of=ELIGIBILITY_AS_OF,
    )

    assert [[row["ts_code"] for row in call] for call in dao.fund_daily_bar.bulk_upsert_calls] == [
        ["510300.SH"]
    ]
    assert result.rows_written == 1
    assert result.rows_rejected == 0
    assert result.persistence_diagnostics == {
        "serving": {"eligible_rows": 1, "rows_upserted": 1, "committed": False},
        "eligibility_as_of": "2026-08-28",
        "excluded_reason_counts": {
            "CODE_NOT_REQUESTABLE_AT_PUBLISH": 2,
            "BEFORE_CURRENT_LIST_DATE": 1,
        },
    }
    dao.etf_basic.load_requestability_snapshot.assert_called_once_with(
        as_of_date=ELIGIBILITY_AS_OF
    )
    assert dao.raw_fund_daily.bulk_upsert_calls == []


def test_fund_daily_serving_phase_rejects_empty_basic_snapshot(mocker) -> None:
    writer, _dao = _writer(mocker, snapshot=_snapshot())

    with pytest.raises(IngestionWriteError) as exc_info:
        writer.write_serving_phase(
            definition=get_dataset_definition("fund_daily"),
            batch=_batch([_fund_daily_row("510300.SH", date(2026, 8, 28))]),
            eligibility_as_of=ELIGIBILITY_AS_OF,
        )

    error = exc_info.value.structured_error
    assert error.error_code == "fund_daily_serving_publish_failed"
    assert error.details["failure_phase"] == "selector_empty"


def test_fund_daily_serving_phase_classifies_selector_and_upsert_failures(mocker) -> None:
    selector_writer, _dao = _writer(
        mocker,
        snapshot=RuntimeError("selector unavailable"),
    )
    with pytest.raises(IngestionWriteError) as selector_exc:
        selector_writer.write_serving_phase(
            definition=get_dataset_definition("fund_daily"),
            batch=_batch([_fund_daily_row("510300.SH", date(2026, 8, 28))]),
            eligibility_as_of=ELIGIBILITY_AS_OF,
        )
    assert selector_exc.value.structured_error.details["failure_phase"] == "selector"

    upsert_writer, _dao = _writer(
        mocker,
        snapshot=_snapshot(
            EtfRequestTarget("510300.SH", date(2012, 5, 28), "SH"),
        ),
        serving_failure=RuntimeError("serving unavailable"),
    )
    with pytest.raises(IngestionWriteError) as upsert_exc:
        upsert_writer.write_serving_phase(
            definition=get_dataset_definition("fund_daily"),
            batch=_batch([_fund_daily_row("510300.SH", date(2026, 8, 28))]),
            eligibility_as_of=ELIGIBILITY_AS_OF,
        )
    assert upsert_exc.value.structured_error.details["failure_phase"] == "serving_upsert"


def test_fund_daily_generic_writer_cannot_bypass_two_phase_executor(mocker) -> None:
    writer, _dao = _writer(mocker, snapshot=_snapshot())

    with pytest.raises(IngestionWriteError, match="必须由 executor 分阶段执行"):
        writer.write(
            definition=get_dataset_definition("fund_daily"),
            batch=_batch([_fund_daily_row("510300.SH", date(2026, 8, 28))]),
        )
