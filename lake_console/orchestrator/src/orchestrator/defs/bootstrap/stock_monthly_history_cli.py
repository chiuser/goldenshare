"""Explicit monthly bootstrap CLI; defaults to a read-only target preflight."""

import argparse
import json
import signal
import tempfile
from pathlib import Path

from orchestrator.defs.bootstrap.stock_monthly_files import (
    check_monthly_path,
    monthly_file_hash,
    read_monthly_json,
    write_monthly_json,
)
from orchestrator.defs.bootstrap.stock_monthly_history import (
    audit_monthly_history,
    execute_monthly_history,
    monthly_history_preflight,
)
from orchestrator.defs.bootstrap.stock_monthly_history_plan import (
    freeze_monthly_history_plan,
    load_monthly_history_plan,
    monthly_history_plan_payload,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.run_contracts.stock_monthly import (
    MonthlyBootstrapIOPolicy,
    StockMonthlySource,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "dry-run", "apply", "audit"), nargs="?", default="dry-run")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--source", choices=[s.value for s in StockMonthlySource])
    parser.add_argument("--first-month")
    parser.add_argument("--last-month")
    parser.add_argument("--lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT))
    parser.add_argument("--staging-root", type=Path, default=Path(DEFAULT_LAKE_STAGING_ROOT))
    parser.add_argument("--preflight", type=Path)
    parser.add_argument("--preflight-sha256")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    check_monthly_path(args.output)
    if any(args.output.is_relative_to(p) for p in (args.lake_root, args.staging_root)):
        parser.error("control output must be outside lake and staging roots")
    if args.output in (args.inventory, args.plan, args.preflight):
        parser.error("output cannot overwrite frozen input evidence")
    repo = Path(__file__).resolve().parents[6]
    if not any(args.output.is_relative_to(root) for root in (repo / "reports", Path("/private/tmp"), Path(tempfile.gettempdir()).resolve())):
        parser.error("output must be under repository reports or /private/tmp")
    if not args.output.parent.is_dir():
        parser.error("output parent must already exist")
    io = MonthlyBootstrapIOPolicy()
    if args.action == "freeze":
        if not all((args.inventory, args.source, args.first_month, args.last_month)):
            parser.error("freeze requires inventory, source, first-month and last-month")
        result = monthly_history_plan_payload(freeze_monthly_history_plan(args.inventory, args.source, args.first_month, args.last_month))
        write_monthly_json(args.output, result, io.inventory_max_bytes)
        return 0
    if args.plan is None:
        parser.error("plan is required")
    plan = load_monthly_history_plan(args.plan)
    if args.action == "dry-run":
        result = monthly_history_preflight(plan, args.lake_root, args.staging_root)
    elif args.action == "audit":
        result = audit_monthly_history(plan, args.lake_root, args.staging_root)
    else:
        if not args.preflight or not args.preflight_sha256:
            parser.error("apply requires preflight and its external SHA256")
        if monthly_file_hash(args.preflight, max_bytes=io.control_max_bytes) != args.preflight_sha256:
            raise ValueError("monthly_preflight_file_changed")
        preflight = read_monthly_json(args.preflight, io.control_max_bytes)
        if monthly_file_hash(args.preflight, max_bytes=io.control_max_bytes) != args.preflight_sha256:
            raise ValueError("monthly_preflight_file_changed")
        if preflight.get("lake_root") != str(args.lake_root) or preflight.get("staging_root") != str(args.staging_root):
            raise ValueError("monthly_cli_root_mismatch")
        interrupted = False

        def cancel(signum, frame):
            nonlocal interrupted
            interrupted = True

        previous = {s: signal.signal(s, cancel) for s in (signal.SIGINT, signal.SIGTERM)}
        try:
            result = execute_monthly_history(plan, preflight, cancel=lambda: interrupted, progress=lambda event: print(json.dumps(event, ensure_ascii=False), flush=True))
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
    write_monthly_json(args.output, result, io.control_max_bytes)
    print(json.dumps({k: v for k, v in result.items() if k not in ("files", "entries")}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
