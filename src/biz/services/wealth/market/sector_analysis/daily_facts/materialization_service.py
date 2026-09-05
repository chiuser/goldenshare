from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Callable
from uuid import uuid4

from sqlalchemy.orm import Session

from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    FORMULA_BUNDLE_VERSION,
    TEMPLATE_VERSION,
    BuiltDailyFacts,
    DailyFactsMaterializationResult,
    DailyFactsPreview,
    SectorAnalysisDailyFactsPlanDriftError,
    SectorAnalysisDailyFactsReadbackError,
    canonical_json_hash,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.fact_builder import (
    SectorAnalysisDailyFactBuilder,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.insight_builder import (
    SectorDailyInsightBuilder,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.repository import (
    SectorAnalysisDailyFactsRepository,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.source_query import (
    SectorAnalysisDailyFactsSourceQuery,
)


class SectorAnalysisDailyFactsMaterializationService:
    def __init__(
        self,
        *,
        session_factory=None,  # type: ignore[no-untyped-def]
        source_query: SectorAnalysisDailyFactsSourceQuery | None = None,
        fact_builder: SectorAnalysisDailyFactBuilder | None = None,
        insight_builder: SectorDailyInsightBuilder | None = None,
        repository: SectorAnalysisDailyFactsRepository | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._source_query = source_query or SectorAnalysisDailyFactsSourceQuery()
        self._fact_builder = fact_builder or SectorAnalysisDailyFactBuilder()
        self._insight_builder = insight_builder or SectorDailyInsightBuilder()
        self._repository = repository or SectorAnalysisDailyFactsRepository()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def preview_trade_date(
        self,
        session: Session,
        *,
        trade_date: date,
        cancel_check: Callable[[], None] | None = None,
        phase_update: Callable[[str], None] | None = None,
    ) -> DailyFactsPreview:
        facts = self._build(
            session,
            trade_date=trade_date,
            cancel_check=cancel_check,
            phase_update=phase_update,
        )
        return self._preview(facts)

    def materialize_trade_date(
        self,
        *,
        trade_date: date,
        expected_source_hash: str | None = None,
        expected_plan_hash: str | None = None,
        expected_content_hash: str | None = None,
        expected_hierarchy_version: str | None = None,
        cancel_check: Callable[[], None] | None = None,
        phase_update: Callable[[str], None] | None = None,
    ) -> DailyFactsMaterializationResult:
        if self._session_factory is None:
            raise RuntimeError("daily facts materialization requires a session factory")
        expected_hashes = (
            expected_source_hash,
            expected_plan_hash,
            expected_content_hash,
        )
        if any(value is not None for value in expected_hashes) and not all(
            value is not None for value in expected_hashes
        ):
            raise ValueError("source/plan/content expected hashes must be provided together")
        with self._session_factory() as source_session:
            facts = self._build(
                source_session,
                trade_date=trade_date,
                cancel_check=cancel_check,
                phase_update=phase_update,
            )
            preview = self._preview(facts)
            source_session.rollback()
        self._check_cancel(cancel_check)
        if expected_hierarchy_version is not None and (
            preview.hierarchy_version != expected_hierarchy_version
        ):
            raise SectorAnalysisDailyFactsPlanDriftError(
                "输入审计与执行时的层级版本不一致"
            )
        if expected_source_hash is not None and (
            preview.source_hash != expected_source_hash
            or preview.plan_hash != expected_plan_hash
            or preview.content_hash != expected_content_hash
        ):
            raise SectorAnalysisDailyFactsPlanDriftError("readiness与执行时的source/plan/content hash不一致")

        self._update_phase(phase_update, "WRITING_FACTS")
        self._check_cancel(cancel_check)
        batch_id = uuid4()
        calculated_at = self._clock()
        with self._session_factory() as session:
            with session.begin():
                successful = self._repository.find_successful_batch(
                    session,
                    trade_date=facts.trade_date,
                    plan_hash=preview.plan_hash,
                    content_hash=preview.content_hash,
                )
                if successful is not None:
                    if successful.status != "PUBLISHED":
                        raise SectorAnalysisDailyFactsPlanDriftError(
                            "本次内容只存在于已被替换的历史batch，禁止静默回退当前事实"
                        )
                    self._repository.readback_published(
                        session,
                        batch_id=successful.batch_id,
                        expected=facts,
                    )
                    return DailyFactsMaterializationResult(
                        trade_date=trade_date,
                        batch_id=successful.batch_id,
                        status="IDEMPOTENT",
                        rows_saved=0,
                        plan_hash=preview.plan_hash,
                        content_hash=preview.content_hash,
                        idempotent=True,
                    )
                self._repository.validate_previous_binding(session, facts=facts)
                self._repository.write_building_batch(
                    session,
                    batch_id=batch_id,
                    facts=facts,
                    plan_hash=preview.plan_hash,
                    calculated_at=calculated_at,
                )

        try:
            self._update_phase(phase_update, "READING_BACK")
            with self._session_factory() as session:
                with session.begin():
                    self._repository.readback(session, batch_id=batch_id, expected=facts)
        except Exception as exc:
            with self._session_factory() as failure_session:
                with failure_session.begin():
                    self._repository.mark_failed(
                        failure_session,
                        batch_id=batch_id,
                        reason_code="SA_DAILY_FACT_READBACK_MISMATCH",
                        now=self._clock(),
                    )
            if isinstance(exc, SectorAnalysisDailyFactsReadbackError):
                raise
            raise SectorAnalysisDailyFactsReadbackError("每日事实read-back失败") from exc

        self._update_phase(phase_update, "PUBLISHING")
        with self._session_factory() as session:
            with session.begin():
                status, idempotent = self._repository.publish(
                    session,
                    batch_id=batch_id,
                    now=self._clock(),
                )
        return DailyFactsMaterializationResult(
            trade_date=trade_date,
            batch_id=batch_id,
            status=status,
            rows_saved=0 if idempotent else sum(facts.fact_counts.values()),
            plan_hash=preview.plan_hash,
            content_hash=preview.content_hash,
            idempotent=idempotent,
        )

    def _build(
        self,
        session: Session,
        *,
        trade_date: date,
        cancel_check: Callable[[], None] | None = None,
        phase_update: Callable[[str], None] | None = None,
    ) -> BuiltDailyFacts:
        self._update_phase(phase_update, "READING_SOURCE")
        bundle = self._source_query.load_bundle(
            session,
            trade_date=trade_date,
            cancel_check=cancel_check,
        )
        self._check_cancel(cancel_check)
        self._update_phase(phase_update, "CALCULATING_FACTS")
        methods = self._fact_builder.build(bundle)
        self._check_cancel(cancel_check)
        previous = self._repository.load_previous_evidence(
            session,
            trade_date=bundle.previous_trade_date,
            hierarchy_version=bundle.hierarchy.baseline_version,
        )
        self._check_cancel(cancel_check)
        self._update_phase(phase_update, "BUILDING_INSIGHT")
        summaries, items = self._insight_builder.build(
            bundle=bundle,
            facts=methods,
            previous=previous,
        )
        self._check_cancel(cancel_check)
        provisional = BuiltDailyFacts(
            trade_date=bundle.trade_date,
            previous_trade_date=bundle.previous_trade_date,
            previous_batch_id=previous.batch_id if previous else None,
            hierarchy_version=bundle.hierarchy.baseline_version,
            source_hash=bundle.source_hash,
            source_dates=bundle.source_dates,
            source_row_counts=bundle.source_row_counts,
            momentum=methods.momentum,
            dual_momentum=methods.dual_momentum,
            relative_rotation=methods.relative_rotation,
            member_breadth=methods.member_breadth,
            member_ma_breadth=methods.member_ma_breadth,
            price_volume=methods.price_volume,
            insight_summaries=summaries,
            insight_items=items,
            content_hash="",
        )
        content_hash = self._repository.content_hash_from_records(
            self._repository.records_for_facts(provisional)
        )
        self._check_cancel(cancel_check)
        return replace(provisional, content_hash=content_hash)

    @staticmethod
    def _check_cancel(cancel_check: Callable[[], None] | None) -> None:
        if cancel_check is not None:
            cancel_check()

    @staticmethod
    def _update_phase(phase_update: Callable[[str], None] | None, phase: str) -> None:
        if phase_update is not None:
            phase_update(phase)

    @staticmethod
    def _preview(facts: BuiltDailyFacts) -> DailyFactsPreview:
        plan_hash = canonical_json_hash(
            {
                "tradeDate": facts.trade_date,
                "previousTradeDate": facts.previous_trade_date,
                "previousBatchId": facts.previous_batch_id,
                "hierarchyVersion": facts.hierarchy_version,
                "formulaBundleVersion": FORMULA_BUNDLE_VERSION,
                "templateVersion": TEMPLATE_VERSION,
                "sourceHash": facts.source_hash,
                "contentHash": facts.content_hash,
                "expectedFactCounts": facts.fact_counts,
            }
        )
        missing_counts: dict[str, int] = {}
        for summary in facts.insight_summaries:
            for key, value in summary.values.items():
                if key.startswith("missing_") and isinstance(value, int):
                    missing_counts[key] = missing_counts.get(key, 0) + value
        return DailyFactsPreview(
            trade_date=facts.trade_date,
            hierarchy_version=facts.hierarchy_version,
            source_hash=facts.source_hash,
            plan_hash=plan_hash,
            content_hash=facts.content_hash,
            source_dates=facts.source_dates,
            source_row_counts=facts.source_row_counts,
            expected_fact_counts=facts.fact_counts,
            missing_counts=missing_counts,
            finite_summary={
                "methodRows": sum(facts.fact_counts[name] for name in facts.fact_counts if name not in {"wealth_sector_analysis_publish_batch", "wealth_sector_daily_insight_summary", "wealth_sector_daily_insight_item"}),
                "summaryRows": len(facts.insight_summaries),
                "itemRows": len(facts.insight_items),
            },
        )
