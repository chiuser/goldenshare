from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from datetime import timedelta
from typing import Any

from sqlalchemy import Date as SqlDate
from sqlalchemy import DateTime as SqlDateTime
from sqlalchemy import delete, or_, select, text, tuple_
from sqlalchemy.orm import Session

from src.foundation.dao.factory import DAOFactory

from src.foundation.datasets.models import DatasetDefinition
from src.foundation.ingestion.errors import IngestionWriteError, StructuredError
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot
from src.foundation.ingestion.moneyflow_publish import publish_moneyflow_serving_for_keys
from src.foundation.ingestion.normalizer import NormalizedBatch
from src.foundation.ingestion.sentinel_guard import (
    find_forbidden_business_sentinel_in_row_context,
    should_guard_dataset_rows,
)
from src.foundation.services.transform.normalize_moneyflow_service import NormalizeMoneyflowService
from src.foundation.services.transform.normalize_security_service import NormalizeSecurityService
from src.utils import parse_tushare_date
from src.foundation.serving.publish_service import ServingPublishService


@dataclass(slots=True, frozen=True)
class WriteResult:
    unit_id: str
    rows_written: int
    rows_upserted: int
    rows_skipped: int
    target_table: str
    conflict_strategy: str
    rows_rejected: int = 0
    rejected_reason_counts: dict[str, int] = field(default_factory=dict)


class DatasetWriter:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.dao = DAOFactory(session)
        self._moneyflow_normalizer = NormalizeMoneyflowService()
        self._security_normalizer = NormalizeSecurityService()

    def write(
        self,
        *,
        definition: DatasetDefinition,
        batch: NormalizedBatch,
        plan_unit: PlanUnitSnapshot | None = None,
        run_profile: str | None = None,
    ) -> WriteResult:
        if should_guard_dataset_rows(definition.dataset_key):
            for index, row in enumerate(batch.rows_normalized):
                sentinel = find_forbidden_business_sentinel_in_row_context(row, path=f"rows_normalized[{index}]")
                if sentinel is not None:
                    path, value = sentinel
                    raise IngestionWriteError(
                        StructuredError(
                            error_code="forbidden_sentinel",
                            error_type="write",
                            phase="writer",
                            message=f"检测到非法业务占位值：{value}，位置：{path}",
                            retryable=False,
                            unit_id=batch.unit_id,
                        )
                    )
        raw_dao = getattr(self.dao, definition.storage.raw_dao_name, None)
        core_dao = getattr(self.dao, definition.storage.core_dao_name, None)
        if raw_dao is None or core_dao is None:
            raise IngestionWriteError(
                StructuredError(
                    error_code="dao_not_found",
                    error_type="write",
                    phase="writer",
                    message=(
                        f"DAO not found: raw={definition.storage.raw_dao_name} "
                        f"core={definition.storage.core_dao_name}"
                    ),
                    retryable=False,
                    unit_id=batch.unit_id,
                )
            )

        try:
            if definition.storage.write_path == "raw_index_period_serving_upsert":
                return self._write_index_period_serving(
                    definition=definition,
                    batch=batch,
                    raw_dao=raw_dao,
                    core_dao=core_dao,
                    plan_unit=plan_unit,
                    run_profile=run_profile,
                )
            if not batch.rows_normalized:
                return WriteResult(
                    unit_id=batch.unit_id,
                    rows_written=0,
                    rows_upserted=0,
                    rows_skipped=batch.rows_rejected,
                    target_table=definition.storage.target_table,
                    conflict_strategy="upsert",
                )
            if definition.storage.write_path == "raw_std_publish_moneyflow":
                return self._write_moneyflow_std_publish(
                    definition=definition,
                    batch=batch,
                    raw_dao=raw_dao,
                    std_dao=core_dao,
                )
            if definition.storage.write_path == "raw_std_publish_stock_basic":
                return self._write_stock_basic_std_publish(
                    definition=definition,
                    batch=batch,
                    plan_unit=plan_unit,
                )
            if definition.storage.write_path == "raw_std_publish_moneyflow_biying":
                return self._write_moneyflow_std_publish_biying(
                    definition=definition,
                    batch=batch,
                    raw_dao=raw_dao,
                    std_dao=core_dao,
                )
            if definition.storage.write_path == "raw_core_snapshot_insert_by_trade_date":
                return self._write_snapshot_insert_by_trade_date(
                    definition=definition,
                    batch=batch,
                    raw_dao=raw_dao,
                    core_dao=core_dao,
                )
            if definition.storage.write_path == "raw_only_upsert":
                return self._write_raw_only_upsert(
                    definition=definition,
                    batch=batch,
                    raw_dao=raw_dao,
                )
            if definition.storage.write_path != "raw_core_upsert":
                raise ValueError(f"不支持的写入路径：{definition.storage.write_path}")
            rows_upserted = self._write_raw_and_core(
                batch=batch,
                raw_dao=raw_dao,
                core_dao=core_dao,
                conflict_columns=definition.storage.conflict_columns,
            )
            rejected_reason_counts = self._duplicate_reason_counts(
                rows=batch.rows_normalized,
                conflict_columns=self._resolve_conflict_columns(
                    core_dao,
                    definition.storage.conflict_columns,
                ),
            )
        except Exception as exc:
            raise IngestionWriteError(
                StructuredError(
                    error_code="write_failed",
                    error_type="write",
                    phase="writer",
                    message=str(exc),
                    retryable=False,
                    unit_id=batch.unit_id,
                )
            ) from exc

        return WriteResult(
            unit_id=batch.unit_id,
            rows_written=rows_upserted,
            rows_upserted=rows_upserted,
            rows_skipped=batch.rows_rejected,
            target_table=definition.storage.target_table,
            conflict_strategy="upsert",
            rows_rejected=sum(rejected_reason_counts.values()),
            rejected_reason_counts=rejected_reason_counts,
        )

    def _write_index_period_serving(
        self,
        *,
        definition: DatasetDefinition,
        batch: NormalizedBatch,
        raw_dao,
        core_dao,
        plan_unit: PlanUnitSnapshot | None,
        run_profile: str | None,
    ) -> WriteResult:
        rows_written = 0
        conflict_strategy = "upsert"
        rejected_reason_counts: dict[str, int] = {}
        active_codes = self._resolve_active_index_codes()
        explicit_ts_code = bool(
            plan_unit is not None and str(plan_unit.request_params.get("ts_code") or "").strip()
        )
        full_date_refresh = (not explicit_ts_code) and run_profile in {"point_incremental", "range_rebuild"}
        if batch.rows_normalized:
            filtered_rows = self._filter_index_rows_by_active_pool(
                rows=batch.rows_normalized,
                active_codes=active_codes,
            )
            rejected_reason_counts = self._reason_count(
                "write.filtered_by_business_rule:ts_code",
                len(batch.rows_normalized) - len(filtered_rows),
            )
            if not filtered_rows:
                return WriteResult(
                    unit_id=batch.unit_id,
                    rows_written=0,
                    rows_upserted=0,
                    rows_skipped=batch.rows_rejected,
                    target_table=definition.storage.target_table,
                    conflict_strategy="index_period_filtered_empty",
                    rows_rejected=sum(rejected_reason_counts.values()),
                    rejected_reason_counts=rejected_reason_counts,
                )
            self._merge_reason_counts(
                rejected_reason_counts,
                self._duplicate_reason_counts(
                    rows=filtered_rows,
                    conflict_columns=self._resolve_conflict_columns(
                        raw_dao,
                        definition.storage.conflict_columns,
                    ),
                ),
            )
            if full_date_refresh:
                self._purge_index_period_raw_rows_by_trade_dates(raw_dao=raw_dao, rows=filtered_rows)
            if definition.storage.conflict_columns:
                raw_dao.bulk_upsert(filtered_rows, conflict_columns=list(definition.storage.conflict_columns))
            else:
                raw_dao.bulk_upsert(filtered_rows)
            serving_rows = self._build_index_period_serving_rows(
                rows=filtered_rows,
                dataset_key=definition.dataset_key,
            )
            if full_date_refresh and plan_unit is not None and not explicit_ts_code:
                trade_date = plan_unit.trade_date
                if isinstance(trade_date, date):
                    existing_codes = {
                        str(row.get("ts_code")).strip().upper()
                        for row in serving_rows
                        if row.get("ts_code")
                    }
                    missing_codes = sorted(active_codes - existing_codes)
                    if missing_codes:
                        serving_rows.extend(
                            self._build_index_period_derived_rows_for_codes(
                                definition=definition,
                                trade_date=trade_date,
                                ts_codes=missing_codes,
                            )
                        )
            if full_date_refresh:
                rows_written = self._replace_index_period_serving_rows_by_trade_dates(
                    core_dao=core_dao,
                    rows=serving_rows,
                )
            else:
                rows_written = self._replace_index_period_serving_rows(
                    core_dao=core_dao,
                    rows=serving_rows,
                    keep_api=False,
                )
            conflict_strategy = "index_period_upsert"
        elif plan_unit is not None and (run_profile == "point_incremental" or full_date_refresh):
            if explicit_ts_code:
                derived_rows = self._build_index_period_derived_rows(
                    definition=definition,
                    plan_unit=plan_unit,
                )
            else:
                trade_date = plan_unit.trade_date
                derived_rows = (
                    self._build_index_period_derived_rows_for_codes(
                        definition=definition,
                        trade_date=trade_date,
                        ts_codes=sorted(active_codes),
                    )
                    if isinstance(trade_date, date)
                    else []
                )
            if full_date_refresh:
                rows_written = self._replace_index_period_serving_rows_by_trade_dates(
                    core_dao=core_dao,
                    rows=derived_rows,
                )
            else:
                rows_written = self._replace_index_period_serving_rows(
                    core_dao=core_dao,
                    rows=derived_rows,
                    keep_api=True,
                )
            conflict_strategy = "derived_daily_fallback"

        return WriteResult(
            unit_id=batch.unit_id,
            rows_written=rows_written,
            rows_upserted=rows_written,
            rows_skipped=batch.rows_rejected,
            target_table=definition.storage.target_table,
            conflict_strategy=conflict_strategy,
            rows_rejected=sum(rejected_reason_counts.values()),
            rejected_reason_counts=rejected_reason_counts,
        )

    def _build_index_period_serving_rows(
        self,
        *,
        rows: list[dict[str, Any]],
        dataset_key: str,
    ) -> list[dict[str, Any]]:
        period_start_cache: dict[date, date] = {}
        serving_rows: list[dict[str, Any]] = []
        for row in rows:
            trade_date = row.get("trade_date")
            ts_code = row.get("ts_code")
            if not isinstance(trade_date, date) or ts_code in (None, ""):
                continue
            transformed = dict(row)
            transformed["period_start_date"] = self._resolve_index_period_start_date(
                dataset_key=dataset_key,
                trade_date=trade_date,
                cache=period_start_cache,
            )
            transformed["source"] = "api"
            transformed.setdefault("change_amount", transformed.get("change"))
            serving_rows.append(transformed)
        return serving_rows

    def _build_index_period_derived_rows(
        self,
        *,
        definition: DatasetDefinition,
        plan_unit: PlanUnitSnapshot,
    ) -> list[dict[str, Any]]:
        ts_code = str(plan_unit.request_params.get("ts_code") or "").strip().upper()
        trade_date = plan_unit.trade_date
        if not ts_code or not isinstance(trade_date, date):
            return []
        return self._build_index_period_derived_rows_for_codes(
            definition=definition,
            trade_date=trade_date,
            ts_codes=[ts_code],
        )

    def _build_index_period_derived_rows_for_codes(
        self,
        *,
        definition: DatasetDefinition,
        trade_date: date,
        ts_codes: list[str],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for code in ts_codes:
            ts_code = str(code or "").strip().upper()
            if not ts_code:
                continue
            results.extend(
                self._build_index_period_derived_rows_for_single_code(
                    definition=definition,
                    trade_date=trade_date,
                    ts_code=ts_code,
                )
            )
        return results

    def _build_index_period_derived_rows_for_single_code(
        self,
        *,
        definition: DatasetDefinition,
        trade_date: date,
        ts_code: str,
    ) -> list[dict[str, Any]]:
        period_start_date = self._resolve_index_period_start_date(
            dataset_key=definition.dataset_key,
            trade_date=trade_date,
            cache={},
        )
        sql = text(
            """
            with win as (
                select
                    d.ts_code,
                    d.trade_date,
                    d.open,
                    d.high,
                    d.low,
                    d.close,
                    d.pre_close,
                    d.vol,
                    d.amount,
                    row_number() over (partition by d.ts_code order by d.trade_date asc) as rn_first,
                    row_number() over (partition by d.ts_code order by d.trade_date desc) as rn_last
                from core_serving.index_daily_serving d
                where d.trade_date between :start_date and :trade_date
                  and d.ts_code = :ts_code
            ),
            agg as (
                select
                    ts_code,
                    max(case when rn_first = 1 then open end) as open,
                    max(high) as high,
                    min(low) as low,
                    max(case when rn_last = 1 then close end) as close,
                    max(case when rn_first = 1 then pre_close end) as pre_close,
                    sum(vol) as vol,
                    sum(amount) as amount
                from win
                group by ts_code
            )
            select
                a.ts_code as ts_code,
                :period_start_date as period_start_date,
                :trade_date as trade_date,
                a.open as open,
                a.high as high,
                a.low as low,
                a.close as close,
                a.pre_close as pre_close,
                case when a.pre_close is null or a.close is null then null else a.close - a.pre_close end as change_amount,
                case
                    when a.pre_close is null or a.pre_close = 0 or a.close is null then null
                    else round(((a.close / a.pre_close) - 1), 4)
                end as pct_chg,
                a.vol * 100 as vol,
                a.amount * 1000 as amount,
                'derived_daily' as source
            from agg a
            """
        )
        rows = self.session.execute(
            sql,
            {
                "ts_code": ts_code,
                "trade_date": trade_date,
                "period_start_date": period_start_date,
                "start_date": period_start_date,
            },
        ).mappings()
        return [dict(row) for row in rows]

    def _replace_index_period_serving_rows(
        self,
        *,
        core_dao,
        rows: list[dict[str, Any]],
        keep_api: bool,
    ) -> int:
        if not rows:
            return 0
        deduped_rows = self._dedupe_index_period_rows(rows)
        if not deduped_rows:
            return 0
        model = core_dao.model
        period_keys = [(row["ts_code"], row["period_start_date"]) for row in deduped_rows]
        trade_keys = [(row["ts_code"], row["trade_date"]) for row in deduped_rows]
        stmt = delete(model).where(
            or_(
                tuple_(model.ts_code, model.period_start_date).in_(period_keys),
                tuple_(model.ts_code, model.trade_date).in_(trade_keys),
            )
        )
        if keep_api:
            stmt = stmt.where(model.source != "api")
        self.session.execute(stmt)
        return core_dao.bulk_insert(deduped_rows)

    def _replace_index_period_serving_rows_by_trade_dates(
        self,
        *,
        core_dao,
        rows: list[dict[str, Any]],
    ) -> int:
        trade_dates = sorted(
            {
                row["trade_date"]
                for row in rows
                if isinstance(row.get("trade_date"), date)
            }
        )
        if not trade_dates:
            return 0
        model = core_dao.model
        self.session.execute(delete(model).where(model.trade_date.in_(trade_dates)))
        deduped_rows = self._dedupe_index_period_rows(rows)
        if not deduped_rows:
            return 0
        return core_dao.bulk_insert(deduped_rows)

    @staticmethod
    def _dedupe_index_period_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped_by_key: dict[tuple[str, date], dict[str, Any]] = {}
        for row in rows:
            ts_code = row.get("ts_code")
            period_start_date = row.get("period_start_date")
            trade_date = row.get("trade_date")
            if ts_code in (None, "") or not isinstance(period_start_date, date) or not isinstance(trade_date, date):
                continue
            deduped_by_key[(str(ts_code), period_start_date)] = row
        return list(deduped_by_key.values())

    @staticmethod
    def _filter_index_rows_by_active_pool(
        *,
        rows: list[dict[str, Any]],
        active_codes: set[str],
    ) -> list[dict[str, Any]]:
        if not active_codes:
            return []
        filtered_rows: list[dict[str, Any]] = []
        for row in rows:
            ts_code = str(row.get("ts_code") or "").strip().upper()
            if ts_code and ts_code in active_codes:
                filtered_rows.append(row)
        return filtered_rows

    def _resolve_active_index_codes(self) -> set[str]:
        active_codes = self.dao.index_series_active.list_active_codes("index_daily")
        if not active_codes:
            active_codes = [item.ts_code for item in self.dao.index_basic.get_active_indexes() if item.ts_code]
        normalized = {
            str(code).strip().upper()
            for code in active_codes
            if str(code).strip()
        }
        if not normalized:
            raise ValueError("未找到可维护的指数代码")
        return normalized

    @staticmethod
    def _purge_index_period_raw_rows_by_trade_dates(*, raw_dao, rows: list[dict[str, Any]]) -> None:
        trade_dates = sorted({row["trade_date"] for row in rows if isinstance(row.get("trade_date"), date)})
        for current_date in trade_dates:
            raw_dao.delete_by_date_range(current_date, current_date)

    def _resolve_index_period_start_date(
        self,
        *,
        dataset_key: str,
        trade_date: date,
        cache: dict[date, date] | None,
    ) -> date:
        natural_start = self._resolve_natural_period_start(dataset_key=dataset_key, trade_date=trade_date)
        if cache is not None and natural_start in cache:
            return cache[natural_start]
        exchange = self.dao.trade_calendar.settings.default_exchange
        open_dates = self.dao.trade_calendar.get_open_dates(exchange, natural_start, trade_date)
        period_start = open_dates[0] if open_dates else natural_start
        if cache is not None:
            cache[natural_start] = period_start
        return period_start

    @staticmethod
    def _resolve_natural_period_start(*, dataset_key: str, trade_date: date) -> date:
        if dataset_key == "index_monthly":
            return trade_date.replace(day=1)
        if dataset_key == "index_weekly":
            return trade_date - timedelta(days=trade_date.weekday())
        raise ValueError(f"不支持生成指数周期服务数据：{dataset_key}")

    @classmethod
    def _write_raw_and_core(
        cls,
        *,
        batch: NormalizedBatch,
        raw_dao,
        core_dao,
        conflict_columns: tuple[str, ...] | None,
    ) -> int:
        raw_rows = cls._coerce_rows_for_dao(batch.rows_normalized, raw_dao)
        core_rows = cls._coerce_rows_for_dao(batch.rows_normalized, core_dao)
        if conflict_columns:
            raw_dao.bulk_upsert(raw_rows, conflict_columns=list(conflict_columns))
            return core_dao.bulk_upsert(core_rows, conflict_columns=list(conflict_columns))
        raw_dao.bulk_upsert(raw_rows)
        return core_dao.bulk_upsert(core_rows)

    @staticmethod
    def _coerce_rows_for_dao(rows: list[dict[str, Any]], dao) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
        model = getattr(dao, "model", None)
        table = getattr(model, "__table__", None)
        if table is None:
            return [dict(row) for row in rows]
        date_columns = {
            column.name
            for column in table.columns
            if isinstance(column.type, SqlDate) and not isinstance(column.type, SqlDateTime)
        }
        if not date_columns:
            return [dict(row) for row in rows]
        prepared: list[dict[str, Any]] = []
        for row in rows:
            normalized = dict(row)
            for column_name in date_columns:
                if column_name in normalized:
                    normalized[column_name] = parse_tushare_date(normalized[column_name])
            prepared.append(normalized)
        return prepared

    @staticmethod
    def _resolve_conflict_columns(dao, explicit_columns: tuple[str, ...] | None) -> tuple[str, ...]:
        if explicit_columns:
            return tuple(explicit_columns)
        model = getattr(dao, "model", None)
        table = getattr(model, "__table__", None)
        primary_key = getattr(table, "primary_key", None)
        if primary_key is None:
            return ()
        return tuple(column.name for column in primary_key.columns)

    @classmethod
    def _duplicate_reason_counts(
        cls,
        *,
        rows: list[dict[str, Any]],
        conflict_columns: tuple[str, ...] | list[str] | None,
    ) -> dict[str, int]:
        columns = tuple(conflict_columns or ())
        if not rows or not columns:
            return {}
        seen: set[tuple[Any, ...]] = set()
        duplicate_count = 0
        for row in rows:
            if any(column not in row or row[column] is None for column in columns):
                continue
            key = tuple(row[column] for column in columns)
            if key in seen:
                duplicate_count += 1
                continue
            seen.add(key)
        return cls._reason_count(
            f"write.duplicate_conflict_key_in_batch:{','.join(columns)}",
            duplicate_count,
        )

    @staticmethod
    def _reason_count(reason_key: str, count: int) -> dict[str, int]:
        normalized_count = int(count or 0)
        if normalized_count <= 0:
            return {}
        return {reason_key: normalized_count}

    @staticmethod
    def _merge_reason_counts(target: dict[str, int], source: dict[str, int]) -> None:
        for key, count in source.items():
            normalized_key = str(key or "").strip()
            normalized_count = int(count or 0)
            if not normalized_key or normalized_count <= 0:
                continue
            target[normalized_key] = target.get(normalized_key, 0) + normalized_count

    def _write_stock_basic_std_publish(
        self,
        *,
        definition: DatasetDefinition,
        batch: NormalizedBatch,
        plan_unit: PlanUnitSnapshot | None,
    ) -> WriteResult:
        source_key = str(plan_unit.source_key if plan_unit is not None else "tushare").strip().lower()
        requested_source_key = str(
            plan_unit.requested_source_key if plan_unit is not None else source_key
        ).strip().lower()
        if source_key not in {"tushare", "biying"}:
            raise ValueError(f"股票基础信息不支持该数据来源：{source_key}")

        raw_dao = self.dao.raw_tushare_stock_basic if source_key == "tushare" else self.dao.raw_biying_stock_basic
        raw_rows = self._prepare_stock_basic_raw_rows(rows=batch.rows_normalized, source_key=source_key)
        if raw_rows:
            raw_dao.bulk_upsert(raw_rows)

        std_rows = [self._security_normalizer.to_std(row, source_key=source_key) for row in batch.rows_normalized]
        if std_rows:
            self.dao.security_std.bulk_upsert(std_rows)

        written = 0
        conflict_strategy = "upsert"
        rejected_reason_counts: dict[str, int] = {}
        if requested_source_key == "all":
            touched_ts_codes = {
                str(row.get("ts_code")).strip().upper()
                for row in std_rows
                if str(row.get("ts_code") or "").strip()
            }
            std_rows_by_source = self._load_security_std_rows_by_source(touched_ts_codes=touched_ts_codes)
            publish_result = ServingPublishService(self.dao).publish_dataset(
                dataset_key="stock_basic",
                std_rows_by_source=std_rows_by_source,
            )
            written = int(publish_result.written)
            conflict_strategy = "resolution_publish"
        elif source_key == "biying":
            ts_codes = [str(row["ts_code"]) for row in std_rows if row.get("ts_code")]
            existing = self.dao.security.get_existing_ts_codes(ts_codes)
            serving_rows = [
                {key: value for key, value in row.items() if key != "source_key"}
                for row in std_rows
                if str(row.get("ts_code") or "") and str(row["ts_code"]) not in existing
            ]
            written = self.dao.security.upsert_many(serving_rows) if serving_rows else 0
            conflict_strategy = "biying_missing_only"
            rejected_reason_counts = self._reason_count(
                "write.filtered_by_business_rule:ts_code",
                len(std_rows) - len(serving_rows),
            )
        else:
            serving_rows = [{key: value for key, value in row.items() if key != "source_key"} for row in std_rows]
            written = self.dao.security.upsert_many(serving_rows) if serving_rows else 0
            conflict_strategy = "tushare_direct_upsert"

        return WriteResult(
            unit_id=batch.unit_id,
            rows_written=written,
            rows_upserted=written,
            rows_skipped=batch.rows_rejected,
            target_table=definition.storage.target_table,
            conflict_strategy=conflict_strategy,
            rows_rejected=sum(rejected_reason_counts.values()),
            rejected_reason_counts=rejected_reason_counts,
        )

    @staticmethod
    def _prepare_stock_basic_raw_rows(*, rows: list[dict[str, Any]], source_key: str) -> list[dict[str, Any]]:
        if source_key == "tushare":
            prepared: list[dict[str, Any]] = []
            for row in rows:
                ts_code = str(row.get("ts_code") or "").strip().upper()
                if not ts_code:
                    continue
                normalized = dict(row)
                normalized["ts_code"] = ts_code
                prepared.append(normalized)
            return prepared

        prepared = []
        for row in rows:
            dm = str(row.get("dm") or row.get("ts_code") or "").strip().upper()
            if not dm:
                continue
            prepared.append(
                {
                    "dm": dm,
                    "mc": row.get("mc") or row.get("name"),
                    "jys": row.get("jys") or row.get("exchange"),
                }
            )
        return prepared

    def _load_security_std_rows_by_source(self, *, touched_ts_codes: set[str]) -> dict[str, list[dict[str, Any]]]:
        if not touched_ts_codes:
            return {}
        model = self.dao.security_std.model
        columns = [column.name for column in model.__table__.columns if column.name not in {"created_at", "updated_at"}]
        stmt = select(model).where(model.ts_code.in_(sorted(touched_ts_codes)))
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in self.session.scalars(stmt):
            source = str(getattr(item, "source_key", "") or "").strip()
            if not source:
                continue
            payload = {column_name: getattr(item, column_name) for column_name in columns}
            grouped.setdefault(source, []).append(payload)
        return grouped

    def _write_moneyflow_std_publish(
        self,
        *,
        definition: DatasetDefinition,
        batch: NormalizedBatch,
        raw_dao,
        std_dao,
    ) -> WriteResult:
        rejected_reason_counts = self._duplicate_reason_counts(
            rows=batch.rows_normalized,
            conflict_columns=self._resolve_conflict_columns(std_dao, definition.storage.conflict_columns),
        )
        if definition.storage.conflict_columns:
            raw_dao.bulk_upsert(batch.rows_normalized, conflict_columns=list(definition.storage.conflict_columns))
        else:
            raw_dao.bulk_upsert(batch.rows_normalized)
        std_rows = [self._moneyflow_normalizer.to_std_from_tushare(row) for row in batch.rows_normalized]
        if definition.storage.conflict_columns:
            std_dao.bulk_upsert(std_rows, conflict_columns=list(definition.storage.conflict_columns))
        else:
            std_dao.bulk_upsert(std_rows)
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
        return WriteResult(
            unit_id=batch.unit_id,
            rows_written=serving_written,
            rows_upserted=serving_written,
            rows_skipped=batch.rows_rejected,
            target_table=definition.storage.target_table,
            conflict_strategy="upsert",
            rows_rejected=sum(rejected_reason_counts.values()),
            rejected_reason_counts=rejected_reason_counts,
        )

    def _write_moneyflow_std_publish_biying(
        self,
        *,
        definition: DatasetDefinition,
        batch: NormalizedBatch,
        raw_dao,
        std_dao,
    ) -> WriteResult:
        rejected_reason_counts = self._duplicate_reason_counts(
            rows=batch.rows_normalized,
            conflict_columns=self._resolve_conflict_columns(std_dao, definition.storage.conflict_columns),
        )
        if definition.storage.conflict_columns:
            raw_dao.bulk_upsert(batch.rows_normalized, conflict_columns=list(definition.storage.conflict_columns))
        else:
            raw_dao.bulk_upsert(batch.rows_normalized)
        std_rows = [self._moneyflow_normalizer.to_std_from_biying_raw(row) for row in batch.rows_normalized]
        if definition.storage.conflict_columns:
            std_dao.bulk_upsert(std_rows, conflict_columns=list(definition.storage.conflict_columns))
        else:
            std_dao.bulk_upsert(std_rows)
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
        return WriteResult(
            unit_id=batch.unit_id,
            rows_written=serving_written,
            rows_upserted=serving_written,
            rows_skipped=batch.rows_rejected,
            target_table=definition.storage.target_table,
            conflict_strategy="upsert",
            rows_rejected=sum(rejected_reason_counts.values()),
            rejected_reason_counts=rejected_reason_counts,
        )

    @staticmethod
    def _write_raw_only_upsert(
        *,
        definition: DatasetDefinition,
        batch: NormalizedBatch,
        raw_dao,
    ) -> WriteResult:
        if definition.storage.conflict_columns:
            rejected_reason_counts = DatasetWriter._duplicate_reason_counts(
                rows=batch.rows_normalized,
                conflict_columns=definition.storage.conflict_columns,
            )
            rows_written = raw_dao.bulk_upsert(
                batch.rows_normalized,
                conflict_columns=list(definition.storage.conflict_columns),
            )
        else:
            rejected_reason_counts = DatasetWriter._duplicate_reason_counts(
                rows=batch.rows_normalized,
                conflict_columns=DatasetWriter._resolve_conflict_columns(raw_dao, None),
            )
            rows_written = raw_dao.bulk_upsert(batch.rows_normalized)
        return WriteResult(
            unit_id=batch.unit_id,
            rows_written=rows_written,
            rows_upserted=rows_written,
            rows_skipped=batch.rows_rejected,
            target_table=definition.storage.target_table,
            conflict_strategy="upsert",
            rows_rejected=sum(rejected_reason_counts.values()),
            rejected_reason_counts=rejected_reason_counts,
        )

    @staticmethod
    def _write_snapshot_insert_by_trade_date(
        *,
        definition: DatasetDefinition,
        batch: NormalizedBatch,
        raw_dao,
        core_dao,
    ) -> WriteResult:
        target_dates = sorted({row["trade_date"] for row in batch.rows_normalized if row.get("trade_date") is not None})
        for current_date in target_dates:
            raw_dao.delete_by_date_range(current_date, current_date)
            core_dao.delete_by_date_range(current_date, current_date)

        raw_dao.bulk_insert(batch.rows_normalized)
        written = core_dao.bulk_insert(batch.rows_normalized)
        return WriteResult(
            unit_id=batch.unit_id,
            rows_written=written,
            rows_upserted=written,
            rows_skipped=batch.rows_rejected,
            target_table=definition.storage.target_table,
            conflict_strategy="snapshot_insert_by_trade_date",
            rows_rejected=0,
            rejected_reason_counts={},
        )
