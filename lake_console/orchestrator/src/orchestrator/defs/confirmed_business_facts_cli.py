"""Local operator commands for DG confirmed facts."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import UUID

import psycopg2

from orchestrator.defs.confirmed_business_facts import (
    SHANGHAI,
    ConfirmedFactsError,
    Evidence,
    FactDetails,
    FactType,
    connect_confirmed_facts,
    correct_fact,
    find_effective_facts,
    list_fact_history,
    register_fact,
    resolve_fund_status,
    revoke_fact,
    validate_etf_code,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="维护 DG 已确认的业务事实。")
    commands = parser.add_subparsers(dest="command", required=True)
    register = commands.add_parser("register", help="登记一条有公告依据的事实。")
    register.add_argument("--subject-key", required=True, type=validate_etf_code)
    register.add_argument(
        "--fact-type", required=True, type=FactType, choices=tuple(FactType)
    )
    correct = commands.add_parser("correct", help="更正已有事实。")
    revoke = commands.add_parser("revoke", help="撤销已有事实。")
    for command in (correct, revoke):
        command.add_argument("--fact-id", type=UUID, required=True)
        command.add_argument("--expected-revision", type=int, required=True)
    for command in (register, correct):
        command.add_argument("--effective-from", type=date.fromisoformat, required=True)
        command.add_argument("--effective-until", type=date.fromisoformat)
    for command in (register, correct, revoke):
        command.add_argument("--reason", required=True)
        command.add_argument(
            "--evidence",
            action="append",
            nargs="+",
            default=[],
            metavar="证据",
            help="发布机构 URL [公告编号]。可重复填写。",
        )
    history = commands.add_parser("history", help="查询登记、更正和撤销历史。")
    key = history.add_mutually_exclusive_group(required=True)
    key.add_argument("--fact-id", type=UUID)
    key.add_argument("--subject-key", type=validate_etf_code)
    history.add_argument("--limit", type=int, default=50)
    history.add_argument("--offset", type=int, default=0)
    status = commands.add_parser(
        "fund-status", help="按日期查看 ETF 来源状态和 DG 状态。"
    )
    status.add_argument("--subject-key", required=True, type=validate_etf_code)
    status.add_argument("--date", type=date.fromisoformat, required=True)
    status.add_argument(
        "--basic-reference",
        type=Path,
        help="历史日期使用原运行保存的 Basic 引用 JSON。",
    )
    return parser


def _evidence(values: list[list[str]]) -> tuple[Evidence, ...]:
    for fields in values:
        if len(fields) not in {2, 3}:
            raise ConfirmedFactsError("每条证据须为发布机构、URL 和可选公告编号。")
    return tuple(Evidence(*fields) for fields in values)


def _modify(args: argparse.Namespace) -> dict:
    evidence = _evidence(args.evidence)
    with connect_confirmed_facts(writable=True) as db:
        if args.command == "revoke":
            result = revoke_fact(
                db,
                fact_id=str(args.fact_id),
                expected_revision=args.expected_revision,
                reason=args.reason,
                evidence=evidence,
            )
        else:
            details = FactDetails(
                args.effective_from, args.effective_until, evidence, args.reason
            )
            if args.command == "register":
                result = register_fact(
                    db,
                    subject_key=args.subject_key,
                    fact_type=args.fact_type,
                    details=details,
                )
            else:
                result = correct_fact(
                    db,
                    fact_id=str(args.fact_id),
                    expected_revision=args.expected_revision,
                    details=details,
                )
    return asdict(result)


def _fund_status(args: argparse.Namespace, lake_root: Path) -> dict:
    import dagster as dg

    from orchestrator.defs.asset_guards.etf_basic_readiness import (
        EtfBasicReadinessError,
        select_latest_etf_basic_snapshot_reference,
    )
    from orchestrator.defs.io.etf_daily_silver_writer import (
        validate_etf_daily_basic_reference,
    )
    from orchestrator.defs.resources import DuckDBResource
    from orchestrator.defs.run_contracts.etf_basic import (
        EtfBasicSilverSnapshotReference,
    )

    today = datetime.now(SHANGHAI).date()
    if args.date == today and args.basic_reference is not None:
        raise ConfirmedFactsError("查询当天状态使用最新已核验的 ETF 基础信息。")
    if args.basic_reference is None and args.date != today:
        raise ConfirmedFactsError("历史日期查询须提供原运行的 --basic-reference。")
    with connect_confirmed_facts() as db:
        facts = find_effective_facts(
            db,
            subject_type="etf",
            fact_types=tuple(FactType),
            window_start=args.date,
            window_end_exclusive=args.date + timedelta(days=1),
            subject_keys=(args.subject_key,),
        )

    duckdb_resource = DuckDBResource()
    if args.basic_reference is None:
        try:
            with dg.DagsterInstance.get() as instance:
                reference = select_latest_etf_basic_snapshot_reference(
                    instance=instance,
                    lake_root_path=lake_root,
                    duckdb_resource=duckdb_resource,
                    eligibility_as_of=today,
                    required_freshness_date=today,
                )
        except EtfBasicReadinessError as error:
            raise ConfirmedFactsError(f"当日 ETF 基础信息未通过核验。{error}") from None
    else:
        reference = validate_etf_daily_basic_reference(
            lake_root_path=lake_root,
            duckdb_resource=duckdb_resource,
            basic_reference=EtfBasicSilverSnapshotReference.model_validate_json(
                args.basic_reference.read_text(encoding="utf-8")
            ),
        )
    with duckdb_resource.connect() as db:
        row = db.execute(
            "SELECT list_status FROM read_parquet(?, hive_partitioning=false) WHERE ts_code = ?",
            [reference.silver_uri, args.subject_key],
        ).fetchone()
    result = resolve_fund_status(
        subject_key=args.subject_key,
        business_date=args.date,
        source_status=row[0] if row is not None else None,
        effective_facts=facts,
    )
    return {
        **asdict(result),
        "basic_reference_fingerprint": reference.reference_fingerprint,
    }


def _json_date(value: date | datetime) -> str:
    if isinstance(value, datetime):
        return value.astimezone(SHANGHAI).isoformat()
    return value.isoformat()


def main(
    argv: list[str] | None = None, *, lake_root: Path = Path(DEFAULT_LAKE_ROOT)
) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "history":
            with connect_confirmed_facts() as db:
                facts = list_fact_history(
                    db,
                    fact_id=str(args.fact_id) if args.fact_id else None,
                    subject_key=args.subject_key,
                    limit=args.limit,
                    offset=args.offset,
                )
            result = [asdict(fact) for fact in facts]
        elif args.command == "fund-status":
            result = _fund_status(args, lake_root)
        else:
            result = _modify(args)
    except (ValueError, OSError) as error:
        parser.exit(1, f"{error}\n")
    except psycopg2.Error as error:
        parser.exit(1, f"业务事实登记库操作失败（{type(error).__name__}）。\n")
    print(json.dumps(result, default=_json_date, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
