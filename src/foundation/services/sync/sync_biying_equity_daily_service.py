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
from src.ops.models.ops.job_execution import JobExecution


ADJ_TYPES: tuple[tuple[str, str], ...] = (
    ("n", "不复权"),
    ("f", "前复权"),
    ("b", "后复权"),
)
WINDOW_DAYS = 3000
LATEST_LIMIT = 5000


def _parse_date(value: date | str | None, *, fallback: date) -> date:
    if value is None:
        return fallback
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


class SyncBiyingEquityDailyService(BaseSyncService):
    job_name = "sync_biying_equity_daily"
    target_table = "raw_biying.equity_daily_bar"

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.connector = create_source_connector("biying")

    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        execution_id = kwargs.get("execution_id")
        today = date.today()
        if run_type == "FULL":
            start_date = _parse_date(kwargs.get("start_date"), fallback=date.fromisoformat(get_settings().history_start_date))
            end_date = _parse_date(kwargs.get("end_date"), fallback=today)
        else:
            trade_date = kwargs.get("trade_date")
            if trade_date is None:
                raise ValueError("trade_date is required for incremental biying_equity_daily sync")
            start_date = _parse_date(trade_date, fallback=today)
            end_date = start_date
        if start_date > end_date:
            raise ValueError("start_date must be <= end_date")

        stocks = self._load_stocks()
        if not stocks:
            return 0, 0, None, "raw_biying.stock_basic 为空，无法拉取日线"

        windows = self._build_windows(start_date, end_date)
        total_units = len(stocks) * len(ADJ_TYPES) * len(windows)
        self._update_progress(execution_id=execution_id, current=0, total=total_units, message=f"准备处理 {len(stocks)} 只股票。")

        fetched_total = 0
        written_total = 0
        current_unit = 0
        for dm, mc in stocks:
            for adj_code, adj_label in ADJ_TYPES:
                for window_start, window_end in windows:
                    self.ensure_not_canceled(execution_id)
                    fetched, written = self._sync_window(
                        dm=dm,
                        mc=mc,
                        adj_type=adj_code,
                        window_start=window_start,
                        window_end=window_end,
                    )
                    fetched_total += fetched
                    written_total += written
                    current_unit += 1
                    self._update_progress(
                        execution_id=execution_id,
                        current=current_unit,
                        total=total_units,
                        message=(
                            f"证券={dm} {mc or ''} 复权类型={adj_label} "
                            f"窗口={window_start.isoformat()}~{window_end.isoformat()} "
                            f"获取={fetched} 写入={written}"
                        ).strip(),
                    )

        return fetched_total, written_total, end_date, f"stocks={len(stocks)} windows={len(windows)}"

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
        adj_type: str,
        window_start: date,
        window_end: date,
    ) -> tuple[int, int]:
        rows = self.connector.call(
            "equity_daily_bar",
            params={
                "dm": dm,
                "freq": "d",
                "adj_type": adj_type,
                "st": window_start.strftime("%Y%m%d"),
                "et": window_end.strftime("%Y%m%d"),
                "lt": str(LATEST_LIMIT),
            },
        )
        normalized = [self._normalize_row(dm=dm, mc=mc, adj_type=adj_type, row=row) for row in rows]
        written = self.dao.raw_biying_equity_daily_bar.bulk_upsert(normalized)
        return len(rows), written

    @staticmethod
    def _normalize_row(*, dm: str, mc: str | None, adj_type: str, row: dict[str, Any]) -> dict[str, Any]:
        quote_time = datetime.fromisoformat(str(row.get("t")))
        return {
            "dm": dm,
            "trade_date": quote_time.date(),
            "adj_type": adj_type,
            "mc": mc,
            "quote_time": quote_time,
            "open": _to_decimal(row.get("o")),
            "high": _to_decimal(row.get("h")),
            "low": _to_decimal(row.get("l")),
            "close": _to_decimal(row.get("c")),
            "pre_close": _to_decimal(row.get("pc")),
            "vol": _to_decimal(row.get("v")),
            "amount": _to_decimal(row.get("a")),
            "suspend_flag": _to_int(row.get("sf")),
            "raw_payload": json.dumps(row, ensure_ascii=False),
        }

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
