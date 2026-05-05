from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from src.foundation.models.core.equity_stock_st import EquityStockSt
from src.foundation.models.raw.raw_stock_st import RawStockSt
from src.foundation.services.migration.stock_st_missing_date_repair.models import (
    StockStMissingDatePreview,
    StockStPreviewArtifacts,
)


class StockStMissingDateRepairWriter:
    def write_preview_files(
        self,
        *,
        output_dir: Path | None,
        date_previews: tuple[StockStMissingDatePreview, ...],
    ) -> StockStPreviewArtifacts:
        target_dir = output_dir or (
            Path("reports")
            / "stock_st_missing_date_repair"
            / datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        target_dir.mkdir(parents=True, exist_ok=True)

        summary_path = target_dir / "stock_st_missing_date_preview_summary.csv"
        preview_rows_path = target_dir / "stock_st_missing_date_preview_rows.csv"
        manual_review_path = target_dir / "stock_st_missing_date_manual_review.csv"

        self._write_summary(summary_path, date_previews)
        self._write_preview_rows(preview_rows_path, date_previews)
        self._write_manual_review(manual_review_path, date_previews)
        return StockStPreviewArtifacts(
            output_dir=target_dir.resolve(),
            summary_path=summary_path.resolve(),
            preview_rows_path=preview_rows_path.resolve(),
            manual_review_path=manual_review_path.resolve(),
        )

    def build_raw_rows(self, date_previews: tuple[StockStMissingDatePreview, ...]) -> list[RawStockSt]:
        rows: list[RawStockSt] = []
        for preview in date_previews:
            if not preview.is_apply_eligible:
                continue
            for candidate in preview.candidates:
                if not candidate.include or candidate.resolved_name is None:
                    continue
                selected = candidate.selected_namechange
                payload = {
                    "reconstruction": True,
                    "source_kind": "db_namechange_primary",
                    "missing_date": candidate.trade_date.isoformat(),
                    "prev_trade_date": preview.prev_date.isoformat(),
                    "next_trade_date": preview.next_date.isoformat(),
                    "name_source": candidate.name_source,
                    "validation_status": candidate.validation_status,
                    "selected_namechange": None
                    if selected is None
                    else {
                        "name": selected.name,
                        "start_date": selected.start_date.isoformat(),
                        "end_date": selected.end_date.isoformat() if selected.end_date else None,
                        "ann_date": selected.ann_date.isoformat() if selected.ann_date else None,
                        "change_reason": selected.change_reason,
                    },
                    "same_day_st_events": [
                        {
                            "name": event.name,
                            "pub_date": event.pub_date.isoformat(),
                            "imp_date": event.imp_date.isoformat() if event.imp_date else None,
                            "st_type": event.st_type,
                            "st_reason": event.st_reason,
                        }
                        for event in candidate.same_day_st_events
                    ],
                    "evidence_sources": {
                        "namechange_table": "raw_tushare.namechange",
                        "st_table": "raw_tushare.st",
                    },
                }
                rows.append(
                    RawStockSt(
                        ts_code=candidate.ts_code,
                        trade_date=candidate.trade_date,
                        type="ST",
                        name=candidate.resolved_name,
                        type_name="风险警示板",
                        api_name="stock_st_repair",
                        raw_payload=json.dumps(payload, ensure_ascii=False, default=str),
                    )
                )
        return rows

    def build_core_rows(self, date_previews: tuple[StockStMissingDatePreview, ...]) -> list[EquityStockSt]:
        rows: list[EquityStockSt] = []
        for preview in date_previews:
            if not preview.is_apply_eligible:
                continue
            for candidate in preview.candidates:
                if not candidate.include or candidate.resolved_name is None:
                    continue
                rows.append(
                    EquityStockSt(
                        ts_code=candidate.ts_code,
                        trade_date=candidate.trade_date,
                        type="ST",
                        name=candidate.resolved_name,
                        type_name="风险警示板",
                    )
                )
        return rows

    @staticmethod
    def _write_summary(path: Path, date_previews: tuple[StockStMissingDatePreview, ...]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "trade_date",
                    "prev_date",
                    "next_date",
                    "prev_count",
                    "next_count",
                    "st_same_day_count",
                    "candidate_count",
                    "selected_namechange_count",
                    "unresolved_candidate_count",
                    "selected_non_st_count",
                    "reconstructed_count",
                    "validation_ok_total",
                    "validation_not_ok_total",
                    "manual_review_count",
                    "apply_eligible",
                ],
            )
            writer.writeheader()
            for preview in date_previews:
                writer.writerow(
                    {
                        "trade_date": preview.trade_date.isoformat(),
                        "prev_date": preview.prev_date.isoformat(),
                        "next_date": preview.next_date.isoformat(),
                        "prev_count": preview.prev_count,
                        "next_count": preview.next_count,
                        "st_same_day_count": preview.st_same_day_count,
                        "candidate_count": preview.candidate_count,
                        "selected_namechange_count": preview.selected_namechange_count,
                        "unresolved_candidate_count": preview.unresolved_candidate_count,
                        "selected_non_st_count": preview.selected_non_st_count,
                        "reconstructed_count": preview.reconstructed_count,
                        "validation_ok_total": preview.validation_ok_total,
                        "validation_not_ok_total": preview.validation_not_ok_total,
                        "manual_review_count": preview.manual_review_count,
                        "apply_eligible": "Y" if preview.is_apply_eligible else "N",
                    }
                )

    @staticmethod
    def _write_preview_rows(path: Path, date_previews: tuple[StockStMissingDatePreview, ...]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "trade_date",
                    "ts_code",
                    "name",
                    "type",
                    "type_name",
                    "name_source",
                    "validation_status",
                    "validation_message",
                    "prev_name",
                    "next_name",
                    "same_day_st_event_count",
                    "same_day_st_names",
                    "same_day_st_types",
                    "selected_namechange_name",
                    "selected_namechange_start_date",
                    "selected_namechange_end_date",
                    "selected_namechange_ann_date",
                    "selected_namechange_change_reason",
                    "active_namechange_row_count",
                ],
            )
            writer.writeheader()
            for preview in date_previews:
                for candidate in preview.candidates:
                    if not candidate.include or candidate.resolved_name is None:
                        continue
                    selected = candidate.selected_namechange
                    writer.writerow(
                        {
                            "trade_date": candidate.trade_date.isoformat(),
                            "ts_code": candidate.ts_code,
                            "name": candidate.resolved_name,
                            "type": "ST",
                            "type_name": "风险警示板",
                            "name_source": candidate.name_source,
                            "validation_status": candidate.validation_status,
                            "validation_message": candidate.validation_message,
                            "prev_name": candidate.prev_name,
                            "next_name": candidate.next_name,
                            "same_day_st_event_count": len(candidate.same_day_st_events),
                            "same_day_st_names": json.dumps(
                                [event.name for event in candidate.same_day_st_events],
                                ensure_ascii=False,
                            ),
                            "same_day_st_types": json.dumps(
                                [event.st_type for event in candidate.same_day_st_events],
                                ensure_ascii=False,
                            ),
                            "selected_namechange_name": selected.name if selected else None,
                            "selected_namechange_start_date": selected.start_date.isoformat() if selected else None,
                            "selected_namechange_end_date": selected.end_date.isoformat() if selected and selected.end_date else None,
                            "selected_namechange_ann_date": selected.ann_date.isoformat() if selected and selected.ann_date else None,
                            "selected_namechange_change_reason": selected.change_reason if selected else None,
                            "active_namechange_row_count": candidate.active_namechange_row_count,
                        }
                    )

    @staticmethod
    def _write_manual_review(path: Path, date_previews: tuple[StockStMissingDatePreview, ...]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "trade_date",
                    "ts_code",
                    "review_code",
                    "review_message",
                    "prev_name",
                    "next_name",
                    "selected_namechange_name",
                    "selected_namechange_start_date",
                    "selected_namechange_end_date",
                    "selected_namechange_ann_date",
                    "selected_namechange_change_reason",
                    "same_day_st_names",
                    "same_day_st_types",
                ],
            )
            writer.writeheader()
            for preview in date_previews:
                for review in preview.review_items:
                    selected = review.selected_namechange
                    writer.writerow(
                        {
                            "trade_date": review.trade_date.isoformat(),
                            "ts_code": review.ts_code,
                            "review_code": review.review_code,
                            "review_message": review.review_message,
                            "prev_name": review.prev_name,
                            "next_name": review.next_name,
                            "selected_namechange_name": selected.name if selected else None,
                            "selected_namechange_start_date": selected.start_date.isoformat() if selected else None,
                            "selected_namechange_end_date": selected.end_date.isoformat() if selected and selected.end_date else None,
                            "selected_namechange_ann_date": selected.ann_date.isoformat() if selected and selected.ann_date else None,
                            "selected_namechange_change_reason": selected.change_reason if selected else None,
                            "same_day_st_names": json.dumps(
                                [event.name for event in review.same_day_st_events],
                                ensure_ascii=False,
                            ),
                            "same_day_st_types": json.dumps(
                                [event.st_type for event in review.same_day_st_events],
                                ensure_ascii=False,
                            ),
                        }
                    )

