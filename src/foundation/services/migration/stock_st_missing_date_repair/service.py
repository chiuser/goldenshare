from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.foundation.models.core.equity_stock_st import EquityStockSt
from src.foundation.models.raw.raw_stock_st import RawStockSt
from src.foundation.services.migration.stock_st_missing_date_repair.candidate_loader import (
    StockStMissingDateCandidateLoader,
)
from src.foundation.services.migration.stock_st_missing_date_repair.evidence_resolver import (
    resolve_candidate,
)
from src.foundation.services.migration.stock_st_missing_date_repair.models import (
    StockStMissingDatePreview,
    StockStMissingDateRepairResult,
)
from src.foundation.services.migration.stock_st_missing_date_repair.writer import (
    StockStMissingDateRepairWriter,
)


class StockStMissingDateRepairService:
    def __init__(
        self,
        *,
        candidate_loader: StockStMissingDateCandidateLoader | None = None,
        writer: StockStMissingDateRepairWriter | None = None,
    ) -> None:
        self.candidate_loader = candidate_loader or StockStMissingDateCandidateLoader()
        self.writer = writer or StockStMissingDateRepairWriter()

    def run(
        self,
        session: Session,
        *,
        trade_dates: list[date],
        output_dir: Path | None = None,
        apply: bool,
        fail_on_review_items: bool,
    ) -> StockStMissingDateRepairResult:
        normalized_dates = sorted(set(trade_dates))
        if not normalized_dates:
            raise ValueError("至少需要一个缺失日期。")

        date_previews = tuple(self._build_date_preview(session, trade_date) for trade_date in normalized_dates)
        artifacts = self.writer.write_preview_files(output_dir=output_dir, date_previews=date_previews)

        review_dates = tuple(preview.trade_date for preview in date_previews if not preview.is_apply_eligible)
        if apply and fail_on_review_items and review_dates:
            raise ValueError(
                "存在人工审查项或验证冲突，拒绝 apply："
                + ", ".join(item.isoformat() for item in review_dates)
            )

        applied_row_count = 0
        applied_date_count = 0
        if apply:
            eligible_previews = tuple(preview for preview in date_previews if preview.is_apply_eligible)
            self._preflight_target_dates_are_empty(session, eligible_previews)
            raw_rows = self.writer.build_raw_rows(eligible_previews)
            core_rows = self.writer.build_core_rows(eligible_previews)
            session.add_all(raw_rows)
            session.add_all(core_rows)
            session.commit()
            applied_row_count = len(core_rows)
            applied_date_count = len(eligible_previews)

        return StockStMissingDateRepairResult(
            artifacts=artifacts,
            date_previews=date_previews,
            applied=apply,
            applied_date_count=applied_date_count,
            applied_row_count=applied_row_count,
            skipped_review_dates=review_dates,
        )

    def _build_date_preview(self, session: Session, trade_date: date) -> StockStMissingDatePreview:
        context = self.candidate_loader.load_date_context(session, trade_date)
        active_namechanges = self.candidate_loader.load_active_namechanges(
            session,
            trade_date=trade_date,
            candidate_codes=context.candidate_codes,
        )

        candidates = []
        review_items = []
        unresolved_candidate_count = 0
        selected_non_st_count = 0
        selected_namechange_count = 0
        validation_ok_total = 0
        validation_not_ok_total = 0
        reconstructed_count = 0

        for ts_code in context.candidate_codes:
            namechange_rows = active_namechanges.get(ts_code, ())
            if namechange_rows:
                selected_namechange_count += 1
            candidate, review = resolve_candidate(
                trade_date=trade_date,
                ts_code=ts_code,
                prev_name=context.prev_names.get(ts_code),
                next_name=context.next_names.get(ts_code),
                same_day_st_events=context.same_day_st_events.get(ts_code, ()),
                active_namechanges=namechange_rows,
            )
            candidates.append(candidate)
            if review is not None:
                review_items.append(review)
            if candidate.validation_status == "not_ok_missing_namechange_interval":
                unresolved_candidate_count += 1
            if candidate.validation_status == "excluded_non_st_namechange":
                selected_non_st_count += 1
            elif candidate.validation_status.startswith("not_ok") and not candidate.include:
                validation_not_ok_total += 1
            if candidate.include:
                reconstructed_count += 1
                if candidate.validation_status.startswith("ok_"):
                    validation_ok_total += 1
                else:
                    validation_not_ok_total += 1

        return StockStMissingDatePreview(
            trade_date=trade_date,
            prev_date=context.prev_date,
            next_date=context.next_date,
            prev_count=context.prev_count,
            next_count=context.next_count,
            st_same_day_count=context.st_same_day_count,
            candidate_count=context.candidate_count,
            selected_namechange_count=selected_namechange_count,
            unresolved_candidate_count=unresolved_candidate_count,
            selected_non_st_count=selected_non_st_count,
            reconstructed_count=reconstructed_count,
            validation_ok_total=validation_ok_total,
            validation_not_ok_total=validation_not_ok_total,
            manual_review_count=len(review_items),
            candidates=tuple(candidates),
            review_items=tuple(review_items),
        )

    @staticmethod
    def _preflight_target_dates_are_empty(
        session: Session,
        date_previews: tuple[StockStMissingDatePreview, ...],
    ) -> None:
        for preview in date_previews:
            raw_count = session.scalar(
                select(func.count()).select_from(RawStockSt).where(RawStockSt.trade_date == preview.trade_date)
            ) or 0
            core_count = session.scalar(
                select(func.count()).select_from(EquityStockSt).where(EquityStockSt.trade_date == preview.trade_date)
            ) or 0
            if int(raw_count) > 0 or int(core_count) > 0:
                raise ValueError(
                    f"目标日期 {preview.trade_date.isoformat()} 已存在数据：raw={int(raw_count)} core={int(core_count)}"
                )

