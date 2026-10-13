"""Checks-only event backfill using a real Dagster execution context."""

import json
import signal
import tempfile
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    check_capture_path,
)
from orchestrator.defs.bootstrap.stock_weekly_event_instance import (
    assert_weekly_event_instance_matches,
)
from orchestrator.defs.bootstrap.stock_weekly_events import (
    apply_weekly_events,
    verify_weekly_event_plan,
)
from orchestrator.defs.paths import DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.run_contracts.configs import (
    StockWeeklyBootstrapEventChecksConfig,
)


@dg.op(description="仅补录已验收复权周线 B0 的检查记录；保留旧记录，不写行情。")
def report_stock_weekly_bootstrap_checks(
    context: dg.OpExecutionContext, config: StockWeeklyBootstrapEventChecksConfig
) -> dict:
    plan_path = Path(config.plan_path)
    checkpoint = Path(config.checkpoint_path)
    check_capture_path(plan_path)
    check_capture_path(checkpoint)
    allowed_roots = (
        Path(DEFAULT_LAKE_STAGING_ROOT),
        Path("/private/tmp"),
        Path(tempfile.gettempdir()).resolve(),
    )
    if (
        not any(plan_path.is_relative_to(root) for root in allowed_roots)
        or checkpoint.parent != plan_path.parent
        or checkpoint == plan_path
    ):
        raise WeeklyCaptureError("event_checkpoint_path_invalid")
    if plan_path.stat().st_size > 8 * 1024 * 1024:
        raise WeeklyCaptureError("event_input_budget_exceeded")
    plan = json.loads(plan_path.read_text())
    verify_weekly_event_plan(plan)
    if plan["plan_hash"] != config.expected_plan_hash:
        raise WeeklyCaptureError("event_plan_hash_mismatch")
    if any(e["bootstrap_identity"] is None for e in plan["entries"]):
        raise WeeklyCaptureError("event_bootstrap_scope_required")
    if config.start >= len(plan["entries"]):
        raise WeeklyCaptureError("event_batch_scope_invalid")
    assert_weekly_event_instance_matches(context.instance, plan["instance_identity"])
    cancelled = False

    def cancel(signum, frame):
        nonlocal cancelled
        cancelled = True

    handlers = {
        number: signal.signal(number, cancel)
        for number in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        context.log.info("补录检查：start=%s count=%s", config.start, config.count)
        return apply_weekly_events(
            context.instance,
            plan,
            stage="checks",
            checkpoint=checkpoint,
            start=config.start,
            count=config.count,
            cancel=lambda: cancelled,
            check_context=context,
        )
    except WeeklyCaptureError as error:
        if str(error) == "canceled":
            run = context.instance.get_run_by_id(context.run_id)
            context.instance.report_run_canceling(run, "检查补录取消；保留已登记事件。")
            raise KeyboardInterrupt from error
        raise
    finally:
        for number, handler in handlers.items():
            signal.signal(number, handler)
