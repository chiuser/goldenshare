from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select, tuple_

from src.foundation.models.core_multi.moneyflow_std import MoneyflowStd
from src.foundation.serving.publish_service import ServingPublishService
from src.utils import chunked

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

