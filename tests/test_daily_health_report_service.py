from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

from src.ops.services.operations_daily_health_report_service import DailyHealthReportService


def _freshness_response() -> SimpleNamespace:
    dataset_daily = SimpleNamespace(
        dataset_key="daily",
        resource_key="daily",
        display_name="股票日线",
        domain_key="equity",
        domain_display_name="股票",
        freshness_status="fresh",
        lag_days=0,
        earliest_business_date=date(2020, 1, 1),
        latest_business_date=date(2026, 4, 8),
        last_sync_date=date(2026, 4, 8),
        latest_success_at=datetime(2026, 4, 8, 1, 0, tzinfo=timezone.utc),
        recent_failure_summary=None,
    )
    dataset_factor = SimpleNamespace(
        dataset_key="adj_factor",
        resource_key="adj_factor",
        display_name="复权因子",
        domain_key="equity",
        domain_display_name="股票",
        freshness_status="stale",
        lag_days=2,
        earliest_business_date=date(2020, 1, 1),
        latest_business_date=date(2026, 4, 6),
        last_sync_date=date(2026, 4, 6),
        latest_success_at=datetime(2026, 4, 6, 1, 0, tzinfo=timezone.utc),
        recent_failure_summary="同步失败：示例",
    )
    summary = SimpleNamespace(
        total_datasets=2,
        fresh_datasets=1,
        lagging_datasets=0,
        stale_datasets=1,
        unknown_datasets=0,
        disabled_datasets=0,
    )
    return SimpleNamespace(
        summary=summary,
        groups=[SimpleNamespace(domain_key="equity", domain_display_name="股票", items=[dataset_daily, dataset_factor])],
    )


def test_daily_health_report_builds_markdown_with_full_dataset_coverage(mocker) -> None:
    service = DailyHealthReportService()
    mocker.patch("src.ops.services.operations_daily_health_report_service.OpsFreshnessQueryService.build_freshness", return_value=_freshness_response())
    mocker.patch.object(
        service,
        "_load_executions",
        return_value=[
            SimpleNamespace(
                id=101,
                spec_key="sync_daily.adj_factor",
                status="failed",
                error_message="boom",
                summary_message=None,
                started_at=None,
            ),
            SimpleNamespace(
                id=102,
                spec_key="sync_daily.daily",
                status="success",
                error_message=None,
                summary_message="ok",
                started_at=None,
            ),
        ],
    )
    mocker.patch.object(
        service,
        "_load_sync_run_logs",
        return_value=[
            SimpleNamespace(
                job_name="sync_equity_daily",
                status="SUCCESS",
                rows_fetched=100,
                rows_written=100,
                started_at=datetime(2026, 4, 8, 1, 0, tzinfo=timezone.utc),
            ),
            SimpleNamespace(
                job_name="sync_equity_adj_factor",
                status="FAILED",
                rows_fetched=100,
                rows_written=0,
                started_at=datetime(2026, 4, 8, 2, 0, tzinfo=timezone.utc),
            ),
        ],
    )

    report = service.build_report(mocker.Mock(), report_date=date(2026, 4, 8))
    markdown = service.render_markdown(report)

    assert report.freshness_summary["total_datasets"] == 2
    assert any(item["display_name"] == "股票日线" for item in report.datasets)
    assert any(item["display_name"] == "复权因子" for item in report.datasets)
    assert "数据健康度日报（2026-04-08）" in markdown
    assert "复权因子" in markdown
    assert "重点关注" in markdown
    assert any("严重滞后" in item for item in report.key_alerts)
