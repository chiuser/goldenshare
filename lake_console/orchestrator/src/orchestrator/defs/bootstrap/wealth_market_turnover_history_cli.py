from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from orchestrator.defs.bootstrap.wealth_market_turnover_history import (
    WEALTH_MARKET_TURNOVER_WMT7_HISTORY_START_DATE,
    audit_wealth_market_turnover_history,
    audit_wealth_market_turnover_history_candidates,
    build_wealth_market_turnover_history_candidates,
    plan_wealth_market_turnover_history,
    promote_wealth_market_turnover_history_candidates,
    publish_wealth_market_turnover_history_to_prod,
    wealth_market_turnover_history_plan_from_dict,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT, DEFAULT_LAKE_STAGING_ROOT
from orchestrator.defs.resources import DuckDBResource, ProdPostgresWriteResource


def main(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage",
        choices=(
            "plan",
            "build-candidates",
            "audit-candidates",
            "promote",
            "formal-audit",
            "prod-publish",
        ),
    )
    parser.add_argument("--lake-root", default=DEFAULT_LAKE_ROOT)
    parser.add_argument("--staging-root", default=DEFAULT_LAKE_STAGING_ROOT)
    parser.add_argument(
        "--start-date",
        default=WEALTH_MARKET_TURNOVER_WMT7_HISTORY_START_DATE,
    )
    parser.add_argument("--end-date")
    parser.add_argument("--partition-keys")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--plan-file")
    parser.add_argument("--candidate-report")
    parser.add_argument("--formal-audit-report")
    parser.add_argument("--confirm-lake-write", action="store_true")
    parser.add_argument("--confirm-prod-write", action="store_true")
    parser.add_argument("--report-dir", default="/private/tmp")
    args = parser.parse_args(argv)

    lake_root = Path(args.lake_root)
    staging_root = Path(args.staging_root)
    requested_keys = _csv_values(args.partition_keys)
    duckdb = DuckDBResource()

    if args.stage == "plan":
        report = plan_wealth_market_turnover_history(
            duckdb_resource=duckdb,
            lake_root=lake_root,
            staging_root=staging_root,
            partition_keys=requested_keys,
            start_date=args.start_date,
            end_date=args.end_date,
            batch_size=args.batch_size,
        ).to_dict()
    else:
        plan = _load_plan(args.plan_file)
        keys = requested_keys or plan.selected_partition_keys[: plan.batch_size]
        if args.stage == "build-candidates":
            _require_confirmation(
                args.confirm_lake_write,
                "build-candidates requires --confirm-lake-write",
            )
            report = build_wealth_market_turnover_history_candidates(
                plan=plan,
                lake_root=lake_root,
                duckdb_resource=duckdb,
                partition_keys=keys,
            ).to_dict()
        elif args.stage == "audit-candidates":
            report = audit_wealth_market_turnover_history_candidates(
                plan=plan,
                lake_root=lake_root,
                duckdb_resource=duckdb,
                partition_keys=keys,
                expected_candidate_hashes=_load_candidate_hashes(
                    args.candidate_report
                ),
            ).to_dict()
        elif args.stage == "promote":
            _require_confirmation(
                args.confirm_lake_write,
                "promote requires --confirm-lake-write",
            )
            report = promote_wealth_market_turnover_history_candidates(
                plan=plan,
                lake_root=lake_root,
                partition_keys=keys,
                candidate_hashes=_load_candidate_hashes(args.candidate_report),
            ).to_dict()
        elif args.stage == "formal-audit":
            report = audit_wealth_market_turnover_history(
                plan=plan,
                lake_root=lake_root,
                duckdb_resource=duckdb,
                partition_keys=keys,
                expected_hashes=_load_candidate_hashes(args.candidate_report),
            ).to_dict()
        elif args.stage == "prod-publish":
            _require_confirmation(
                args.confirm_prod_write,
                "prod-publish requires --confirm-prod-write",
            )
            report = publish_wealth_market_turnover_history_to_prod(
                plan=plan,
                lake_root=lake_root,
                duckdb_resource=duckdb,
                prod_postgres_write=ProdPostgresWriteResource(),
                partition_keys=keys,
                formal_audit_hashes=_load_audit_hashes(
                    args.formal_audit_report
                ),
            ).to_dict()
        else:
            raise ValueError(f"Unsupported stage: {args.stage}")

    output_path = _write_report(args.report_dir, args.stage, report)
    print(output_path)
    return output_path


def _load_plan(plan_file: str | None):
    if not plan_file:
        raise ValueError("WMT-7 history stage requires --plan-file")
    payload = json.loads(Path(plan_file).read_text(encoding="utf-8"))
    return wealth_market_turnover_history_plan_from_dict(payload)


def _load_candidate_hashes(candidate_report: str | None) -> Mapping[str, str]:
    if not candidate_report:
        raise ValueError("WMT-7 history stage requires --candidate-report")
    payload = json.loads(Path(candidate_report).read_text(encoding="utf-8"))
    hashes = payload.get("candidate_hashes")
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("candidate report does not contain candidate_hashes")
    return {str(key): str(value) for key, value in hashes.items()}


def _load_audit_hashes(audit_report: str | None) -> Mapping[str, str]:
    if not audit_report:
        raise ValueError("prod-publish requires --formal-audit-report")
    payload = json.loads(Path(audit_report).read_text(encoding="utf-8"))
    if int(payload.get("failed_partition_count", -1)) != 0:
        raise ValueError("formal audit report is not green")
    partition_audits = payload.get("partition_audits")
    if not isinstance(partition_audits, list) or not partition_audits:
        raise ValueError("formal audit report does not contain partition audits")
    hashes = {
        str(item["partition_key"]): str(item["file_hash"])
        for item in partition_audits
        if isinstance(item, dict)
        and item.get("passed") is True
        and item.get("file_hash")
    }
    if not hashes:
        raise ValueError("formal audit report does not contain green file hashes")
    return hashes


def _require_confirmation(confirmed: bool, message: str) -> None:
    if not confirmed:
        raise ValueError(message)


def _csv_values(value: str | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _write_report(report_dir: str, stage: str, payload: dict[str, object]) -> Path:
    timestamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S")
    output_path = (
        Path(report_dir) / f"wealth_market_turnover_history_{stage}_{timestamp}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return output_path


if __name__ == "__main__":
    main()
