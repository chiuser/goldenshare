from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import Numeric, select
from sqlalchemy.orm import Session

from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    BuiltDailyFacts,
    FORMULA_BUNDLE_VERSION,
    TEMPLATE_VERSION,
    PreviousPublishedEvidence,
    PreviousSectorEvidence,
    SectorAnalysisDailyFactsPlanDriftError,
    SectorAnalysisDailyFactsReadbackError,
    canonical_json_hash,
)
from src.biz.services.wealth.market.sector_analysis.sector_dual_momentum_contract import FORMULA_KEY as DUAL_FORMULA_KEY, FORMULA_VERSION as DUAL_FORMULA_VERSION
from src.biz.services.wealth.market.sector_analysis.sector_member_breadth_contract import MEMBER_BREADTH_FORMULA_KEY, MEMBER_BREADTH_FORMULA_VERSION
from src.biz.services.wealth.market.sector_analysis.sector_momentum_contract import FORMULA_KEY as MOMENTUM_FORMULA_KEY, FORMULA_VERSION as MOMENTUM_FORMULA_VERSION
from src.biz.services.wealth.market.sector_analysis.sector_price_volume_contract import FORMULA_KEY as PRICE_VOLUME_FORMULA_KEY, FORMULA_VERSION as PRICE_VOLUME_FORMULA_VERSION
from src.biz.services.wealth.market.sector_analysis.sector_relative_rotation_contract import FORMULA_KEY as ROTATION_FORMULA_KEY, FORMULA_VERSION as ROTATION_FORMULA_VERSION
from src.foundation.models.core_serving.wealth_sector_analysis_publish_batch import WealthSectorAnalysisPublishBatch
from src.foundation.models.core_serving.wealth_sector_daily_insight_item import WealthSectorDailyInsightItem
from src.foundation.models.core_serving.wealth_sector_daily_insight_summary import WealthSectorDailyInsightSummary
from src.foundation.models.core_serving.wealth_sector_dual_momentum_daily import WealthSectorDualMomentumDaily
from src.foundation.models.core_serving.wealth_sector_member_breadth_daily import WealthSectorMemberBreadthDaily
from src.foundation.models.core_serving.wealth_sector_member_ma_breadth_daily import WealthSectorMemberMaBreadthDaily
from src.foundation.models.core_serving.wealth_sector_momentum_daily import WealthSectorMomentumDaily
from src.foundation.models.core_serving.wealth_sector_price_volume_daily import WealthSectorPriceVolumeDaily
from src.foundation.models.core_serving.wealth_sector_relative_rotation_daily import WealthSectorRelativeRotationDaily


_CHILD_MODELS = (
    WealthSectorMomentumDaily,
    WealthSectorDualMomentumDaily,
    WealthSectorRelativeRotationDaily,
    WealthSectorMemberBreadthDaily,
    WealthSectorMemberMaBreadthDaily,
    WealthSectorPriceVolumeDaily,
    WealthSectorDailyInsightSummary,
    WealthSectorDailyInsightItem,
)
_MODEL_BY_TABLE = {model.__tablename__: model for model in _CHILD_MODELS}


class SectorAnalysisDailyFactsRepository:
    def find_successful_batch(
        self,
        session: Session,
        *,
        trade_date: date,
        plan_hash: str,
        content_hash: str,
    ) -> WealthSectorAnalysisPublishBatch | None:
        return session.scalar(
            select(WealthSectorAnalysisPublishBatch).where(
                WealthSectorAnalysisPublishBatch.trade_date == trade_date,
                WealthSectorAnalysisPublishBatch.plan_hash == plan_hash,
                WealthSectorAnalysisPublishBatch.content_hash == content_hash,
                WealthSectorAnalysisPublishBatch.status.in_(("PUBLISHED", "SUPERSEDED")),
            )
        )

    def validate_previous_binding(self, session: Session, *, facts: BuiltDailyFacts) -> None:
        current = session.scalar(
            select(WealthSectorAnalysisPublishBatch).where(
                WealthSectorAnalysisPublishBatch.trade_date == facts.previous_trade_date,
                WealthSectorAnalysisPublishBatch.status == "PUBLISHED",
                WealthSectorAnalysisPublishBatch.hierarchy_version == facts.hierarchy_version,
                WealthSectorAnalysisPublishBatch.formula_bundle_version == FORMULA_BUNDLE_VERSION,
            )
        )
        current_id = current.batch_id if current is not None else None
        if current_id != facts.previous_batch_id:
            raise SectorAnalysisDailyFactsPlanDriftError("前一交易日PUBLISHED batch已变化")

    def load_previous_evidence(
        self,
        session: Session,
        *,
        trade_date: date,
        hierarchy_version: str,
    ) -> PreviousPublishedEvidence | None:
        batch = session.scalar(
            select(WealthSectorAnalysisPublishBatch).where(
                WealthSectorAnalysisPublishBatch.trade_date == trade_date,
                WealthSectorAnalysisPublishBatch.status == "PUBLISHED",
                WealthSectorAnalysisPublishBatch.hierarchy_version == hierarchy_version,
                WealthSectorAnalysisPublishBatch.formula_bundle_version == FORMULA_BUNDLE_VERSION,
            )
        )
        if batch is None:
            return None
        momentum = {
            row.sector_code: row
            for row in session.scalars(
                select(WealthSectorMomentumDaily).where(
                    WealthSectorMomentumDaily.batch_id == batch.batch_id,
                    WealthSectorMomentumDaily.period == 20,
                    WealthSectorMomentumDaily.comparison_scope.in_(("LEVEL_1", "LEVEL_2", "LEVEL_3")),
                )
            )
        }
        dual = self._by_code(session, WealthSectorDualMomentumDaily, batch.batch_id, period=20)
        rotation = self._by_code(session, WealthSectorRelativeRotationDaily, batch.batch_id, period=20)
        breadth = self._by_code(session, WealthSectorMemberBreadthDaily, batch.batch_id)
        ma20 = self._by_code(session, WealthSectorMemberMaBreadthDaily, batch.batch_id, ma_period=20)
        price_volume = self._by_code(session, WealthSectorPriceVolumeDaily, batch.batch_id, period=20)
        by_sector = {
            code: PreviousSectorEvidence(
                sector_code=code,
                rank_20d=row.strength_rank,
                rankable_count_20d=row.rankable_count,
                percentile_20d=row.percentile,
                price_volume_state=price_volume.get(code).distribution_state if code in price_volume else None,
                dual_qualification_20d_80=dual.get(code).qualification_status_80 if code in dual else None,
                rotation_status_20d=rotation.get(code).rotation_status if code in rotation else None,
                member_up_pct=breadth.get(code).member_up_pct if code in breadth else None,
                turnover_up_pct=breadth.get(code).turnover_up_pct if code in breadth else None,
                ma20_above_pct=ma20.get(code).above_pct if code in ma20 else None,
                member_qualification=breadth.get(code).member_qualification if code in breadth else None,
                turnover_qualification=breadth.get(code).turnover_qualification if code in breadth else None,
                ma20_qualification=ma20.get(code).qualification if code in ma20 else None,
            )
            for code, row in momentum.items()
        }
        return PreviousPublishedEvidence(
            batch_id=batch.batch_id,
            trade_date=batch.trade_date,
            hierarchy_version=batch.hierarchy_version,
            formula_bundle_version=batch.formula_bundle_version,
            by_sector=by_sector,
        )

    @staticmethod
    def _by_code(session: Session, model, batch_id: UUID, **filters):  # type: ignore[no-untyped-def]
        conditions = [model.batch_id == batch_id, model.comparison_scope.in_(("LEVEL_1", "LEVEL_2", "LEVEL_3"))]
        conditions.extend(getattr(model, key) == value for key, value in filters.items())
        return {row.sector_code: row for row in session.scalars(select(model).where(*conditions))}

    def write_building_batch(
        self,
        session: Session,
        *,
        batch_id: UUID,
        facts: BuiltDailyFacts,
        plan_hash: str,
        calculated_at: datetime,
    ) -> None:
        counts = facts.fact_counts
        session.add(
            WealthSectorAnalysisPublishBatch(
                batch_id=batch_id,
                trade_date=facts.trade_date,
                status="BUILDING",
                previous_trade_date=facts.previous_trade_date,
                previous_batch_id=facts.previous_batch_id,
                hierarchy_version=facts.hierarchy_version,
                formula_bundle_version=FORMULA_BUNDLE_VERSION,
                template_version=TEMPLATE_VERSION,
                source_hash=facts.source_hash,
                plan_hash=plan_hash,
                content_hash=facts.content_hash,
                source_dates_json=dict(facts.source_dates),
                source_row_counts_json=dict(facts.source_row_counts),
                expected_fact_counts_json=counts,
                actual_fact_counts_json={},
                started_at=calculated_at,
                calculated_at=calculated_at,
            )
        )
        records = self.records_for_facts(facts)
        for model in _CHILD_MODELS:
            rows = records[model.__tablename__]
            session.add_all(
                model(batch_id=batch_id, calculated_at=calculated_at, **row)
                if "calculated_at" in model.__table__.columns
                else model(batch_id=batch_id, **row)
                for row in rows
            )

    def readback(self, session: Session, *, batch_id: UUID, expected: BuiltDailyFacts) -> dict[str, int]:
        batch = session.get(WealthSectorAnalysisPublishBatch, batch_id)
        if batch is None or batch.trade_date != expected.trade_date or batch.status != "BUILDING":
            raise SectorAnalysisDailyFactsReadbackError("BUILDING batch身份不一致")
        actual_counts = {"wealth_sector_analysis_publish_batch": 1}
        payload: dict[str, list[dict[str, Any]]] = {}
        for model in _CHILD_MODELS:
            name = model.__tablename__
            rows = tuple(session.scalars(select(model).where(model.batch_id == batch_id)))
            actual_counts[name] = len(rows)
            payload[name] = [self._model_content_record(row) for row in rows]
        if actual_counts != expected.fact_counts:
            raise SectorAnalysisDailyFactsReadbackError(
                f"逐表计数不一致 expected={expected.fact_counts}, actual={actual_counts}"
            )
        if self.content_hash_from_records(payload) != expected.content_hash:
            raise SectorAnalysisDailyFactsReadbackError("逐表内容hash不一致")
        batch.actual_fact_counts_json = actual_counts
        return actual_counts

    def publish(self, session: Session, *, batch_id: UUID, now: datetime) -> tuple[str, bool]:
        new_batch = session.scalar(
            select(WealthSectorAnalysisPublishBatch)
            .where(WealthSectorAnalysisPublishBatch.batch_id == batch_id)
            .with_for_update()
        )
        if new_batch is None or new_batch.status != "BUILDING":
            raise SectorAnalysisDailyFactsReadbackError("待发布batch不存在或状态非法")
        successful = session.scalar(
            select(WealthSectorAnalysisPublishBatch)
            .where(
                WealthSectorAnalysisPublishBatch.trade_date == new_batch.trade_date,
                WealthSectorAnalysisPublishBatch.plan_hash == new_batch.plan_hash,
                WealthSectorAnalysisPublishBatch.content_hash == new_batch.content_hash,
                WealthSectorAnalysisPublishBatch.status == "PUBLISHED",
            )
            .with_for_update()
        )
        if successful is not None:
            new_batch.status = "FAILED"
            new_batch.failed_at = now
            new_batch.failure_reason_code = "IDEMPOTENT_CONTENT_ALREADY_PUBLISHED"
            return "IDEMPOTENT", True
        current = session.scalar(
            select(WealthSectorAnalysisPublishBatch)
            .where(
                WealthSectorAnalysisPublishBatch.trade_date == new_batch.trade_date,
                WealthSectorAnalysisPublishBatch.status == "PUBLISHED",
            )
            .with_for_update()
        )
        if current is not None:
            current.status = "SUPERSEDED"
            current.superseded_at = now
            session.flush()
        new_batch.status = "PUBLISHED"
        new_batch.published_at = now
        return "PUBLISHED", False

    @staticmethod
    def mark_failed(session: Session, *, batch_id: UUID, reason_code: str, now: datetime) -> None:
        batch = session.get(WealthSectorAnalysisPublishBatch, batch_id)
        if batch is not None and batch.status == "BUILDING":
            batch.status = "FAILED"
            batch.failed_at = now
            batch.failure_reason_code = reason_code

    @staticmethod
    def records_for_facts(facts: BuiltDailyFacts) -> dict[str, list[dict[str, Any]]]:
        def identity(row) -> dict[str, Any]:  # type: ignore[no-untyped-def]
            return asdict(row.identity)
        records: dict[str, list[dict[str, Any]]] = {
            "wealth_sector_momentum_daily": [
                {**identity(row), **{key: value for key, value in asdict(row).items() if key != "identity"}, "formula_key": MOMENTUM_FORMULA_KEY, "formula_version": MOMENTUM_FORMULA_VERSION}
                for row in facts.momentum
            ],
            "wealth_sector_dual_momentum_daily": [
                {**identity(row), **{key: value for key, value in asdict(row).items() if key != "identity"}, "formula_key": DUAL_FORMULA_KEY, "formula_version": DUAL_FORMULA_VERSION}
                for row in facts.dual_momentum
            ],
            "wealth_sector_relative_rotation_daily": [
                {**identity(row), **{key: value for key, value in asdict(row).items() if key != "identity"}, "formula_key": ROTATION_FORMULA_KEY, "formula_version": ROTATION_FORMULA_VERSION}
                for row in facts.relative_rotation
            ],
            "wealth_sector_member_breadth_daily": [
                {**identity(row), **dict(row.values), "calculation_status": row.calculation_status, "missing_reason": row.missing_reason, "formula_key": MEMBER_BREADTH_FORMULA_KEY, "formula_version": MEMBER_BREADTH_FORMULA_VERSION}
                for row in facts.member_breadth
            ],
            "wealth_sector_member_ma_breadth_daily": [
                {**identity(row), "ma_period": row.ma_period, **dict(row.values), "calculation_status": row.calculation_status, "missing_reason": row.missing_reason, "formula_key": MEMBER_BREADTH_FORMULA_KEY, "formula_version": MEMBER_BREADTH_FORMULA_VERSION}
                for row in facts.member_ma_breadth
            ],
            "wealth_sector_price_volume_daily": [
                {**identity(row), "period": row.period, **dict(row.values), "calculation_status": row.calculation_status, "missing_reason": row.missing_reason, "formula_key": PRICE_VOLUME_FORMULA_KEY, "formula_version": PRICE_VOLUME_FORMULA_VERSION}
                for row in facts.price_volume
            ],
            "wealth_sector_daily_insight_summary": [
                {"trade_date": row.trade_date, "industry_level": row.industry_level, **dict(row.values)}
                for row in facts.insight_summaries
            ],
            "wealth_sector_daily_insight_item": [
                {"trade_date": row.trade_date, "industry_level": row.industry_level, "category": row.category, "sector_code": row.sector_code, **dict(row.values)}
                for row in facts.insight_items
            ],
        }
        return {
            table: [SectorAnalysisDailyFactsRepository._normalize_record(_MODEL_BY_TABLE[table], row) for row in rows]
            for table, rows in records.items()
        }

    @staticmethod
    def content_hash_from_records(records: Mapping[str, list[dict[str, Any]]]) -> str:
        normalized = {
            table: sorted(rows, key=lambda row: str(canonical_json_hash(row)))
            for table, rows in sorted(records.items())
        }
        return canonical_json_hash(normalized)

    @staticmethod
    def _model_content_record(row) -> dict[str, Any]:  # type: ignore[no-untyped-def]
        return {
            column.name: getattr(row, column.name)
            for column in row.__table__.columns
            if column.name not in {"batch_id", "calculated_at"}
        }

    @staticmethod
    def _normalize_record(model, record: Mapping[str, Any]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
        normalized: dict[str, Any] = {}
        for key, value in record.items():
            column = model.__table__.columns[key]
            if isinstance(value, Decimal) and isinstance(column.type, Numeric) and column.type.scale is not None:
                quantum = Decimal(1).scaleb(-column.type.scale)
                normalized[key] = value.quantize(quantum, rounding=ROUND_HALF_UP)
            else:
                normalized[key] = value
        return normalized
