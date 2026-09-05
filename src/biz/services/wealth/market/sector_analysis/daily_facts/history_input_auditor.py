from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.biz.queries.wealth.market.common.sector_hierarchy_query import (
    SectorHierarchyQuery,
    SectorHierarchyUnavailableError,
)
from src.foundation.models.core.trade_calendar import TradeCalendar

from .contract import (
    FORMULA_BUNDLE_VERSION,
    HISTORY_INPUT_AUDIT_CONTRACT_VERSION,
    PLAN_DRIFT,
    SOURCE_NOT_READY,
    TEMPLATE_VERSION,
    HistorySourceCoverage,
    SectorAnalysisDailyFactsSourceNotReadyError,
    canonical_json_hash,
)
from .replay_planner import MIN_PUBLISH_DATE
from .source_query import (
    SectorAnalysisDailyFactsSourceQuery,
    ensure_repeatable_read_only_transaction,
)


TARGET_TABLES = (
    "core_serving.wealth_sector_analysis_publish_batch",
    "core_serving.wealth_sector_momentum_daily",
    "core_serving.wealth_sector_dual_momentum_daily",
    "core_serving.wealth_sector_relative_rotation_daily",
    "core_serving.wealth_sector_member_breadth_daily",
    "core_serving.wealth_sector_member_ma_breadth_daily",
    "core_serving.wealth_sector_price_volume_daily",
    "core_serving.wealth_sector_daily_insight_summary",
    "core_serving.wealth_sector_daily_insight_item",
)


@dataclass(frozen=True, slots=True)
class HistoryInputAuditIssue:
    code: str
    source: str
    message: str
    blocking: bool
    count: int = 0
    samples: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "source": self.source,
            "message": self.message,
            "blocking": self.blocking,
            "count": self.count,
            "samples": list(self.samples),
        }


@dataclass(frozen=True, slots=True)
class SectorAnalysisHistoryInputAudit:
    requested_start_date: date
    requested_end_date: date
    effective_start_date: date | None
    effective_end_date: date | None
    warmup_start_date: date | None
    ordered_trade_dates: tuple[date, ...]
    hierarchy_version: str | None
    source_coverage: tuple[HistorySourceCoverage, ...]
    issues: tuple[HistoryInputAuditIssue, ...]
    audit_hash: str

    @property
    def state(self) -> str:
        return "BLOCKED" if any(issue.blocking for issue in self.issues) else "AUDIT_PASSED"

    @property
    def apply_ready(self) -> bool:
        return self.state == "AUDIT_PASSED"

    def metadata(self) -> dict[str, Any]:
        return {
            "audit_contract_version": HISTORY_INPUT_AUDIT_CONTRACT_VERSION,
            "audit_state": self.state,
            "requested_start_date": self.requested_start_date.isoformat(),
            "requested_end_date": self.requested_end_date.isoformat(),
            "effective_start_date": (
                self.effective_start_date.isoformat() if self.effective_start_date else None
            ),
            "effective_end_date": (
                self.effective_end_date.isoformat() if self.effective_end_date else None
            ),
            "warmup_start_date": (
                self.warmup_start_date.isoformat() if self.warmup_start_date else None
            ),
            "ordered_trade_dates": [item.isoformat() for item in self.ordered_trade_dates],
            "trade_dates_hash": canonical_json_hash(self.ordered_trade_dates),
            "hierarchy_version": self.hierarchy_version,
            "formula_bundle_version": FORMULA_BUNDLE_VERSION,
            "template_version": TEMPLATE_VERSION,
            "target_tables": list(TARGET_TABLES),
            "source_coverage_summary": {
                coverage.source: {
                    "row_count": coverage.row_count,
                    "covered_date_count": len(coverage.covered_dates),
                    "daily_row_counts": {
                        trade_date.isoformat(): row_count
                        for trade_date, row_count in coverage.daily_row_counts
                    },
                    "missing_dates": [item.isoformat() for item in coverage.missing_dates],
                    "duplicate_key_count": coverage.duplicate_key_count,
                    "illegal_date_count": coverage.illegal_date_count,
                    "invalid_value_count": coverage.invalid_value_count,
                    "missing_value_count": coverage.missing_value_count,
                }
                for coverage in self.source_coverage
            },
            "audit_issues": [issue.as_dict() for issue in self.issues],
            "audit_hash": self.audit_hash,
        }


class SectorAnalysisHistoryInputAuditor:
    AUDIT_TOTAL = 6

    def __init__(
        self,
        *,
        source_query: SectorAnalysisDailyFactsSourceQuery | None = None,
        hierarchy_query: SectorHierarchyQuery | None = None,
    ) -> None:
        self._source_query = source_query or SectorAnalysisDailyFactsSourceQuery()
        self._hierarchy_query = hierarchy_query or SectorHierarchyQuery()

    def audit(
        self,
        session: Session,
        *,
        start_date: date,
        end_date: date,
        cancel_check: Callable[[], None] | None = None,
        progress_update: Callable[[int, int, str], None] | None = None,
    ) -> SectorAnalysisHistoryInputAudit:
        if start_date > end_date:
            raise ValueError("start_date must not be later than end_date")
        ensure_repeatable_read_only_transaction(session)
        issues: list[HistoryInputAuditIssue] = []
        coverage: list[HistorySourceCoverage] = []

        self._progress(progress_update, done=0, item="trade_calendar")
        self._check_cancel(cancel_check)
        target_dates = tuple(
            session.scalars(
                select(TradeCalendar.trade_date)
                .where(
                    TradeCalendar.exchange == "SSE",
                    TradeCalendar.is_open.is_(True),
                    TradeCalendar.trade_date >= max(start_date, MIN_PUBLISH_DATE),
                    TradeCalendar.trade_date <= end_date,
                )
                .order_by(TradeCalendar.trade_date)
            )
        )
        self._check_cancel(cancel_check)
        if not target_dates:
            issues.append(
                HistoryInputAuditIssue(
                    code=SOURCE_NOT_READY,
                    source="trade_calendar",
                    message="目标范围内没有SSE开市日",
                    blocking=True,
                )
            )
            self._progress(progress_update, done=1, item="trade_calendar")
            return self._result(
                start_date=start_date,
                end_date=end_date,
                target_dates=(),
                warmup_dates=(),
                hierarchy_version=None,
                coverage=(),
                issues=tuple(issues),
            )

        warmup_dates = tuple(
            reversed(
                tuple(
                    session.scalars(
                        select(TradeCalendar.trade_date)
                        .where(
                            TradeCalendar.exchange == "SSE",
                            TradeCalendar.is_open.is_(True),
                            TradeCalendar.trade_date <= target_dates[0],
                        )
                        .order_by(TradeCalendar.trade_date.desc())
                        .limit(SectorAnalysisDailyFactsSourceQuery.WINDOW_SIZE)
                    )
                )
            )
        )
        self._check_cancel(cancel_check)
        if (
            len(warmup_dates) != SectorAnalysisDailyFactsSourceQuery.WINDOW_SIZE
            or warmup_dates[-1] != target_dates[0]
        ):
            issues.append(
                HistoryInputAuditIssue(
                    code=SOURCE_NOT_READY,
                    source="trade_calendar",
                    message="首个目标日缺少完整60个SSE交易日预热窗口",
                    blocking=True,
                    count=max(
                        SectorAnalysisDailyFactsSourceQuery.WINDOW_SIZE - len(warmup_dates),
                        0,
                    ),
                )
            )
        all_open_dates = warmup_dates[:-1] + target_dates
        coverage.append(
            HistorySourceCoverage(
                source="trade_calendar",
                row_count=len(all_open_dates),
                covered_dates=all_open_dates,
                daily_row_counts=tuple((item, 1) for item in all_open_dates),
                missing_dates=(),
                duplicate_key_count=0,
                illegal_date_count=0,
                invalid_value_count=0,
                missing_value_count=0,
            )
        )
        self._progress(progress_update, done=1, item="trade_calendar")

        self._progress(progress_update, done=1, item="wealth_sector_hierarchy")
        self._check_cancel(cancel_check)
        try:
            hierarchy = self._hierarchy_query.load(session)
            pools = self._source_query._comparison_pools(hierarchy)
            required_scopes = {
                "LEVEL_1",
                "LEVEL_2",
                "LEVEL_3",
                "LEVEL_1_CHILDREN",
                "LEVEL_2_CHILDREN",
            }
            if not required_scopes.issubset({pool.scope for pool in pools}):
                raise SectorHierarchyUnavailableError("industry hierarchy comparison pools incomplete")
        except (
            SectorHierarchyUnavailableError,
            SectorAnalysisDailyFactsSourceNotReadyError,
        ) as exc:
            issues.append(
                HistoryInputAuditIssue(
                    code=PLAN_DRIFT,
                    source="wealth_sector_hierarchy",
                    message=str(exc),
                    blocking=True,
                )
            )
            self._progress(progress_update, done=2, item="wealth_sector_hierarchy")
            return self._result(
                start_date=start_date,
                end_date=end_date,
                target_dates=target_dates,
                warmup_dates=warmup_dates,
                hierarchy_version=None,
                coverage=tuple(coverage),
                issues=tuple(issues),
            )
        self._check_cancel(cancel_check)
        coverage.append(
            HistorySourceCoverage(
                source="wealth_sector_hierarchy",
                row_count=len(hierarchy.nodes),
                covered_dates=(),
                daily_row_counts=(),
                missing_dates=(),
                duplicate_key_count=0,
                illegal_date_count=0,
                invalid_value_count=0,
                missing_value_count=0,
            )
        )
        self._progress(progress_update, done=2, item="wealth_sector_hierarchy")

        sector_codes = tuple(node.sector_code for node in hierarchy.nodes)
        source_audits = (
            ("dc_daily", self._source_query.audit_dc_daily),
            ("dc_member", self._source_query.audit_dc_member),
            ("equity_daily_bar", self._source_query.audit_equity_daily_bar),
            ("equity_adj_factor", self._source_query.audit_equity_adj_factor),
        )
        for index, (source, audit_source) in enumerate(source_audits, start=3):
            self._progress(progress_update, done=index - 1, item=source)
            current = audit_source(
                session,
                open_dates=all_open_dates,
                sector_codes=sector_codes,
                cancel_check=cancel_check,
            )
            coverage.append(current)
            issues.extend(self._coverage_issues(current))
            self._progress(progress_update, done=index, item=source)

        return self._result(
            start_date=start_date,
            end_date=end_date,
            target_dates=target_dates,
            warmup_dates=warmup_dates,
            hierarchy_version=hierarchy.baseline_version,
            coverage=tuple(coverage),
            issues=tuple(issues),
        )

    @staticmethod
    def _coverage_issues(coverage: HistorySourceCoverage) -> tuple[HistoryInputAuditIssue, ...]:
        issues: list[HistoryInputAuditIssue] = []
        checks = (
            (
                coverage.row_count == 0,
                "联合窗口来源为空",
                coverage.row_count,
                (),
            ),
            (
                bool(coverage.missing_dates),
                "存在整体未发布的SSE交易日",
                len(coverage.missing_dates),
                tuple(item.isoformat() for item in coverage.missing_dates[:5]),
            ),
            (
                coverage.duplicate_key_count > 0,
                "存在重复业务键",
                coverage.duplicate_key_count,
                (),
            ),
            (
                coverage.illegal_date_count > 0,
                "存在非SSE开市日记录",
                coverage.illegal_date_count,
                (),
            ),
            (
                coverage.invalid_value_count > 0,
                "存在非法数值",
                coverage.invalid_value_count,
                (),
            ),
        )
        for failed, message, count, samples in checks:
            if failed:
                issues.append(
                    HistoryInputAuditIssue(
                        code=SOURCE_NOT_READY,
                        source=coverage.source,
                        message=message,
                        blocking=True,
                        count=count,
                        samples=samples,
                    )
                )
        if coverage.missing_value_count:
            issues.append(
                HistoryInputAuditIssue(
                    code=SOURCE_NOT_READY,
                    source=coverage.source,
                    message="存在由既有计算合同表达的局部缺失值",
                    blocking=False,
                    count=coverage.missing_value_count,
                )
            )
        return tuple(issues)

    @staticmethod
    def _result(
        *,
        start_date: date,
        end_date: date,
        target_dates: tuple[date, ...],
        warmup_dates: tuple[date, ...],
        hierarchy_version: str | None,
        coverage: tuple[HistorySourceCoverage, ...],
        issues: tuple[HistoryInputAuditIssue, ...],
    ) -> SectorAnalysisHistoryInputAudit:
        payload: Mapping[str, Any] = {
            "auditContractVersion": HISTORY_INPUT_AUDIT_CONTRACT_VERSION,
            "requestedStartDate": start_date,
            "requestedEndDate": end_date,
            "effectiveStartDate": target_dates[0] if target_dates else None,
            "effectiveEndDate": target_dates[-1] if target_dates else None,
            "warmupStartDate": warmup_dates[0] if warmup_dates else None,
            "orderedTradeDates": target_dates,
            "hierarchyVersion": hierarchy_version,
            "formulaBundleVersion": FORMULA_BUNDLE_VERSION,
            "templateVersion": TEMPLATE_VERSION,
            "targetTables": TARGET_TABLES,
            "sourceCoverageSummary": {
                item.source: {
                    "rowCount": item.row_count,
                    "coveredDates": item.covered_dates,
                    "dailyRowCounts": item.daily_row_counts,
                    "missingDates": item.missing_dates,
                    "duplicateKeyCount": item.duplicate_key_count,
                    "illegalDateCount": item.illegal_date_count,
                    "invalidValueCount": item.invalid_value_count,
                    "missingValueCount": item.missing_value_count,
                }
                for item in coverage
            },
            "auditIssues": [issue.as_dict() for issue in issues],
        }
        return SectorAnalysisHistoryInputAudit(
            requested_start_date=start_date,
            requested_end_date=end_date,
            effective_start_date=target_dates[0] if target_dates else None,
            effective_end_date=target_dates[-1] if target_dates else None,
            warmup_start_date=warmup_dates[0] if warmup_dates else None,
            ordered_trade_dates=target_dates,
            hierarchy_version=hierarchy_version,
            source_coverage=coverage,
            issues=issues,
            audit_hash=canonical_json_hash(payload),
        )

    @classmethod
    def _progress(
        cls,
        callback: Callable[[int, int, str], None] | None,
        *,
        done: int,
        item: str,
    ) -> None:
        if callback is not None:
            callback(done, cls.AUDIT_TOTAL, item)

    @staticmethod
    def _check_cancel(cancel_check: Callable[[], None] | None) -> None:
        if cancel_check is not None:
            cancel_check()
