from __future__ import annotations

from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.context.market_page_context_query import (
    MarketPageContextQuery,
)
from src.biz.queries.wealth.market.sector_analysis.sector_daily_insight_query import (
    ITEM_FIELDS,
    SUMMARY_FIELDS,
    SectorDailyInsightBatchMismatchError,
    SectorDailyInsightQuery,
)
from src.biz.schemas.wealth.market.sector_daily_insight import (
    MISSING_REASON_FIELDS,
    SectorDailyInsightDateContextDto,
    SectorDailyInsightItemDto,
    SectorDailyInsightMetaResponseDto,
    SectorDailyInsightMissingReasonDto,
    SectorDailyInsightSnapshotRequest,
    SectorDailyInsightSnapshotResponseDto,
    SectorDailyInsightSummaryDto,
    SectorDailyInsightTradeDateDto,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.contract import (
    FORMULA_BUNDLE_VERSION,
    TEMPLATE_VERSION,
)
from src.biz.services.wealth.market.sector_analysis.daily_facts.replay_planner import (
    MIN_PUBLISH_DATE,
)


def _camel(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(part[:1].upper() + part[1:] for part in rest)


class SectorDailyInsightQueryService:
    def __init__(self, *, context_query=None, query=None):
        self._context = context_query or MarketPageContextQuery()
        self._query = query or SectorDailyInsightQuery()

    def build_meta(
        self, session: Session, *, market: str = "CN_A"
    ) -> SectorDailyInsightMetaResponseDto:
        context = self._context.resolve_context(
            session, market=market, requested_trade_date=None
        )
        rows = self._query.load_coverage(session, end_date=context.trade_date)
        dates = [
            SectorDailyInsightTradeDateDto(
                tradeDate=row["trade_date"],
                availability="PUBLISHED" if row["batch_id"] else "MISSING",
                batchKey=row["batch_id"],
                hierarchyVersion=row["hierarchy_version"],
                publishedAt=row["published_at"],
            )
            for row in rows
        ]
        published = [row for row in rows if row["batch_id"] is not None]
        latest = published[-1] if published else None
        observed = latest["trade_date"] if latest else None
        delayed = observed is not None and observed < context.trade_date
        message = f"当前展示{observed.isoformat()}盘后数据" if delayed else None
        return SectorDailyInsightMetaResponseDto(
            status="EMPTY" if latest is None else "DELAYED" if delayed else "READY",
            message="暂无已发布的每日洞察。" if latest is None else message,
            exceptionCode=None,
            formulaBundleVersion=latest["formula_bundle_version"]
            if latest
            else FORMULA_BUNDLE_VERSION,
            templateVersion=latest["template_version"] if latest else TEMPLATE_VERSION,
            levels=[1, 2, 3],
            dateContext=SectorDailyInsightDateContextDto(
                requestedTradeDate=context.trade_date,
                observedTradeDate=observed,
                previousTradeDate=latest["pretrade_date"] if latest else None,
                isDelayed=delayed,
                asOf=latest["published_at"] if latest else context.generated_at,
                delayReason="目标交易日数据尚未发布。" if delayed else None,
            ),
            coverageStartDate=MIN_PUBLISH_DATE,
            coverageEndDate=context.trade_date,
            tradeDates=dates,
            defaultTradeDate=observed,
            defaultBatchKey=latest["batch_id"] if latest else None,
            hierarchyVersion=latest["hierarchy_version"] if latest else None,
        )

    def build_snapshot(
        self, session: Session, *, request: SectorDailyInsightSnapshotRequest
    ) -> SectorDailyInsightSnapshotResponseDto:
        batch = self._query.load_batch(session, trade_date=request.tradeDate)
        if batch is None or (batch["batch_id"], batch["hierarchy_version"]) != (
            request.batchKey,
            request.hierarchyVersion,
        ):
            raise SectorDailyInsightBatchMismatchError(
                "requested published batch is no longer current"
            )
        summary_row = self._query.load_summary(
            session,
            batch_id=request.batchKey,
            trade_date=request.tradeDate,
            level=request.industryLevel,
        )
        summary = SectorDailyInsightSummaryDto(
            **{_camel(key): summary_row[key] for key in SUMMARY_FIELDS}
        )
        rows = self._query.load_items(
            session,
            batch_id=request.batchKey,
            trade_date=request.tradeDate,
            level=request.industryLevel,
        )
        groups: dict[str, list[SectorDailyInsightItemDto]] = {
            key: []
            for key in ("HEAD_GAINER", "HEAD_LOSER", "STRENGTHENING", "WEAKENING")
        }
        for row in rows:
            category = row["category"]
            if (
                category not in groups
                or row["stable_order"] != len(groups[category]) + 1
            ):
                raise ValueError("published insight stable order is invalid")
            if (
                row["industry_level"] != request.industryLevel
                or row["template_version"] != batch["template_version"]
            ):
                raise ValueError("published item identity does not match its batch")
            groups[category].append(
                SectorDailyInsightItemDto(
                    **{_camel(key): row[key] for key in ITEM_FIELDS},
                    secondaryEvidenceTypes=[
                        row[key]
                        for key in (
                            "secondary_evidence_type_1",
                            "secondary_evidence_type_2",
                        )
                        if row[key] is not None
                    ],
                )
            )
        reasons = [
            SectorDailyInsightMissingReasonDto(
                reasonCode=code, count=getattr(summary, field)
            )
            for code, field in MISSING_REASON_FIELDS
            if getattr(summary, field)
        ]
        has_facts = bool(
            summary.calculableCount
            or any(groups.values())
            or summary.dualMomentumCount20d80
            or summary.leadingImprovingCount20d5d
            or summary.priceVolumeJointCount20d
            or summary.breadthUpShareAbove50Count
        )
        return SectorDailyInsightSnapshotResponseDto(
            status="READY" if has_facts else "EMPTY",
            message=None if has_facts else "当前层级暂无可展示的行业事实。",
            exceptionCode=None,
            requestedTradeDate=request.tradeDate,
            observedTradeDate=batch["trade_date"],
            previousTradeDate=batch["previous_trade_date"],
            batchKey=batch["batch_id"],
            hierarchyVersion=batch["hierarchy_version"],
            formulaBundleVersion=batch["formula_bundle_version"],
            templateVersion=batch["template_version"],
            publishedAt=batch["published_at"],
            calculatedAt=batch["calculated_at"],
            industryLevel=request.industryLevel,
            summary=summary,
            headGainers=groups["HEAD_GAINER"],
            headLosers=groups["HEAD_LOSER"],
            strengthening=groups["STRENGTHENING"],
            weakening=groups["WEAKENING"],
            missingSectorCount=summary.missingCount,
            missingReasonCounts=reasons,
        )
