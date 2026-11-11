from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime

from sqlalchemy import select

from src.foundation.config.settings import get_settings
from src.foundation.ingestion.index_period_serving import (
    SHANGHAI,
    IndexPeriodFrequency,
    IndexServingPeriod,
    invalid_serving_request,
    resolve_index_serving_period,
    update_index_serving_bar,
)
from src.foundation.models.core.index_basic import IndexBasic
from src.ops.index_series_active_store_adapter import INDEX_PERIOD_SERVING_RESOURCE, OpsIndexSeriesActiveStore


class IndexPeriodServingExecutor:
    def __init__(self, *, session_factory) -> None:
        self._session_factory = session_factory

    @staticmethod
    def check_schedule_cutoff(frequency: IndexPeriodFrequency, target: date) -> None:
        if datetime.now(SHANGHAI).date() > target:
            raise invalid_serving_request(
                "index_period_serving.schedule_expired",
                f"{target} 的盘后日更已过上海时间午夜，请在手动更新入口指定原目标日补数。",
                frequency=frequency, trade_date=target.isoformat(),
            )

    def prepare(
        self, frequency: IndexPeriodFrequency, params: Mapping,
    ) -> tuple[IndexServingPeriod, tuple[str, ...], dict[str, date | None]]:
        with self._session_factory() as session:
            return self.prepare_in_session(session, frequency, params, now=datetime.now(SHANGHAI))

    @staticmethod
    def prepare_in_session(session, frequency: IndexPeriodFrequency, params: Mapping, *, now: datetime):
        pool = OpsIndexSeriesActiveStore(session).list_active_codes(INDEX_PERIOD_SERVING_RESOURCE)
        if not pool:
            raise invalid_serving_request(
                "index_period_serving.pool_empty", "指数周、月线 Serving 激活池未初始化",
                resource=INDEX_PERIOD_SERVING_RESOURCE,
            )
        if len(pool) > 10:
            raise invalid_serving_request(
                "index_period_serving.pool_size", "指数周、月线 Serving 激活池超出首期 10 个代码的范围。",
                resource=INDEX_PERIOD_SERVING_RESOURCE, pool_size=len(pool),
            )
        ts_code = str(params.get("ts_code") or "").strip().upper()
        if ts_code and ts_code not in pool:
            raise invalid_serving_request(
                "index_period_serving.code_outside_pool", "指定指数不在周、月线 Serving 激活池内。",
                ts_code=ts_code,
            )
        try:
            trade_date = date.fromisoformat(str(params.get("trade_date") or ""))
        except ValueError as exc:
            raise invalid_serving_request("index_period_serving.target_date", "请指定一个目标交易日。") from exc
        period = resolve_index_serving_period(
            session, frequency=frequency, trade_date=trade_date,
            exchange=get_settings().default_exchange, now=now,
        )
        codes = (ts_code,) if ts_code else tuple(pool)
        dates = dict(session.execute(
            select(IndexBasic.ts_code, IndexBasic.list_date).where(IndexBasic.ts_code.in_(codes))
        ).all())
        return period, codes, dates

    def execute_code(self, period: IndexServingPeriod, ts_code: str, list_date: date | None):
        with self._session_factory() as session:
            result = update_index_serving_bar(session, period=period, ts_code=ts_code, list_date=list_date)
            if result.rows_saved:
                session.commit()
            return result
