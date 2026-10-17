"""Fixed local moneyflow continuation CLI, outside Definitions discovery."""

import argparse

from orchestrator.moneyflow_continuation.contract import (
    ContinuationError,
    encoded,
    file_hash,
    now,
    read_json,
)
from orchestrator.moneyflow_continuation.plan import (
    make_plan,
    validate_plan,
    validate_scope,
)
from orchestrator.moneyflow_continuation.submission import (
    new_plan_output,
    validate_new_output,
    verify_plan_file,
)


def parser():
    result = argparse.ArgumentParser(
        description="按明确日期清单接续七表；正式运行需先获批准。"
    )
    operations = result.add_subparsers(dest="mode", required=True)
    plan = operations.add_parser("plan", help="只读核对并生成新清单")
    plan.add_argument("--scope-file", required=True)
    plan.add_argument("--output", required=True)
    plan.add_argument("--parent-plan")
    inspect = operations.add_parser("inspect", help="只读回当前事实")
    inspect.add_argument("--plan", required=True)
    apply = operations.add_parser("apply", help="执行已批准的精确清单或继续观察原任务")
    apply.add_argument("--plan", required=True)
    apply.add_argument("--expect-plan-sha256", required=True)
    audit = operations.add_parser(
        "audit", help="只读核验原49项，保留两次父失败，仅创建报告"
    )
    audit.add_argument("--plan", required=True)
    audit.add_argument("--expect-plan-sha256", required=True)
    audit.add_argument("--output", required=True)
    return result


def run(args, backend):
    from orchestrator.moneyflow_continuation.execution import (
        StopSignals,
        apply,
        inspect,
    )
    from orchestrator.moneyflow_continuation.state import next_action, source_inventory

    if args.mode == "plan":
        scope = read_json(args.scope_file)
        from orchestrator.moneyflow_continuation.contract import require

        require(
            {"units", "verification"}
            <= set(scope)
            <= {"units", "verification", "launch_recovery", "collection_recovery"},
            "scope_fields",
            2,
        )
        # Reject malformed input before any calendar query.
        entries = scope["units"]
        candidate_days = (
            {u.get("trade_date") for u in entries if isinstance(u, dict)}
            if isinstance(entries, list)
            else set()
        )
        validate_scope(entries, candidate_days, now())
        opened = backend.calendar([u["trade_date"] for u in entries])
        validate_scope(entries, opened, now())
        verification_audit = backend.verification(scope["verification"])
        parent = read_json(args.parent_plan) if args.parent_plan else None
        draft = make_plan(
            entries,
            opened,
            now(),
            scope["verification"],
            source_inventory(),
            [],
            parent,
            file_hash(args.parent_plan) if parent else None,
            scope.get("launch_recovery"),
            scope.get("collection_recovery"),
        )
        from orchestrator.moneyflow_continuation.submission import Journal

        observations = backend.snapshots(draft["units"], Journal(draft))
        draft["unrelated_source_changes"] = verification_audit.get(
            "unrelated_source_changes", []
        )
        draft["observations"] = [{**s, "next": next_action(s)} for s in observations]
        validate_plan(draft)
        new_plan_output(args.output, draft)
        return 0, {
            "mode": "plan",
            "complete": False,
            "path": args.output,
            "sha256": file_hash(args.output),
            "units": len(draft["units"]),
        }
    plan = (
        verify_plan_file(args.plan, args.expect_plan_sha256)
        if args.mode in {"apply", "audit"}
        else read_json(args.plan)
    )
    validate_plan(plan)
    if args.mode == "inspect":
        report = inspect(backend, plan)
        return (3 if report["blocked"] or report["unknown"] else 0), report
    if args.mode == "audit":
        from orchestrator.moneyflow_continuation.acceptance import audit

        validate_new_output(args.output)
        code, report = audit(backend, plan)
        report.update(
            plan_path=args.plan,
            plan_sha256=file_hash(args.plan),
            verification=plan["verification"],
            policy=plan["policy"],
        )
        new_plan_output(args.output, report)
        return code, report
    with StopSignals() as stop:
        return apply(backend, plan, stop=stop)


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        from orchestrator.defs.bootstrap.daily_basic_event_instance import (
            daily_basic_event_instance,
        )
        from orchestrator.moneyflow_continuation.state import NativeBackend

        with daily_basic_event_instance() as instance:
            code, report = run(args, NativeBackend(instance))
    except ContinuationError as error:
        code, report = (
            error.code,
            {"mode": args.mode, "complete": False, "reason": error.reason},
        )
    except Exception as error:  # noqa: BLE001 -- CLI boundary reports failure and redacts native diagnostics
        code, report = (
            3,
            {
                "mode": args.mode,
                "complete": False,
                "reason": "io_or_native_error",
                "error_type": type(error).__name__,
            },
        )
    print(encoded(report).decode().strip())
    return code


if __name__ == "__main__":
    raise SystemExit(main())
