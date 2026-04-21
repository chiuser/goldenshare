from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select, tuple_

from src.foundation.clients.tushare_client import TushareHttpClient
from src.foundation.models.core_multi.moneyflow_std import MoneyflowStd
from src.foundation.serving.publish_service import ServingPublishService
from src.foundation.services.sync.fields import MONEYFLOW_FIELDS
from src.foundation.services.sync.base_sync_service import BaseSyncService
from src.foundation.services.sync.sync_daily_basic_service import build_trade_date_only
from src.foundation.services.transform.normalize_moneyflow_service import NormalizeMoneyflowService
from src.utils import chunked, coerce_row


_MONEYFLOW_STD_FETCH_CHUNK_SIZE = 2000


def _std_rows_by_source_from_business_keys(
    session,
    keys: set[tuple[str, date]],
) -> dict[str, list[dict[str, Any]]]:
    if not keys:
        return {}

    rows_by_source: dict[str, list[dict[str, Any]]] = {}
    ordered_keys = sorted(keys)
    columns = [column.name for column in MoneyflowStd.__table__.columns if column.name not in {"created_at", "updated_at"}]
    for batch in chunked(ordered_keys, _MONEYFLOW_STD_FETCH_CHUNK_SIZE):
        stmt = select(MoneyflowStd).where(
            tuple_(MoneyflowStd.ts_code, MoneyflowStd.trade_date).in_(batch)
        )
        for row in session.scalars(stmt):
            source_rows = rows_by_source.setdefault(row.source_key, [])
            source_rows.append({column: getattr(row, column) for column in columns})
    return rows_by_source


def publish_moneyflow_serving_for_keys(
    dao,
    session,
    keys: set[tuple[str, date]],
) -> int:
    std_rows_by_source = _std_rows_by_source_from_business_keys(session, keys)
    if not std_rows_by_source:
        return 0
    publish_result = ServingPublishService(dao).publish_dataset(
        dataset_key="moneyflow",
        std_rows_by_source=std_rows_by_source,
    )
    return publish_result.written


class SyncMoneyflowService(BaseSyncService):
    job_name = "sync_moneyflow"
    target_table = "core_serving.equity_moneyflow"
    api_name = "moneyflow"
    fields = MONEYFLOW_FIELDS
    date_fields = ("trade_date",)
    volume_fields = (
        "buy_sm_vol",
        "sell_sm_vol",
        "buy_md_vol",
        "sell_md_vol",
        "buy_lg_vol",
        "sell_lg_vol",
        "buy_elg_vol",
        "sell_elg_vol",
        "net_mf_vol",
    )
    decimal_fields = (
        "buy_sm_amount",
        "sell_sm_amount",
        "buy_md_amount",
        "sell_md_amount",
        "buy_lg_amount",
        "sell_lg_amount",
        "buy_elg_amount",
        "sell_elg_amount",
        "net_mf_amount",
    )
    params_builder = staticmethod(build_trade_date_only)
    _normalizer = NormalizeMoneyflowService()

    def __init__(self, session) -> None:  # type: ignore[no-untyped-def]
        super().__init__(session)
        self.client = TushareHttpClient()

    @classmethod
    def _coerce_integer_volumes(cls, row: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(row)
        for field in cls.volume_fields:
            if field not in normalized:
                continue
            value = normalized.get(field)
            if value in (None, ""):
                normalized[field] = None
                continue
            decimal_value = Decimal(str(value))
            if decimal_value != decimal_value.to_integral_value():
                raise ValueError(f"moneyflow field `{field}` must be integer-like, got: {value}")
            normalized[field] = int(decimal_value)
        return normalized

    def execute(self, run_type: str, **kwargs: Any) -> tuple[int, int, date | None, str | None]:
        trade_date = kwargs.get("trade_date")
        rows = self.client.call(
            self.api_name,
            params=self.params_builder(run_type, **kwargs),
            fields=self.fields,
        )
        normalized = [
            self._coerce_integer_volumes(
                coerce_row(row, self.date_fields, self.decimal_fields),
            )
            for row in rows
        ]
        self.dao.raw_moneyflow.bulk_upsert(normalized)

        std_rows = [self._normalizer.to_std_from_tushare(row) for row in normalized]
        std_written = self.dao.moneyflow_std.bulk_upsert(std_rows)
        touched_keys = {
            (str(row["ts_code"]), row["trade_date"])
            for row in std_rows
            if row.get("ts_code") and isinstance(row.get("trade_date"), date)
        }
        serving_written = publish_moneyflow_serving_for_keys(
            self.dao,
            self.session,
            touched_keys,
        )
        message = f"source=tushare std={std_written} serving={serving_written}"
        return len(rows), serving_written, trade_date, message
