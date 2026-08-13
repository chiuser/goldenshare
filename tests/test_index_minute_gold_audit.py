from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

duckdb = pytest.importorskip("duckdb")

from src.scripts.audit_index_minute_gold import (  # noqa: E402
    FAILED,
    READY,
    SOURCE_NOT_READY,
    SOURCE_NOT_READY_CODE,
    _maximum_response_acceptance,
    run_gold_acceptance,
)
from src.foundation.clients.local_lake.major_index_mins_reader import (  # noqa: E402
    IndexMinuteRequestError,
)


def _write_fixture(root: Path, *, dataset: str) -> None:
    if dataset == "bars":
        target = root / (
            "gold/quote/major_index_mins/freq=5/trade_date=2026-08-11/part-000.parquet"
        )
        create_sql = """
            CREATE TABLE fixture (
              ts_code VARCHAR, freq INTEGER, trade_date DATE, trade_time TIMESTAMP,
              open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
              vol DOUBLE, amount DOUBLE, exchange VARCHAR, vwap DOUBLE
            )
        """
        insert_sql = """
            INSERT INTO fixture VALUES (
              '000001.SH', 5, DATE '2026-08-11',
              TIMESTAMP '2026-08-11 09:35:00',
              1, 1.2, .9, 1.1, 10, 100, 'SSE', 1.05
            )
        """
    else:
        target = root / (
            "gold/indicator/major_index_mins_technical/freq=5/"
            "trade_date=2026-08-11/part-000.parquet"
        )
        create_sql = """
            CREATE TABLE fixture (
              ts_code VARCHAR, freq SMALLINT, trade_date DATE, trade_time TIMESTAMP,
              ma_5 DOUBLE, ma_10 DOUBLE, ma_20 DOUBLE, ma_30 DOUBLE,
              ma_60 DOUBLE, ma_90 DOUBLE, ma_250 DOUBLE,
              boll_mid DOUBLE, boll_upper DOUBLE, boll_lower DOUBLE,
              macd_dif DOUBLE, macd_dea DOUBLE, macd DOUBLE,
              kdj_k DOUBLE, kdj_d DOUBLE, kdj_j DOUBLE,
              observation_count INTEGER, params_key VARCHAR, indicator_version INTEGER
            )
        """
        insert_sql = """
            INSERT INTO fixture VALUES (
              '000001.SH', 5, DATE '2026-08-11', TIMESTAMP '2026-08-11 09:35:00',
              NULL, NULL, NULL, NULL, NULL, NULL, NULL,
              NULL, NULL, NULL, 0, 0, 0, 50, 50, 50, 1,
              'ma_5_10_20_30_60_90_250__boll_20_2__macd_12_26_9__kdj_9_3_3', 1
            )
        """
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(create_sql)
        connection.execute(insert_sql)
        connection.execute("COPY fixture TO ? (FORMAT PARQUET)", [str(target)])
    finally:
        connection.close()


def test_gold_acceptance_reports_source_not_ready_without_gold_files(
    tmp_path: Path,
) -> None:
    _write_fixture(tmp_path, dataset="bars")

    result = run_gold_acceptance(
        lake_root=tmp_path,
        ts_codes=("000001.SH",),
        frequencies=(5,),
        runs=1,
    )

    assert result["status"] == SOURCE_NOT_READY
    assert result["code"] == SOURCE_NOT_READY_CODE
    assert result["readOnly"] is True
    assert result["performance"] is None


def test_gold_acceptance_checks_alignment_and_query_service_performance(
    tmp_path: Path,
) -> None:
    _write_fixture(tmp_path, dataset="bars")
    _write_fixture(tmp_path, dataset="gold")

    result = run_gold_acceptance(
        lake_root=tmp_path,
        ts_codes=("000001.SH",),
        frequencies=(5,),
        runs=1,
        full_alignment=True,
        include_max=True,
    )

    assert result["status"] == READY
    assert result["code"] is None
    assert result["frequencies"][0]["checkedPartitionCount"] == 1
    assert result["frequencies"][0]["alignmentFailures"] == []
    assert result["performance"]["status"] == READY
    assert result["performance"]["frequencies"][0]["sampleCount"] == 1
    assert result["maximumResponse"]["status"] == READY
    assert result["maximumResponse"]["maximumRequest"]["outcome"] == "RETURNED"
    assert result["maximumResponse"]["safePage"]["status"] == READY


def test_maximum_response_acceptance_treats_5mb_rejection_as_expected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeIndicatorService(
        reject_maximum_with="响应超过 5MB，请降低 limit 或使用 cursor 分页。"
    )
    monkeypatch.setattr(
        "src.scripts.audit_index_minute_gold.IndexDetailMinutesQueryService",
        lambda _lake_root: service,
    )

    result = _maximum_response_acceptance(
        lake_root=tmp_path,
        ts_code="000001.SH",
        freq=1,
    )

    assert result["status"] == READY
    assert result["maximumRequest"]["outcome"] == "REJECTED_AS_EXPECTED"
    assert result["maximumRequest"]["responseTooLargeRejected"] is True
    assert result["safePage"]["limit"] == 5_000
    assert result["safePage"]["cursorOrderValid"] is True
    assert service.limits == [10_000, 5_000, 1]


def test_maximum_response_acceptance_rejects_unrelated_request_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _FakeIndicatorService(reject_maximum_with="cursor 不合法。")
    monkeypatch.setattr(
        "src.scripts.audit_index_minute_gold.IndexDetailMinutesQueryService",
        lambda _lake_root: service,
    )

    result = _maximum_response_acceptance(
        lake_root=tmp_path,
        ts_code="000001.SH",
        freq=1,
    )

    assert result["status"] == FAILED
    assert result["maximumRequest"]["outcome"] == "FAILED"
    assert result["safePage"]["status"] == READY


class _FakeIndicatorPage:
    def __init__(
        self,
        *,
        items: list[SimpleNamespace],
        has_more: bool,
        next_cursor: str | None,
    ) -> None:
        self.items = items
        self.meta = SimpleNamespace(hasMore=has_more, nextCursor=next_cursor)
        self.dataStatus = SimpleNamespace(status=READY)

    def model_dump_json(self) -> str:
        return "{}"


class _FakeIndicatorService:
    def __init__(self, *, reject_maximum_with: str) -> None:
        self._reject_maximum_with = reject_maximum_with
        self.limits: list[int] = []

    def read_indicators(self, **kwargs: object) -> _FakeIndicatorPage:
        limit = int(kwargs["limit"])
        self.limits.append(limit)
        if limit == 10_000:
            raise IndexMinuteRequestError(self._reject_maximum_with)
        if limit == 5_000:
            return _FakeIndicatorPage(
                items=[
                    SimpleNamespace(tradeTime=datetime(2026, 8, 11, 9, 35)),
                    SimpleNamespace(tradeTime=datetime(2026, 8, 11, 9, 40)),
                ],
                has_more=True,
                next_cursor="next-page",
            )
        return _FakeIndicatorPage(
            items=[SimpleNamespace(tradeTime=datetime(2026, 8, 11, 9, 30))],
            has_more=False,
            next_cursor=None,
        )
