from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from orchestrator.analysis.index_wave import InputContractError
from orchestrator.analysis.index_wave_research.source_adapters import (
    INDEX_DAILY_SOURCE_CONTRACT_VERSION,
    MAJOR_INDEX_120M_SOURCE_CONTRACT_VERSION,
    adapt_index_daily_rows,
    adapt_major_index_120m_rows,
)
from orchestrator.analysis.index_wave_research.research_sources import (
    classify_daily_reference_observations,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
AS_OF = datetime(2026, 8, 8, 0, 0, tzinfo=SHANGHAI)


def _daily_row(trade_date: date, *, ts_code: str = "000001.SH") -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "open": 10,
        "high": 12,
        "low": 9,
        "close": 11,
        "vol": 100,
        "amount": 1000,
    }


def _minute_row(
    trade_time: datetime,
    *,
    ts_code: str = "000001.SH",
    freq: str = "120min",
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "freq": freq,
        "trade_time": trade_time,
        "open": 10,
        "high": 12,
        "low": 9,
        "close": 11,
        "vol": 100,
        "amount": 1000,
    }


def test_adapt_index_daily_rows_sets_closed_bar_time_and_lineage() -> None:
    trade_dates = (date(2026, 8, 6), date(2026, 8, 7))

    bars = adapt_index_daily_rows(
        [_daily_row(item) for item in trade_dates],
        ts_code="000001.SH",
        data_snapshot_id="snapshot-1",
        as_of=AS_OF,
        expected_trade_dates=trade_dates,
    )

    assert [bar.bar_end_at for bar in bars] == [
        datetime(2026, 8, 6, 15, 0, tzinfo=SHANGHAI),
        datetime(2026, 8, 7, 15, 0, tzinfo=SHANGHAI),
    ]
    assert bars[0].freq == "1d"
    assert bars[0].source_contract_version == INDEX_DAILY_SOURCE_CONTRACT_VERSION
    assert bars[0].source_partition == "trade_date=2026-08-06"


def test_adapt_index_daily_rows_rejects_identity_coverage_and_future_bar() -> None:
    with pytest.raises(InputContractError, match="SOURCE_TS_CODE_MISMATCH"):
        adapt_index_daily_rows(
            [_daily_row(date(2026, 8, 7), ts_code="399001.SZ")],
            ts_code="000001.SH",
            data_snapshot_id="snapshot-1",
            as_of=AS_OF,
        )

    with pytest.raises(InputContractError, match="SOURCE_TRADE_DATE_COVERAGE_MISMATCH"):
        adapt_index_daily_rows(
            [_daily_row(date(2026, 8, 7))],
            ts_code="000001.SH",
            data_snapshot_id="snapshot-1",
            as_of=AS_OF,
            expected_trade_dates=(date(2026, 8, 6), date(2026, 8, 7)),
        )

    with pytest.raises(InputContractError, match="BAR_AFTER_AS_OF"):
        adapt_index_daily_rows(
            [_daily_row(date(2026, 8, 7))],
            ts_code="000001.SH",
            data_snapshot_id="snapshot-1",
            as_of=datetime(2026, 8, 7, 14, 59, tzinfo=SHANGHAI),
        )

    incomplete = _daily_row(date(2026, 8, 7))
    incomplete["open"] = None
    with pytest.raises(InputContractError, match="SOURCE_PRICE_FIELD_MISSING"):
        adapt_index_daily_rows(
            [incomplete],
            ts_code="000001.SH",
            data_snapshot_id="snapshot-1",
            as_of=AS_OF,
        )


def test_classify_daily_reference_observation_only_excludes_leading_close_only_row() -> (
    None
):
    reference = _daily_row(date(2019, 12, 31), ts_code="000688.SH")
    reference.update({"open": None, "high": None, "low": None, "close": 1000})
    first_bar = _daily_row(date(2020, 1, 2), ts_code="000688.SH")

    rows, exclusions = classify_daily_reference_observations([reference, first_bar])

    assert rows == [first_bar]
    assert len(exclusions) == 1
    assert exclusions[0].trade_date == date(2019, 12, 31)
    assert exclusions[0].reason_code == "LEADING_CLOSE_ONLY_REFERENCE_OBSERVATION"


def test_adapt_major_index_120m_rows_preserves_two_closed_bars_per_date() -> None:
    rows = [
        _minute_row(datetime(2026, 8, 7, 11, 30)),
        _minute_row(datetime(2026, 8, 7, 15, 0)),
    ]

    bars = adapt_major_index_120m_rows(
        rows,
        ts_code="000001.SH",
        data_snapshot_id="snapshot-2",
        as_of=AS_OF,
        expected_trade_dates=(date(2026, 8, 7),),
    )

    assert [bar.bar_end_at for bar in bars] == [
        datetime(2026, 8, 7, 11, 30, tzinfo=SHANGHAI),
        datetime(2026, 8, 7, 15, 0, tzinfo=SHANGHAI),
    ]
    assert bars[0].freq == "120min"
    assert bars[0].source_contract_version == MAJOR_INDEX_120M_SOURCE_CONTRACT_VERSION


@pytest.mark.parametrize(
    ("rows", "reason_code"),
    [
        (
            [_minute_row(datetime(2026, 8, 7, 11, 30), freq="60min")],
            "SOURCE_FREQ_MISMATCH",
        ),
        (
            [_minute_row(datetime(2026, 8, 7, 10, 30))],
            "SOURCE_120M_SESSION_TIME_INVALID",
        ),
        (
            [_minute_row(datetime(2026, 8, 7, 11, 30))],
            "SOURCE_120M_COVERAGE_MISMATCH",
        ),
    ],
)
def test_adapt_major_index_120m_rows_rejects_invalid_source_contract(
    rows: list[dict[str, object]], reason_code: str
) -> None:
    with pytest.raises(InputContractError, match=reason_code):
        adapt_major_index_120m_rows(
            rows,
            ts_code="000001.SH",
            data_snapshot_id="snapshot-2",
            as_of=AS_OF,
            expected_trade_dates=(date(2026, 8, 7),),
        )
