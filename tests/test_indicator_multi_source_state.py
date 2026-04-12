from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from src.foundation.services.sync.sync_equity_indicators_service import SyncEquityIndicatorsService


def _mock_price_rows() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            trade_date=date(2026, 4, 7),
            open=Decimal("10.0000"),
            high=Decimal("10.5000"),
            low=Decimal("9.8000"),
            close=Decimal("10.2000"),
        ),
        SimpleNamespace(
            trade_date=date(2026, 4, 8),
            open=Decimal("10.2000"),
            high=Decimal("10.6000"),
            low=Decimal("10.0000"),
            close=Decimal("10.4000"),
        ),
    ]


def _mock_factor_map() -> dict[date, Decimal]:
    return {
        date(2026, 4, 7): Decimal("1.00000000"),
        date(2026, 4, 8): Decimal("1.00000000"),
    }


def _prepare_service(mocker) -> tuple[SyncEquityIndicatorsService, object]:
    service = SyncEquityIndicatorsService(mocker.Mock())
    mocker.patch.object(service, "_load_daily_rows", return_value=_mock_price_rows())
    mocker.patch.object(service, "_load_factor_map", return_value=_mock_factor_map())
    mocker.patch.object(service, "_load_anchor", return_value=Decimal("1.00000000"))
    state_upsert = mocker.patch.object(service.dao.indicator_state, "bulk_upsert", return_value=6)
    mocker.patch.object(service.dao.indicator_macd, "bulk_upsert", return_value=4)
    mocker.patch.object(service.dao.indicator_kdj, "bulk_upsert", return_value=4)
    mocker.patch.object(service.dao.indicator_rsi, "bulk_upsert", return_value=4)
    return service, state_upsert


def test_indicator_state_uses_default_tushare_source_key(mocker) -> None:
    service, state_upsert = _prepare_service(mocker)

    service._build_for_ts_code(
        "000001.SZ",
        start_date=date(2026, 4, 7),
        end_date=date(2026, 4, 8),
    )

    first_state_row = state_upsert.call_args.args[0][0]
    assert first_state_row["source_key"] == "tushare"


def test_indicator_state_keeps_isolated_source_key(mocker) -> None:
    service, state_upsert = _prepare_service(mocker)

    service._build_for_ts_code(
        "000001.SZ",
        start_date=date(2026, 4, 7),
        end_date=date(2026, 4, 8),
        source_key="biying",
    )

    first_state_row = state_upsert.call_args.args[0][0]
    assert first_state_row["source_key"] == "biying"
