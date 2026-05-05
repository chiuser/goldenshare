from __future__ import annotations

from datetime import date
from decimal import Decimal
import os
from typing import Any

import pytest
from sqlalchemy import text

from src.db import SessionLocal
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.writer import DatasetWriter


_RUN_FLAG = "RUN_INDEX_PERIOD_DERIVED_COMPARE"
_TS_CODE = os.getenv("INDEX_PERIOD_COMPARE_TS_CODE", "000001.SH").strip().upper()


def _as_decimal(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.0001"))


def _assert_decimal_equal(left: Any, right: Any, *, field: str) -> None:
    assert _as_decimal(left) == _as_decimal(right), f"{field}: left={left} right={right}"


def _assert_decimal_close(left: Any, right: Any, *, field: str, tolerance: Decimal) -> None:
    left_decimal = _as_decimal(left)
    right_decimal = _as_decimal(right)
    assert abs(left_decimal - right_decimal) <= tolerance, f"{field}: left={left} right={right}"


def _load_api_row(session, *, table_name: str, trade_date: date) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    row = session.execute(
        text(
            f"""
            select
                ts_code,
                period_start_date,
                trade_date,
                open,
                high,
                low,
                close,
                pre_close,
                change_amount,
                pct_chg,
                vol,
                amount,
                source
            from core_serving.{table_name}
            where ts_code = :ts_code
              and trade_date = :trade_date
              and source = 'api'
            """
        ),
        {"ts_code": _TS_CODE, "trade_date": trade_date},
    ).mappings().one_or_none()
    if row is None:
        pytest.skip(f"missing API row: table={table_name} ts_code={_TS_CODE} trade_date={trade_date}")
    return dict(row)


def _assert_derived_matches_api(derived: dict[str, Any], api_row: dict[str, Any]) -> None:
    assert derived["ts_code"] == api_row["ts_code"]
    assert derived["trade_date"] == api_row["trade_date"]
    assert derived["period_start_date"] == api_row["period_start_date"]
    assert derived["source"] == "derived_daily"

    for field in (
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "change_amount",
        "pct_chg",
        "vol",
    ):
        _assert_decimal_equal(derived[field], api_row[field], field=field)
    _assert_decimal_close(derived["amount"], api_row["amount"], field="amount", tolerance=Decimal("1000.0000"))


@pytest.mark.skipif(
    os.getenv(_RUN_FLAG) != "1",
    reason=f"set {_RUN_FLAG}=1 to compare derived index period bars against synced API rows",
)
def test_index_weekly_and_monthly_derived_from_daily_match_synced_api_rows() -> None:
    with SessionLocal() as session:
        writer = DatasetWriter(session)

        weekly_definition = get_dataset_definition("index_weekly")
        weekly_derived = writer._build_index_period_derived_rows_for_single_code(
            definition=weekly_definition,
            trade_date=date(2026, 4, 17),
            ts_code=_TS_CODE,
        )
        assert len(weekly_derived) == 1
        weekly_api = _load_api_row(session, table_name="index_weekly_serving", trade_date=date(2026, 4, 17))
        _assert_derived_matches_api(weekly_derived[0], weekly_api)

        monthly_definition = get_dataset_definition("index_monthly")
        monthly_derived = writer._build_index_period_derived_rows_for_single_code(
            definition=monthly_definition,
            trade_date=date(2026, 3, 31),
            ts_code=_TS_CODE,
        )
        assert len(monthly_derived) == 1
        monthly_api = _load_api_row(session, table_name="index_monthly_serving", trade_date=date(2026, 3, 31))
        _assert_derived_matches_api(monthly_derived[0], monthly_api)
