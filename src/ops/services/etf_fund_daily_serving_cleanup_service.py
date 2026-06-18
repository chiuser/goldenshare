from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


FUND_DAILY_RESOURCE = "fund_daily"
OPEN_TASK_RUN_STATUSES: tuple[str, ...] = ("queued", "running", "canceling")


@dataclass(frozen=True, slots=True)
class EtfFundDailyServingCleanupRow:
    ts_code: str
    min_trade_date: str
    max_trade_date: str
    row_count: int


@dataclass(frozen=True, slots=True)
class EtfFundDailyServingCleanupReport:
    dry_run: bool
    output_path: str | None
    confirm_report_path: str | None
    outside_code_count: int
    outside_row_count: int
    deleted_count: int
    post_outside_row_count: int
    raw_row_count_before: int
    raw_row_count_after: int
    active_task_run_count: int


class EtfFundDailyServingCleanupService:
    def run(
        self,
        session: Session,
        *,
        dry_run: bool = True,
        output_path: Path | None = None,
        confirm_report_path: Path | None = None,
    ) -> EtfFundDailyServingCleanupReport:
        if dry_run:
            rows = self._list_outside_active_pool_rows(session)
            if output_path is not None:
                self._write_report_csv(output_path, rows)
            outside_row_count = sum(row.row_count for row in rows)
            return EtfFundDailyServingCleanupReport(
                dry_run=True,
                output_path=str(output_path) if output_path is not None else None,
                confirm_report_path=None,
                outside_code_count=len(rows),
                outside_row_count=outside_row_count,
                deleted_count=0,
                post_outside_row_count=outside_row_count,
                raw_row_count_before=self._raw_row_count(session),
                raw_row_count_after=self._raw_row_count(session),
                active_task_run_count=0,
            )

        if confirm_report_path is None:
            raise ValueError("--confirm-report is required when --apply is used")

        active_task_run_count = self._active_fund_daily_task_run_count(session)
        if active_task_run_count > 0:
            raise RuntimeError(f"fund_daily task runs are still open: count={active_task_run_count}")

        confirm_codes = self._load_confirm_codes(confirm_report_path)
        raw_row_count_before = self._raw_row_count(session)
        pre_rows = self._list_outside_active_pool_rows(session)
        pre_outside_row_count = sum(row.row_count for row in pre_rows)
        deleted_count = self._delete_confirmed_outside_active_pool_rows(session, confirm_codes)
        post_rows = self._list_outside_active_pool_rows(session)
        post_outside_row_count = sum(row.row_count for row in post_rows)
        raw_row_count_after = self._raw_row_count(session)

        if raw_row_count_after != raw_row_count_before:
            raise RuntimeError(
                "raw_tushare.fund_daily row count changed during serving cleanup: "
                f"before={raw_row_count_before} after={raw_row_count_after}"
            )
        if post_outside_row_count != 0:
            raise RuntimeError(f"serving rows outside ETF active pool remain: count={post_outside_row_count}")

        session.commit()
        return EtfFundDailyServingCleanupReport(
            dry_run=False,
            output_path=None,
            confirm_report_path=str(confirm_report_path),
            outside_code_count=len(pre_rows),
            outside_row_count=pre_outside_row_count,
            deleted_count=deleted_count,
            post_outside_row_count=post_outside_row_count,
            raw_row_count_before=raw_row_count_before,
            raw_row_count_after=raw_row_count_after,
            active_task_run_count=active_task_run_count,
        )

    @staticmethod
    def _list_outside_active_pool_rows(session: Session) -> list[EtfFundDailyServingCleanupRow]:
        rows = session.execute(
            text(
                """
                SELECT
                    f.ts_code AS ts_code,
                    MIN(f.trade_date) AS min_trade_date,
                    MAX(f.trade_date) AS max_trade_date,
                    COUNT(*) AS row_count
                FROM core_serving.fund_daily_bar f
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM ops.etf_series_active a
                    WHERE a.resource = :resource
                      AND a.ts_code = f.ts_code
                )
                GROUP BY f.ts_code
                ORDER BY f.ts_code
                """
            ),
            {"resource": FUND_DAILY_RESOURCE},
        ).mappings()
        return [
            EtfFundDailyServingCleanupRow(
                ts_code=str(row["ts_code"]),
                min_trade_date=str(row["min_trade_date"]),
                max_trade_date=str(row["max_trade_date"]),
                row_count=int(row["row_count"]),
            )
            for row in rows
        ]

    @staticmethod
    def _write_report_csv(output_path: Path, rows: list[EtfFundDailyServingCleanupRow]) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["ts_code", "min_trade_date", "max_trade_date", "row_count"],
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        "ts_code": row.ts_code,
                        "min_trade_date": row.min_trade_date,
                        "max_trade_date": row.max_trade_date,
                        "row_count": row.row_count,
                    }
                )

    @staticmethod
    def _load_confirm_codes(confirm_report_path: Path) -> tuple[str, ...]:
        if not confirm_report_path.exists():
            raise FileNotFoundError(f"confirm report not found: {confirm_report_path}")
        with confirm_report_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if "ts_code" not in set(reader.fieldnames or []):
                raise ValueError("confirm report missing required column: ts_code")
            codes = tuple(
                sorted(
                    {
                        str(row.get("ts_code") or "").strip().upper()
                        for row in reader
                        if str(row.get("ts_code") or "").strip()
                    }
                )
            )
        if not codes:
            raise ValueError("confirm report contains no ts_code")
        return codes

    @staticmethod
    def _delete_confirmed_outside_active_pool_rows(session: Session, confirm_codes: tuple[str, ...]) -> int:
        statement = text(
            """
            DELETE FROM core_serving.fund_daily_bar
            WHERE ts_code IN :confirm_codes
              AND ts_code NOT IN (
                  SELECT a.ts_code
                  FROM ops.etf_series_active a
                  WHERE a.resource = :resource
              )
            """
        ).bindparams(bindparam("confirm_codes", expanding=True))
        result = session.execute(
            statement,
            {"confirm_codes": list(confirm_codes), "resource": FUND_DAILY_RESOURCE},
        )
        return result.rowcount or 0

    @staticmethod
    def _raw_row_count(session: Session) -> int:
        return int(session.scalar(text("SELECT COUNT(*) FROM raw_tushare.fund_daily")) or 0)

    @staticmethod
    def _active_fund_daily_task_run_count(session: Session) -> int:
        statement = text(
            """
            SELECT COUNT(*)
            FROM ops.task_run
            WHERE resource_key = :resource
              AND status IN :statuses
            """
        ).bindparams(bindparam("statuses", expanding=True))
        return int(
            session.scalar(
                statement,
                {"resource": FUND_DAILY_RESOURCE, "statuses": list(OPEN_TASK_RUN_STATUSES)},
            )
            or 0
        )
