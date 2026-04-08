from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from src.ops.models.ops.job_execution import JobExecution
from src.ops.models.ops.sync_run_log import SyncRunLog
from src.ops.queries.freshness_query_service import OpsFreshnessQueryService
from src.operations.specs import get_dataset_freshness_spec_by_job_name


DEFAULT_REPORT_TZ = "Asia/Shanghai"


@dataclass(slots=True)
class DailyHealthReport:
    report_date: date
    generated_at: datetime
    timezone_name: str
    freshness_summary: dict[str, int]
    execution_summary: dict[str, int]
    datasets: list[dict]
    dataset_runs: list[dict]
    key_alerts: list[str]

    def to_json(self) -> str:
        payload = {
            "report_date": self.report_date.isoformat(),
            "generated_at": self.generated_at.isoformat(),
            "timezone": self.timezone_name,
            "freshness_summary": self.freshness_summary,
            "execution_summary": self.execution_summary,
            "datasets": self.datasets,
            "dataset_runs": self.dataset_runs,
            "key_alerts": self.key_alerts,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)


class DailyHealthReportService:
    def build_report(
        self,
        session: Session,
        *,
        report_date: date,
        timezone_name: str = DEFAULT_REPORT_TZ,
    ) -> DailyHealthReport:
        tz = ZoneInfo(timezone_name)
        start_utc, end_utc = self._day_window_utc(report_date, tz)
        freshness = OpsFreshnessQueryService().build_freshness(session, today=report_date)
        dataset_items = [item for group in freshness.groups for item in group.items]
        executions = self._load_executions(session, start_utc=start_utc, end_utc=end_utc)
        run_logs = self._load_sync_run_logs(session, start_utc=start_utc, end_utc=end_utc)

        execution_summary = self._summarize_executions(executions)
        dataset_runs = self._summarize_dataset_runs(run_logs)
        datasets = self._serialize_dataset_items(dataset_items)
        key_alerts = self._build_key_alerts(
            report_date=report_date,
            timezone_name=timezone_name,
            dataset_items=dataset_items,
            executions=executions,
            dataset_runs=dataset_runs,
        )

        return DailyHealthReport(
            report_date=report_date,
            generated_at=datetime.now(tz),
            timezone_name=timezone_name,
            freshness_summary={
                "total_datasets": freshness.summary.total_datasets,
                "fresh_datasets": freshness.summary.fresh_datasets,
                "lagging_datasets": freshness.summary.lagging_datasets,
                "stale_datasets": freshness.summary.stale_datasets,
                "unknown_datasets": freshness.summary.unknown_datasets,
            },
            execution_summary=execution_summary,
            datasets=datasets,
            dataset_runs=dataset_runs,
            key_alerts=key_alerts,
        )

    def render_markdown(self, report: DailyHealthReport) -> str:
        lines: list[str] = []
        lines.append(f"# 数据健康度日报（{report.report_date.isoformat()}）")
        lines.append("")
        lines.append(f"- 生成时间：{report.generated_at.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"- 时区：{report.timezone_name}")
        lines.append("")
        lines.append("## 总览")
        lines.append(
            f"- 数据集：总计 {report.freshness_summary['total_datasets']}，正常 {report.freshness_summary['fresh_datasets']}，"
            f"滞后 {report.freshness_summary['lagging_datasets']}，严重滞后 {report.freshness_summary['stale_datasets']}，"
            f"未知 {report.freshness_summary['unknown_datasets']}"
        )
        lines.append(
            f"- 今日任务：总计 {report.execution_summary['total']}，成功 {report.execution_summary['success']}，"
            f"失败 {report.execution_summary['failed']}，执行中 {report.execution_summary['running']}，"
            f"等待中 {report.execution_summary['queued']}"
        )
        lines.append("")
        lines.append("## 重点关注")
        if report.key_alerts:
            for alert in report.key_alerts:
                lines.append(f"- {alert}")
        else:
            lines.append("- 无")
        lines.append("")
        lines.append("## 数据健康度（全量数据集）")
        lines.append("| 数据域 | 数据集 | 状态 | 日期范围/最近同步 | 最近成功时间 | 最近异常 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for item in report.datasets:
            lines.append(
                "| {domain} | {name} | {status} | {range} | {success_at} | {failure} |".format(
                    domain=item["domain_display_name"],
                    name=item["display_name"],
                    status=item["freshness_status"],
                    range=item["date_range_or_sync"],
                    success_at=item["latest_success_at"] or "-",
                    failure=item["recent_failure_summary"] or "-",
                )
            )
        lines.append("")
        lines.append("## 当日同步任务（按数据集聚合）")
        lines.append("| 数据集 | 运行次数 | 成功 | 失败 | 运行中 | 拉取总量 | 写入总量 | 最后一次状态 |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
        for row in report.dataset_runs:
            lines.append(
                "| {display_name} | {total_runs} | {success_runs} | {failed_runs} | {running_runs} | {rows_fetched} | {rows_written} | {last_status} |".format(
                    **row
                )
            )
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _day_window_utc(report_date: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
        start_local = datetime(report_date.year, report_date.month, report_date.day, tzinfo=tz)
        end_local = start_local + timedelta(days=1)
        return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)

    @staticmethod
    def _load_executions(session: Session, *, start_utc: datetime, end_utc: datetime) -> list[JobExecution]:
        return list(
            session.scalars(
                select(JobExecution).where(
                    and_(JobExecution.requested_at >= start_utc, JobExecution.requested_at < end_utc)
                )
            )
        )

    @staticmethod
    def _load_sync_run_logs(session: Session, *, start_utc: datetime, end_utc: datetime) -> list[SyncRunLog]:
        return list(
            session.scalars(
                select(SyncRunLog).where(and_(SyncRunLog.started_at >= start_utc, SyncRunLog.started_at < end_utc))
            )
        )

    @staticmethod
    def _summarize_executions(executions: list[JobExecution]) -> dict[str, int]:
        summary = {"total": len(executions), "success": 0, "failed": 0, "running": 0, "queued": 0}
        for item in executions:
            status = (item.status or "").lower()
            if status in summary:
                summary[status] += 1
        return summary

    @staticmethod
    def _format_range_or_sync(item) -> str:  # type: ignore[no-untyped-def]
        if item.earliest_business_date and item.latest_business_date:
            return f"{item.earliest_business_date.isoformat()} ~ {item.latest_business_date.isoformat()}"
        if item.last_sync_date:
            return f"最近同步 {item.last_sync_date.isoformat()}"
        return "-"

    def _serialize_dataset_items(self, dataset_items: list) -> list[dict]:  # type: ignore[no-untyped-def]
        rows = []
        for item in dataset_items:
            rows.append(
                {
                    "dataset_key": item.dataset_key,
                    "resource_key": item.resource_key,
                    "display_name": item.display_name,
                    "domain_display_name": item.domain_display_name,
                    "freshness_status": item.freshness_status,
                    "lag_days": item.lag_days,
                    "date_range_or_sync": self._format_range_or_sync(item),
                    "latest_success_at": item.latest_success_at.isoformat() if item.latest_success_at else None,
                    "recent_failure_summary": item.recent_failure_summary,
                }
            )
        rows.sort(key=lambda row: (row["domain_display_name"], row["display_name"]))
        return rows

    @staticmethod
    def _summarize_dataset_runs(run_logs: list[SyncRunLog]) -> list[dict]:
        # job_name -> aggregate
        by_job_name: dict[str, dict] = {}
        for log in run_logs:
            spec = get_dataset_freshness_spec_by_job_name(log.job_name)
            if spec is None:
                continue
            key = spec.resource_key
            row = by_job_name.get(key)
            if row is None:
                row = {
                    "resource_key": key,
                    "display_name": spec.display_name,
                    "total_runs": 0,
                    "success_runs": 0,
                    "failed_runs": 0,
                    "running_runs": 0,
                    "rows_fetched": 0,
                    "rows_written": 0,
                    "last_status": "-",
                    "last_started_at": None,
                }
                by_job_name[key] = row
            row["total_runs"] += 1
            status = (log.status or "").upper()
            if status == "SUCCESS":
                row["success_runs"] += 1
            elif status == "FAILED":
                row["failed_runs"] += 1
            elif status == "RUNNING":
                row["running_runs"] += 1
            row["rows_fetched"] += int(log.rows_fetched or 0)
            row["rows_written"] += int(log.rows_written or 0)
            if row["last_started_at"] is None or (log.started_at and log.started_at > row["last_started_at"]):
                row["last_started_at"] = log.started_at
                row["last_status"] = status
        rows = list(by_job_name.values())
        for row in rows:
            row.pop("last_started_at", None)
        rows.sort(key=lambda item: item["display_name"])
        return rows

    def _build_key_alerts(
        self,
        *,
        report_date: date,
        timezone_name: str,
        dataset_items: list,  # type: ignore[no-untyped-def]
        executions: list[JobExecution],
        dataset_runs: list[dict],
    ) -> list[str]:
        alerts: list[str] = []

        stale_items = [item for item in dataset_items if item.freshness_status == "stale"]
        stale_items.sort(key=lambda item: ((item.lag_days or 0) * -1, item.display_name))
        for item in stale_items[:8]:
            lag_text = f"{item.lag_days}天" if item.lag_days is not None else "未知"
            alerts.append(f"【严重滞后】{item.display_name}，滞后 {lag_text}")

        failed = [item for item in executions if (item.status or "").lower() == "failed"]
        for item in failed[:8]:
            alerts.append(
                f"【今日失败】{item.spec_key}（执行ID={item.id}）{(item.error_message or item.summary_message or '').strip()[:60]}"
            )

        now_local = datetime.now(ZoneInfo(timezone_name))
        for item in executions:
            if (item.status or "").lower() != "running" or item.started_at is None:
                continue
            elapsed = now_local - item.started_at.astimezone(ZoneInfo(timezone_name))
            if elapsed >= timedelta(minutes=30):
                alerts.append(f"【长时间运行】{item.spec_key}（执行ID={item.id}）已运行约 {int(elapsed.total_seconds() // 60)} 分钟")

        for row in dataset_runs:
            if row["rows_fetched"] > 0 and row["rows_written"] == 0:
                alerts.append(f"【写入异常】{row['display_name']} 当日拉取 {row['rows_fetched']} 条但写入 0 条")

        if not alerts:
            return []
        # de-dup while preserving order
        deduped = []
        seen = set()
        for item in alerts:
            if item in seen:
                continue
            deduped.append(item)
            seen.add(item)
        return deduped[:12]

