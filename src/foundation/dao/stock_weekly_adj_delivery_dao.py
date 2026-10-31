"""Bounded append/read operations; the publisher owns locks, policy and commits."""

from copy import deepcopy
from datetime import date
import re
from uuid import UUID

from sqlalchemy import Text, cast, literal, select
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import defer
from sqlalchemy.orm.attributes import set_committed_value

from src.foundation.datasets.stock_weekly_adj_contracts import (
    WeeklyAdjContractError,
    SOURCE_ROW_BLOCK_SIZE,
    WeeklyAdjExecutionPolicy,
    canonical_json,
    canonical_json_size,
    canonical_source_rows,
    digest,
    validate_correction_payload,
)
from src.foundation.models.core.stock_weekly_adj_delivery import StockWeeklyAdjDelivery


class StockWeeklyAdjDeliveryDAO:
    def __init__(self, session):
        self.session = session

    def get_record(self, *, batch_id, record_kind, unit_id):
        return self.session.scalar(
            select(StockWeeklyAdjDelivery)
            .where(
                StockWeeklyAdjDelivery.batch_id == UUID(str(batch_id)),
                StockWeeklyAdjDelivery.record_kind == record_kind,
                StockWeeklyAdjDelivery.unit_id == unit_id,
            )
            .execution_options(populate_existing=True)
        )

    def append(self, record: dict, policy: WeeklyAdjExecutionPolicy):
        """Idempotent append. Conflict with different business values is never upserted."""
        allowed = set(StockWeeklyAdjDelivery.__table__.columns.keys()) - {
            "revision",
            "published_at",
        }
        if set(record) != allowed:
            raise WeeklyAdjContractError("交接记录字段不完整或包含技术主键")
        # Validation and SQL serialization never mutate nested input values.
        values = dict(record)
        try:
            values["batch_id"] = UUID(str(values["batch_id"]))
        except (ValueError, TypeError, AttributeError):
            raise WeeklyAdjContractError("交接批次UUID无效") from None
        if (
            not isinstance(values["unit_id"], str)
            or not 1 <= len(values["unit_id"]) <= 128
            or type(values["cutoff_week"]) is not date
            or values["cutoff_week"].weekday() != 4
            or any(
                not isinstance(values[key], str)
                or re.fullmatch(r"[0-9a-f]{64}", values[key]) is None
                for key in ("scope_digest", "payload_digest")
            )
        ):
            raise WeeklyAdjContractError("交接单元、截止周或摘要无效")
        if (
            type(values["contract_version"]) is not int
            or values["contract_version"] != policy.contract_version
        ):
            raise WeeklyAdjContractError("交接版本错误")
        if values["record_kind"] not in {
            "plan",
            "plan_correction",
            "unit",
            "batch_closed",
            "bootstrap_closed",
        }:
            raise WeeklyAdjContractError("交接记录类型错误")
        if values["outcome"] not in {
            "published",
            "source_empty_preserved",
            "partial_source_preserved",
            "no_trading_week",
        }:
            raise WeeklyAdjContractError("失败/未就绪不能作为闭合业务结果")
        counts = [
            values[n]
            for n in ("rows_received", "rows_unique", "rows_written", "rows_preserved")
        ]
        if any(type(v) is not int or v < 0 for v in counts):
            raise WeeklyAdjContractError("交接行数必须为非负整数")
        if (
            values["record_kind"] == "unit"
            and values["rows_received"] > policy.max_rows_per_unit
        ):
            raise WeeklyAdjContractError(
                "交接单元超过行数预算", "weekly_adj.row_budget_exceeded"
            )
        payload = values["payload"]
        if (
            not isinstance(payload, dict)
            or not isinstance(values["intent"], dict)
            or not isinstance(values["reason_summary"], dict)
        ):
            raise WeeklyAdjContractError("交接JSON必须为对象")
        if values["intent"].get("mode") not in {
            "scheduled_week",
            "historical_refresh",
            "manual_revision",
        }:
            raise WeeklyAdjContractError("交接意图缺失或无效")
        limit = (
            policy.max_plan_bytes
            if values["record_kind"] in {"plan", "plan_correction"}
            else policy.max_payload_bytes
        )
        if canonical_json_size(payload) > limit:
            raise WeeklyAdjContractError(
                "交接载荷超预算", "weekly_adj.row_budget_exceeded"
            )
        if values["record_kind"] == "plan_correction":
            validate_correction_payload(payload, policy)
            approved = payload["approved_plan"]
            if (values["unit_id"] != "plan_correction" or any(counts)
                    or values["outcome"] != "published"
                    or str(values["batch_id"]) != approved["batch_id"]
                    or values["scope_digest"] != approved["scope_digest"]
                    or values["cutoff_week"].isoformat() != approved["cutoff_week"]
                    or any(values[k] is not None for k in ("ts_code", "start_date", "end_date", "factor_target", "basis_date", "unit_kind"))):
                raise WeeklyAdjContractError("更正记录头与批准清单不一致")
        if values["record_kind"] == "plan" and (
            not isinstance(payload.get("units"), list)
            or len(payload["units"]) > policy.max_units
        ):
            raise WeeklyAdjContractError("冻结单元清单不完整或超量")
        if (
            values["record_kind"] == "unit"
            and not values["intent"].get("bootstrap", False)
        ):
            rows = payload.get("rows")
            if not isinstance(rows, list):
                raise WeeklyAdjContractError("日常交接必须保存标准化去重的源值")
            previous = None
            for start in range(0, len(rows), SOURCE_ROW_BLOCK_SIZE):
                block = rows[start : start + SOURCE_ROW_BLOCK_SIZE]
                if canonical_source_rows(block, policy) != block:
                    raise WeeklyAdjContractError("日常交接必须保存标准化去重的源值")
                first = (block[0]["ts_code"], block[0]["trade_date"])
                if previous is not None and previous >= first:
                    raise WeeklyAdjContractError("日常交接源键必须全局排序且不重复")
                previous = (block[-1]["ts_code"], block[-1]["trade_date"])
            if (
                len(rows) != values["rows_unique"]
                or values["rows_unique"] != values["rows_written"]
            ):
                raise WeeklyAdjContractError("交接源键、写入和载荷行数不一致")
        if values["rows_unique"] > values["rows_received"]:
            raise WeeklyAdjContractError("去重行数不能大于源端行数")
        if values["record_kind"] in {"batch_closed", "bootstrap_closed"}:
            header = payload.get("header")
            ids = payload.get("unit_ids")
            if (
                not isinstance(header, dict)
                or len(canonical_json(header).encode()) > 4096
                or not isinstance(ids, list)
                or len(ids) > policy.max_units
                or any(not isinstance(v, str) or not v or len(v) > 128 for v in ids)
                or len(set(ids)) != len(ids)
                or type(header.get("unit_count")) is not int
                or header["unit_count"] != len(ids)
                or type(header.get("total_payload_bytes")) is not int
                or not 0
                <= header["total_payload_bytes"]
                <= policy.max_batch_payload_bytes
            ):
                raise WeeklyAdjContractError("闭合批摘要、单元数量或载荷预算错误")
        samples = values["reason_summary"].get("samples", [])
        if not isinstance(samples, list) or len(samples) > 20:
            raise WeeklyAdjContractError("交接原因样本超过20项")
        if values["payload_digest"] != digest(payload):
            raise WeeklyAdjContractError("交接载荷摘要不一致")
        table = StockWeeklyAdjDelivery.__table__
        dialect = self.session.get_bind().dialect.name
        insert = (
            pg_insert
            if dialect == "postgresql"
            else sqlite_insert
            if dialect == "sqlite"
            else None
        )
        if insert is None:
            raise WeeklyAdjContractError("交接DAO仅支持PostgreSQL及隔离SQLite测试")
        payload_value = (
            cast(literal(canonical_json(payload), type_=Text), JSONB)
            if dialect == "postgresql"
            else payload
        )
        self.session.execute(
            insert(table)
            .values(**{**values, "payload": payload_value})
            .on_conflict_do_nothing(
                index_elements=["batch_id", "record_kind", "unit_id"]
            )
        )
        if dialect == "postgresql":
            model = StockWeeklyAdjDelivery
            # JSONB verifies the complete payload on the server. Do not decode
            # a second copy of all source strings merely to compare equal rows.
            existing = self.session.scalar(
                select(model)
                .where(
                    model.batch_id == values["batch_id"],
                    model.record_kind == values["record_kind"],
                    model.unit_id == values["unit_id"],
                    model.payload == payload_value,
                )
                .options(defer(model.payload, raiseload=True))
                .execution_options(populate_existing=True)
            )
            compare_keys = set(values) - {"payload"}
        else:
            existing = self.get_record(
                batch_id=values["batch_id"],
                record_kind=values["record_kind"],
                unit_id=values["unit_id"],
            )
            compare_keys = set(values)
        if existing is None or any(
            getattr(existing, key) != values[key] for key in compare_keys
        ):
            raise WeeklyAdjContractError("同批同单元已存在不同交付值")
        if dialect == "postgresql":
            set_committed_value(existing, "payload", deepcopy(payload))
        return existing

    def next_closed_header(self, *, after_revision: int):
        """Control projection only: never load payload into the sensor."""
        if type(after_revision) is not int or after_revision < 0:
            raise WeeklyAdjContractError("交付水位必须为非负整数")
        m = StockWeeklyAdjDelivery
        return (
            self.session.execute(
                select(
                    m.revision,
                    m.contract_version,
                    m.batch_id,
                    m.cutoff_week,
                    m.rows_written,
                    m.rows_preserved,
                    m.payload_digest,
                    m.scope_digest,
                    m.record_kind,
                    m.outcome,
                    m.payload["header"].label("header"),
                )
                .where(
                    m.record_kind.in_(("batch_closed", "bootstrap_closed")),
                    m.revision > after_revision,
                )
                .order_by(m.revision)
                .limit(1)
            )
            .mappings()
            .first()
        )

    def iter_units(self, *, batch_id, after_revision=0, limit=1000):
        """Stream a bounded batch; closure validation belongs to the publisher/reader."""
        if (
            type(limit) is not int
            or not 1 <= limit <= 1000
            or type(after_revision) is not int
            or after_revision < 0
        ):
            raise WeeklyAdjContractError("单批最多读取1000个单元")
        m = StockWeeklyAdjDelivery
        query = (
            select(m)
            .where(
                m.batch_id == UUID(str(batch_id)),
                m.record_kind == "unit",
                m.revision > after_revision,
            )
            .order_by(m.revision)
            .limit(limit)
            .execution_options(yield_per=1)
        )
        yield from self.session.scalars(query)
