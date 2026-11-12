"""Fill only the closing status on existing daily-basic records, one date at a time."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select, text, tuple_
from sqlalchemy.exc import SQLAlchemyError

from src.foundation.clients.bounded_tushare_call import BoundedTushareError
from src.foundation.config.settings import get_settings
from src.foundation.connectors.tushare_connector import TushareSourceConnector
from src.foundation.dao.base_dao import BaseDAO
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.errors import (
    IngestionNormalizeError,
    IngestionPlanningError,
    IngestionSourceError,
    IngestionWriteError,
    StructuredError,
)
from src.foundation.ingestion.execution_plan import DatasetActionRequest, DatasetTimeInput
from src.foundation.ingestion.normalizer import DatasetNormalizer
from src.foundation.ingestion.resolver import DatasetActionResolver
from src.foundation.ingestion.source_client import SourceFetchResult
from src.foundation.models.core_serving.equity_daily_basic import EquityDailyBasic
from src.foundation.models.raw.raw_daily_basic import RawDailyBasic
from src.utils import chunked


RESPONSE_CONTRACT = "daily_basic/v1"
PLAN_CONTRACT = "daily_basic_limit_status/v1"
TARGET_TABLES = ("raw_tushare.daily_basic", "core_serving.equity_daily_basic")


def statement_timeout(session, seconds):
    session.execute(text("SELECT set_config('statement_timeout', :value, true)"), {"value": f"{seconds}s"})


def _target_mismatch(message, **details):
    return IngestionPlanningError(StructuredError(
        error_code="daily_basic_limit_status.target_mismatch", error_type="validation",
        phase="reconcile", message=message, retryable=False, details=details,
    ))


class DailyBasicLimitStatusService:
    def __init__(self, *, session_factory, connector=None):
        self.session_factory = session_factory
        self.connector = connector if connector is not None else TushareSourceConnector()
        self.definition = get_dataset_definition("daily_basic")

    def plan_dates(self, session, *, start_date, end_date, config, check, on_batch):
        check()
        statement_timeout(session, config["statement_timeout_seconds"])
        plan = DatasetActionResolver(session).build_plan(DatasetActionRequest(
            dataset_key="daily_basic", action="maintain", trigger_source="manual",
            time_input=DatasetTimeInput(mode="range", start_date=start_date, end_date=end_date),
        ))
        check()
        if not plan.units:
            raise _target_mismatch("所选范围没有可补录的交易日期")
        on_batch([], len(plan.units), "核对两表日期计数")
        counts = []
        for model in (RawDailyBasic, EquityDailyBasic):
            check()
            counts.append(dict(session.execute(select(model.trade_date, func.count()).where(
                model.trade_date >= start_date, model.trade_date <= end_date,
            ).group_by(model.trade_date)).all()))
            check()
        dates = {unit.trade_date for unit in plan.units}
        if set(counts[0]) != dates or set(counts[1]) != dates:
            raise _target_mismatch("两表日期集合与计划交易日不一致", planned_dates=sorted(map(str, dates)),
                                   raw_dates=sorted(map(str, counts[0])), serving_dates=sorted(map(str, counts[1])))
        units = []
        for batch in chunked(plan.units, config["sync_batch_size"]):
            check()
            for unit in batch:
                day = unit.trade_date
                if counts[0][day] != counts[1][day]:
                    raise _target_mismatch(f"{day} 两表记录数不一致", trade_date=str(day),
                                           raw_count=counts[0][day], serving_count=counts[1][day])
                units.append({"trade_date": str(day), "raw_count": counts[0][day],
                              "serving_count": counts[1][day], "request_params": dict(unit.request_params),
                              "page_limit": unit.page_limit})
            on_batch(units, len(plan.units), "保存日期计划")
            check()
        return units

    def execute_day(self, payload, *, config, check, observe):
        try:
            return self._execute_day(payload, config=config, check=check, observe=observe)
        except SQLAlchemyError:
            # The date's Session has rolled back. A requested stop wins over a
            # statement timeout; ordinary SQL errors retain their original cause.
            check()
            raise

    def _execute_day(self, payload, *, config, check, observe):
        day = date.fromisoformat(payload["trade_date"])
        batch_size = BaseDAO._compute_batch_size(configured_batch_size=config["sync_batch_size"], row_param_count=3)
        check()
        with self.session_factory() as session:
            statement_timeout(session, config["statement_timeout_seconds"])
            raw, serving = self._read_targets(session, day, payload, batch_size, check, observe)
        for code, value in serving.items():
            original = raw[code]
            for status in (original, value):
                if status is not None and (type(status) is not int or status not in range(7)):
                    raise _target_mismatch(f"{day} {code} 已有收盘涨跌状态不合法", trade_date=str(day),
                                           ts_code=code, limit_status=status)
            if original is not None and value is not None and original != value:
                raise _target_mismatch(f"{day} {code} 两表已有状态冲突", trade_date=str(day),
                                       ts_code=code, raw_status=original, serving_status=value)
        if all(raw[code] is not None and serving[code] is not None for code in serving):
            check()
            return {"rows_fetched": 0, "rows_saved": len(serving), "raw_changed": 0,
                    "serving_changed": 0, "already_complete": True, "source_extra_codes": []}

        source = self._fetch(payload, config=config, check=check, observe=observe)
        normalized = self._normalize(source, day)
        source_by_code = {row["ts_code"]: row for row in normalized}
        missing = set(serving) - source_by_code.keys()
        if missing:
            raise _target_mismatch(f"{day} 源数据缺少目标股票，当前日期未提交", trade_date=str(day),
                                   missing_codes=sorted(missing))
        updates = []
        for code in serving:
            status = source_by_code[code]["limit_status"]
            if any(value is not None and value != status for value in (raw[code], serving[code])):
                raise _target_mismatch(f"{day} {code} 源状态与已有非空状态冲突", trade_date=str(day),
                                       ts_code=code, source_status=status, raw_status=raw[code], serving_status=serving[code])
            updates.append({"ts_code": code, "trade_date": day, "limit_status": status})

        changed = []
        frozen_settings = get_settings().model_copy(update={"sync_batch_size": config["sync_batch_size"]})
        check()
        # No business transaction is held while waiting for the source.
        with self.session_factory() as session:
            statement_timeout(session, config["statement_timeout_seconds"])
            for model, phase in ((RawDailyBasic, "更新原始表"), (EquityDailyBasic, "更新服务表")):
                dao = BaseDAO(session, model)
                dao.settings = frozen_settings
                count = 0
                for batch in chunked(updates, batch_size):
                    check()
                    observe(phase)
                    count += dao.bulk_update_columns(batch, ("limit_status",))
                    check()
                    observe(phase)
                changed.append(count)
            check()
            observe("提交当前日期")
            check()
            try:
                session.commit()
            except Exception as exc:
                raise IngestionWriteError(StructuredError(
                    error_code="daily_basic_limit_status.commit_unconfirmed", error_type="writer",
                    phase="commit", message=f"{day} 提交结果未确认，确认原任务已结束后按原 PLAN 重试",
                    retryable=False, details={"trade_date": str(day)},
                )) from exc
        # Return confirmed work before honoring a cancellation received during COMMIT.
        return {"rows_fetched": len(source), "rows_saved": len(updates), "raw_changed": changed[0],
                "serving_changed": changed[1], "already_complete": False,
                "source_extra_codes": sorted(source_by_code.keys() - serving.keys())}

    @staticmethod
    def _read_targets(session, day, payload, batch_size, check, observe):
        check()
        observe("读取服务表当日记录")
        serving = dict(session.execute(select(EquityDailyBasic.ts_code, EquityDailyBasic.limit_status).where(
            EquityDailyBasic.trade_date == day,
        )).all())
        check()
        observe("读取服务表当日记录")
        if len(serving) != payload["serving_count"]:
            raise _target_mismatch(f"{day} 服务表数量与冻结计划不一致", trade_date=str(day))
        raw = {}
        for codes in chunked(list(serving), batch_size):
            check()
            observe("按主键核对原始表")
            raw.update(session.execute(select(RawDailyBasic.ts_code, RawDailyBasic.limit_status).where(
                tuple_(RawDailyBasic.ts_code, RawDailyBasic.trade_date).in_([(code, day) for code in codes]),
            )).all())
            check()
            observe("按主键核对原始表")
        if len(raw) != payload["raw_count"] or raw.keys() != serving.keys():
            raise _target_mismatch(f"{day} 两表主键与冻结计划不一致", trade_date=str(day),
                                   missing_raw_codes=sorted(serving.keys() - raw.keys()))
        return raw, serving

    def _fetch(self, payload, *, config, check, observe):
        limit = payload["page_limit"]
        rows = []
        for page in range(payload["serving_count"] // limit + 1):
            check()
            observe("读取源数据", page=page + 1)
            params = {**payload["request_params"], "limit": limit, "offset": page * limit}
            try:
                batch = self.connector.call_bounded(
                    api_name=self.definition.source.api_name, params=params, fields=self.definition.source.source_fields,
                    maximum=None, timeout=config["source_timeout_seconds"],
                    check=check, tick=lambda: observe("读取源数据", page=page + 1, tick=True),
                    before_request=check, response_contract=RESPONSE_CONTRACT,
                )
            except BoundedTushareError as exc:
                raise IngestionSourceError(StructuredError(
                    error_code=exc.code, error_type="source", phase="source", message=str(exc),
                    retryable=False, details=exc.details,
                )) from exc
            check()
            observe("读取源数据", page=page + 1)
            rows.extend(batch)
            if len(batch) < limit:
                return rows
        raise IngestionSourceError(StructuredError(
            error_code="daily_basic_limit_status.pagination_incomplete", error_type="source", phase="source",
            message="每日指标在冻结页数内未遇到短页或空末页，当前日期未提交", retryable=False,
            details={"trade_date": payload["trade_date"], "rows_fetched": len(rows)},
        ))

    def _normalize(self, source, day):
        normalizer = DatasetNormalizer()
        unit_id = f"daily_basic:{day}"
        try:
            batch = normalizer.normalize(definition=self.definition, expected_unit_date=day,
                fetch_result=SourceFetchResult(unit_id=unit_id, rows_raw=source, request_count=0, retry_count=0, latency_ms=0))
        except IngestionNormalizeError as exc:
            original = exc.structured_error
            if original.error_code == "normalize.row_transform_failed":
                raise
            raise self._source_invalid(day, len(source), {original.error_code: 1}, {original.error_code: [{
                "row": original.details.get("row") or original.details.get("duplicate_row") or {},
                "field": original.details.get("field"), "value": original.details.get("actual"),
                "message": original.message,
            }]}) from exc
        if batch.rows_rejected:
            raise self._source_invalid(day, len(source), batch.rejected_reasons, batch.rejected_samples)
        reasons, samples, seen = {}, {}, set()
        for row in batch.rows_normalized:
            field = "trade_date" if row["trade_date"] != day else "ts_code"
            reason = ("normalize.unit_date_mismatch" if row["trade_date"] != day
                      else "normalize.batch_unique_key_duplicate" if row["ts_code"] in seen else None)
            if reason:
                normalizer._record_rejection(reasons, samples, reason, row=row, unit_id=unit_id,
                                             field=field, value=row[field], message="每日指标日期不符或主键重复")
            seen.add(row["ts_code"])
        if reasons:
            raise self._source_invalid(day, len(source), reasons, samples)
        return batch.rows_normalized

    @staticmethod
    def _source_invalid(day, fetched, reasons, samples):
        return IngestionNormalizeError(StructuredError(
            error_code="normalize.source_validation_failed", error_type="normalize", phase="normalizer",
            message=f"{day} 每日指标源数据未通过校验，当前日期未提交", retryable=False,
            unit_id=f"daily_basic:{day}", details={"dataset_key": "daily_basic", "trade_date": str(day),
                "rows_fetched": fetched, "rows_rejected": sum(reasons.values()),
                "rejected_reasons": reasons, "rejected_samples": samples,
                "failed_unit": {"unit_id": f"daily_basic:{day}", "rows_fetched": fetched}},
        ))
