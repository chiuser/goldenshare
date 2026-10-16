"""Monthly sensor follows the shared direct-source planner without old daily-file dependencies."""

from types import SimpleNamespace as NS

from orchestrator.defs.stock_period_update import evaluate_daily_sensor

from .test_raw_stock_weekly_update_job_sensor import NOW, exercise_sensor


def test_monthly_debt_and_current_request_preserve_cursor(tmp_path):
    exercise_sensor(tmp_path, "month")


def test_pending_weekly_writer_blocks_monthly_without_scanning(tmp_path):
    class Forbidden:
        def __getattr__(self, name):
            raise AssertionError(name)

    ctx = NS(
        instance=NS(get_runs=lambda **_: [object()]),
        resources=Forbidden(),
        cursor="old",
    )
    result = evaluate_daily_sensor(
        ctx, NOW, freq="month", staging_root=tmp_path / "stage"
    )
    assert (
        not result.run_requests
        and result.cursor is None
        and not (tmp_path / "stage").exists()
    )
