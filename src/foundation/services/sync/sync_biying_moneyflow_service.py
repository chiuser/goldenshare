from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from typing import Any

from sqlalchemy import select

from src.foundation.connectors.factory import create_source_connector
from src.foundation.config.settings import get_settings
from src.foundation.models.raw_multi.raw_biying_stock_basic import RawBiyingStockBasic
from src.foundation.services.sync.base_sync_service import BaseSyncService
from src.foundation.services.sync.sync_moneyflow_service import publish_moneyflow_serving_for_keys
from src.foundation.services.transform.normalize_moneyflow_service import NormalizeMoneyflowService


WINDOW_DAYS = 100

INT_FIELDS: tuple[str, ...] = (
    "zmbzds",
    "zmszds",
    "zmbzdszl",
    "zmszdszl",
    "cjbszl",
    "zmbtdcjl",
    "zmbddcjl",
    "zmbzdcjl",
    "zmbxdcjl",
    "zmstdcjl",
    "zmsddcjl",
    "zmszdcjl",
    "zmsxdcjl",
    "bdmbtdcjl",
    "bdmbddcjl",
    "bdmbzdcjl",
    "bdmbxdcjl",
    "bdmstdcjl",
    "bdmsddcjl",
    "bdmszdcjl",
    "bdmsxdcjl",
    "zmbtdcjzlv",
    "zmbddcjzlv",
    "zmbzdcjzlv",
    "zmbxdcjzlv",
    "zmstdcjzlv",
    "zmsddcjzlv",
    "zmszdcjzlv",
    "zmsxdcjzlv",
    "bdmbtdcjzlv",
    "bdmbddcjzlv",
    "bdmbzdcjzlv",
    "bdmbxdcjzlv",
    "bdmstdcjzlv",
    "bdmsddcjzlv",
    "bdmszdcjzlv",
    "bdmsxdcjzlv",
)

DECIMAL_FIELDS: tuple[str, ...] = (
    "dddx",
    "zddy",
    "ddcf",
    "zmbtdcje",
    "zmbddcje",
    "zmbzdcje",
    "zmbxdcje",
    "zmstdcje",
    "zmsddcje",
    "zmszdcje",
    "zmsxdcje",
    "bdmbtdcje",
    "bdmbddcje",
    "bdmbzdcje",
    "bdmbxdcje",
    "bdmstdcje",
    "bdmsddcje",
    "bdmszdcje",
    "bdmsxdcje",
    "zmbtdcjzl",
    "zmbddcjzl",
    "zmbzdcjzl",
    "zmbxdcjzl",
    "zmstdcjzl",
    "zmsddcjzl",
    "zmszdcjzl",
    "zmsxdcjzl",
    "bdmbtdcjzl",
    "bdmbddcjzl",
    "bdmbzdcjzl",
    "bdmbxdcjzl",
    "bdmstdcjzl",
    "bdmsddcjzl",
    "bdmszdcjzl",
    "bdmsxdcjzl",
)


def _parse_date(value: date | str | None, *, fallback: date) -> date:
    if value is None:
        return fallback
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


class SyncBiyingMoneyflowService(BaseSyncService):
    job_name = "sync_biying_moneyflow"
    target_table = "raw_biying.moneyflow"

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.connector = create_source_connector("biying")
        self._normalizer = NormalizeMoneyflowService()

    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        execution_id = kwargs.get("execution_id")
        today = date.today()
        if run_type == "FULL":
            start_date = _parse_date(kwargs.get("start_date"), fallback=date.fromisoformat(get_settings().history_start_date))
            end_date = _parse_date(kwargs.get("end_date"), fallback=today)
        else:
            trade_date = kwargs.get("trade_date")
            if trade_date is None:
                raise ValueError("trade_date is required for incremental biying_moneyflow sync")
            start_date = _parse_date(trade_date, fallback=today)
            end_date = start_date
        if start_date > end_date:
            raise ValueError("start_date must be <= end_date")

        stocks = self._load_stocks()
        if not stocks:
            return 0, 0, None, "raw_biying.stock_basic 为空，无法拉取资金流向"

        windows = self._build_windows(start_date, end_date)
        total_units = len(stocks) * len(windows)
        self._update_progress(execution_id=execution_id, current=0, total=total_units, message=f"准备处理 {len(stocks)} 只股票。")

        fetched_total = 0
        written_total = 0
        std_written_total = 0
        current_unit = 0
        touched_keys: set[tuple[str, date]] = set()
        for dm, mc in stocks:
            for window_start, window_end in windows:
                self.ensure_not_canceled(execution_id)
                fetched, written, std_written, window_keys = self._sync_window(
                    dm=dm,
                    mc=mc,
                    window_start=window_start,
                    window_end=window_end,
                )
                fetched_total += fetched
                written_total += written
                std_written_total += std_written
                touched_keys.update(window_keys)
                current_unit += 1
                self._update_progress(
                    execution_id=execution_id,
                    current=current_unit,
                    total=total_units,
                    message=(
                        f"证券={dm} {mc or ''} "
                        f"窗口={window_start.isoformat()}~{window_end.isoformat()} "
                        f"获取={fetched} 写入={written}"
                    ).strip(),
                )

        serving_written = publish_moneyflow_serving_for_keys(self.dao, self.session, touched_keys)
        return (
            fetched_total,
            written_total,
            end_date,
            f"stocks={len(stocks)} windows={len(windows)} std={std_written_total} serving={serving_written}",
        )

    def _load_stocks(self) -> list[tuple[str, str | None]]:
        rows = self.session.execute(
            select(RawBiyingStockBasic.dm, RawBiyingStockBasic.mc)
            .where(RawBiyingStockBasic.dm.is_not(None))
            .order_by(RawBiyingStockBasic.dm.asc())
        ).all()
        return [(str(row.dm).strip().upper(), row.mc) for row in rows if row.dm]

    @staticmethod
    def _build_windows(start_date: date, end_date: date) -> list[tuple[date, date]]:
        windows: list[tuple[date, date]] = []
        cursor = start_date
        while cursor <= end_date:
            window_end = min(cursor + timedelta(days=WINDOW_DAYS - 1), end_date)
            windows.append((cursor, window_end))
            cursor = window_end + timedelta(days=1)
        return windows

    def _sync_window(
        self,
        *,
        dm: str,
        mc: str | None,
        window_start: date,
        window_end: date,
    ) -> tuple[int, int, int, set[tuple[str, date]]]:
        rows = self.connector.call(
            "moneyflow",
            params={
                "dm": dm,
                "st": window_start.strftime("%Y%m%d"),
                "et": window_end.strftime("%Y%m%d"),
            },
        )
        normalized = [self._normalize_row(dm=dm, mc=mc, row=row) for row in rows]
        written = self.dao.raw_biying_moneyflow.bulk_upsert(normalized)
        std_rows = [self._normalizer.to_std_from_biying_raw(row) for row in normalized]
        std_written = self.dao.moneyflow_std.bulk_upsert(std_rows)
        touched_keys = {
            (str(row["ts_code"]), row["trade_date"])
            for row in std_rows
            if row.get("ts_code") and isinstance(row.get("trade_date"), date)
        }
        return len(rows), written, std_written, touched_keys

    @staticmethod
    def _normalize_row(*, dm: str, mc: str | None, row: dict[str, Any]) -> dict[str, Any]:
        quote_time = datetime.fromisoformat(str(row.get("t")))
        normalized: dict[str, Any] = {
            "dm": dm,
            "mc": mc,
            "trade_date": quote_time.date(),
            "quote_time": quote_time,
            "raw_payload": json.dumps(row, ensure_ascii=False),
        }
        for field in INT_FIELDS:
            normalized[field] = _to_int(row.get(field))
        for field in DECIMAL_FIELDS:
            normalized[field] = _to_decimal(row.get(field))
        return normalized

    def _update_progress(self, *, execution_id: int | None, current: int, total: int, message: str) -> None:
        self._update_execution_progress(execution_id=execution_id, current=current, total=total, message=message)


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)
