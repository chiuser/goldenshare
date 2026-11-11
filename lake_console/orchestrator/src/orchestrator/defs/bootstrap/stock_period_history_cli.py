"""Direct-source period bootstrap. Default is read-only preparation; apply is explicit."""

from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path
from urllib.parse import urlparse

from orchestrator.defs.bootstrap.stock_period_history import (
    load_scope,
    replay_events,
    report_bootstrap_events,
    roots,
    run_period,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.run_contracts.stock_period import (
    VERSION,
    StockPeriodPolicy,
    execution_id,
    source_period,
)


def _run_reporting(instance, operation):
    """One real run for all checks in an explicit CLI operation."""
    import dagster as dg

    @dg.op
    def report(context):
        return operation(context)

    @dg.job(name="stock_period_event_report")
    def reporting():
        report()

    result = reporting.execute_in_process(instance=instance)
    return result.output_for_node("report")


def parse_maintenance_args(argv):
    parser = argparse.ArgumentParser(
        description="Submit explicit stock weekly/monthly maintenance."
    )
    parser.add_argument(
        "--intent",
        required=True,
        choices=("factor_changed", "specified_history", "identity_maintenance"),
    )
    parser.add_argument("--business-date", required=True)
    parser.add_argument(
        "--frequency", action="append", choices=("week", "month"), default=[]
    )
    parser.add_argument("--stock-code", action="append", default=[])
    parser.add_argument(
        "--upstream-completion", action="append", type=json.loads, default=[]
    )
    parser.add_argument("--remove-key", action="append", default=[])
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--remote")
    parser.add_argument("--repository-location")
    parser.add_argument("--repository")
    args = parser.parse_args(argv)
    if args.submit and not all(
        (args.remote, args.repository_location, args.repository)
    ):
        parser.error(
            "--submit requires --remote, --repository-location and --repository"
        )
    if args.intent == "factor_changed" and (
        args.frequency or args.stock_code or args.remove_key
    ):
        parser.error("factor_changed derives codes and both frequencies")
    if len(set(args.frequency)) != len(args.frequency):
        parser.error("duplicate frequency")
    return args


def build_maintenance_request(args):
    from orchestrator.defs.run_contracts.stock_period_history_repair import (
        FREQUENCIES,
        JOB_NAME,
        StockPeriodHistoryRepairConfig,
        build_history_repair_run_config,
        normalize_remove_keys,
    )
    from orchestrator.defs.stock_daily_qfq import (
        gold_stock_daily_qfq_factor_repair_codes_hash,
    )

    frequencies = (
        FREQUENCIES
        if args.intent == "factor_changed"
        else [f for f in FREQUENCIES if f in args.frequency]
    )
    keys = []
    for value in args.remove_key:
        parts = value.split(",")
        if len(parts) != 3:
            raise ValueError("period_maintenance_remove_key_invalid")
        keys.append(dict(zip(("ts_code", "trade_date", "freq"), parts, strict=True)))
    codes = sorted({code.strip().upper() for code in args.stock_code})
    references = args.upstream_completion
    if args.intent == "factor_changed":
        from orchestrator.defs.stock_period_history_repair import (
            load_factor_changed_codes,
        )

        codes = load_factor_changed_codes(Path(DEFAULT_LAKE_ROOT), args.business_date)
        references = sorted(references, key=lambda r: FREQUENCIES.index(r["freq"]))
    config = StockPeriodHistoryRepairConfig(
        intent=args.intent,
        business_date=args.business_date,
        stock_codes=codes,
        codes_hash=gold_stock_daily_qfq_factor_repair_codes_hash(codes),
        frequencies=frequencies,
        upstream_completions=references,
        remove_keys=normalize_remove_keys(keys),
    )
    run_config = build_history_repair_run_config(config)
    return {
        "job_name": JOB_NAME,
        "run_config": run_config,
        "submitted": False,
        "stock_codes": codes,
        "codes_hash": config.codes_hash,
        "frequencies": frequencies,
        "source_units": len(codes) * len(frequencies),
        "remove_key_count": len(config.remove_keys),
        "remove_keys_hash": config.remove_keys_hash,
        "file_count": "尚待源定位"
        if codes
        else len(
            {
                (k["freq"], source_period(k["trade_date"], k["freq"]))
                for k in config.remove_keys
            }
        ),
    }


def submit_maintenance_request(args, request):
    from dagster_graphql import DagsterGraphQLClient

    remote = urlparse(args.remote)
    if (
        remote.scheme not in ("http", "https")
        or not remote.hostname
        or remote.path not in ("", "/")
        or remote.query
        or remote.fragment
        or remote.username
        or remote.password
    ):
        raise ValueError("period_maintenance_remote_origin_invalid")
    client = DagsterGraphQLClient(
        remote.hostname, port_number=remote.port, use_https=remote.scheme == "https"
    )
    run_id = client.submit_job_execution(
        request["job_name"],
        repository_location_name=args.repository_location,
        repository_name=args.repository,
        run_config=request["run_config"],
    )
    return {**request, "submitted": True, "run_id": run_id}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "maintain":
        args = parse_maintenance_args(argv[1:])
        request = build_maintenance_request(args)
        if args.submit:
            request = submit_maintenance_request(args, request)
        print(json.dumps(request, ensure_ascii=False))
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("prepare", "apply", "resume", "events"),
        nargs="?",
        default="prepare",
    )
    parser.add_argument("--lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT))
    parser.add_argument(
        "--staging-root", type=Path, default=Path(DEFAULT_LAKE_STAGING_ROOT)
    )
    parser.add_argument("--request-id")
    parser.add_argument("--run-id")
    parser.add_argument("--confirm-delete-existing", action="store_true")
    parser.add_argument(
        "--rss-limit-gib",
        type=int,
        help="Override process RSS for an existing bootstrap resume (positive GiB).",
    )
    args = parser.parse_args(argv)
    if args.rss_limit_gib is not None and (
        args.action not in ("resume",) or args.rss_limit_gib <= 0
    ):
        parser.error("--rss-limit-gib requires resume and a positive integer")
    root, staging = roots(args.lake_root, args.staging_root)
    if args.action == "prepare":
        print(
            json.dumps(
                {
                    "mode": "bootstrap",
                    "roots": [
                        str(root / "raw/tushare/stk_period_bar_adj_week"),
                        str(root / "raw/tushare/stk_period_bar_adj_month"),
                    ],
                    "request_id": args.request_id,
                    "applied": False,
                }
            )
        )
        return 0
    if args.action == "apply" and (
        not args.confirm_delete_existing or not args.request_id
    ):
        parser.error("apply requires --request-id and --confirm-delete-existing")
    if args.action == "apply":
        from orchestrator.defs.io.stock_period_raw import read_json

        manifest = (
            staging
            / "stock_period/runs"
            / execution_id(args.request_id)
            / "manifest.json"
        )
        if manifest.is_file() and read_json(manifest)["phase"] in (
            "files_complete",
            "events_complete",
        ):
            parser.error(
                "apply cannot restart completed bootstrap files; use events to verify and register them"
            )
    frozen = None
    if args.action in ("resume", "events"):
        import re

        from orchestrator.defs.io.stock_period_raw import read_json
        from orchestrator.defs.run_contracts.stock_period import verify_execution

        if not args.run_id or not re.fullmatch(r"[0-9a-f]{64}", args.run_id):
            parser.error("resume/events require --run-id")
        frozen = read_json(
            staging / "stock_period" / "runs" / args.run_id / "manifest.json"
        )
        verify_execution(frozen, args.run_id)
        if frozen["identity"]["root"] != str(root):
            raise ValueError("period_resume_identity_changed")
        if frozen["identity"]["intent"]["mode"] != "bootstrap":
            parser.error("resume/events require an existing bootstrap")
        if args.action == "events" and frozen["phase"] not in (
            "files_complete",
            "events_complete",
        ):
            raise ValueError("period_event_files_incomplete")
        if args.action == "resume" and frozen["phase"] in (
            "files_complete",
            "events_complete",
        ):
            raise ValueError(
                "period_delivery_events_required:use_existing_events_action"
            )
        if frozen["phase"] == "deleting" and not args.confirm_delete_existing:
            parser.error("resume deletion requires --confirm-delete-existing")
    interrupted = False

    def cancel(signum, frame):
        nonlocal interrupted
        interrupted = True

    previous = {s: signal.signal(s, cancel) for s in (signal.SIGINT, signal.SIGTERM)}
    instance = None
    try:
        if frozen is None:
            listed, aliases = load_scope(root, staging / "stock_period" / "scope")
            intent = {
                "version": VERSION,
                "mode": "bootstrap",
                "frequencies": ["week", "month"],
                "codes": sorted(listed),
                "request_id": args.request_id,
            }
        else:
            listed = set(frozen["identity"]["listed"])
            aliases = frozen["identity"]["aliases"]
            intent = frozen["identity"]["intent"]
        if args.action == "events":
            import dagster as dg

            instance = dg.DagsterInstance.get()

            def operation(context):
                return replay_events(
                    staging / "stock_period/runs" / args.run_id,
                    root=root,
                    staging=staging,
                    events=lambda files: report_bootstrap_events(
                        instance, context, files, cancel=lambda: interrupted
                    ),
                    cancel=lambda: interrupted,
                )

            result = _run_reporting(instance, operation)
        else:
            result = run_period(
                root=root,
                staging=staging,
                listed=listed,
                aliases=aliases,
                intent=intent,
                policy=StockPeriodPolicy(**frozen["identity"]["policy"])
                if frozen
                else StockPeriodPolicy(),
                runtime_rss_bytes=args.rss_limit_gib * 1024**3
                if args.rss_limit_gib is not None
                else None,
                cancel=lambda: interrupted,
                progress=lambda event: print(json.dumps(event), flush=True),
            )
        print(
            json.dumps(
                {
                    "run_id": result["run_id"],
                    "files": len(result["files"]),
                    "events_reported": result.get("events_complete", False),
                }
            )
        )
    finally:
        if instance is not None:
            instance.dispose()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
