"""Controlled P9 runless events for rebuilt China-A minute Gold assets."""

from __future__ import annotations

import argparse
from pathlib import Path

import dagster as dg

from orchestrator.defs.bootstrap.cn_a_minute_gold_p9_events import (
    P9_FAMILIES,
    P9Evidence,
    apply_p9_family,
    build_p9_plan,
    post_audit_p9_family,
    write_p9_report,
)
from orchestrator.defs.paths import DEFAULT_LAKE_ROOT

_P6 = Path("/private/tmp/cn_a_minute_gold_p6")
_P7 = Path("/private/tmp/cn_a_minute_gold_p7")
_P8 = Path("/private/tmp/cn_a_minute_gold_p8")
_P8_STAGING = Path("/Volumes/datasource/data_lake_staging/cn_a_minute_gold_p8")
_P6_INDEX_HASH = "f79f609a83f2ce978745a930476496ad6176c603d804993d6ecf0d43be6781e1"
_P6_MAJOR_HASH = "8f131a9f7412c5bdd226e6709f128ba13f6a44e7be3ace2b531778e57f682159"
_P6_TECH_HASH = "d49b1f4bccb403f5057c340d76d76f003d94f2b08fef4df197274ed9e9c91c41"
_P7_STOCK_HASH = "c8b53c333d5a969488171b4da4eca9a444aaba54c1a69e113464773f831ea099"


def default_evidence() -> P9Evidence:
    stock_audits = tuple(
        _P7 / f"formal_audit_freq_{freq}_{_P7_STOCK_HASH}.json"
        for freq in (5, 15, 30, 60)
    )
    indicator_audits = (
        *(_P8 / f"audit_5m_{year}_v2_stdout.txt" for year in range(2014, 2026)),
        _P8 / "audit_5m_2026_v3_stdout.txt",
        _P8 / "audit_15m_full_v3_stdout.txt",
        _P8 / "audit_30m_full_v3_stdout.txt",
        _P8 / "audit_60m_full_v3_stdout.txt",
    )
    return P9Evidence(
        p6_summary=_P6 / "p6_execution_summary_20260813.json",
        index_plan=_P6 / f"index_mins_gold_plan_{_P6_INDEX_HASH}.json",
        index_formal_audit=_P6 / f"index_mins_gold_formal_audit_{_P6_INDEX_HASH}.json",
        major_plan=_P6 / f"major_index_mins_gold_plan_{_P6_MAJOR_HASH}.json",
        major_formal_audit=_P6
        / f"major_index_mins_gold_formal_audit_{_P6_MAJOR_HASH}.json",
        major_technical_plan=_P6
        / f"major_index_mins_technical_bootstrap_plan_{_P6_TECH_HASH}.json",
        major_technical_promote=_P6
        / f"major_index_mins_technical_promote_{_P6_TECH_HASH}.json",
        major_technical_formal_audit=_P6
        / f"major_index_mins_technical_formal_audit_{_P6_TECH_HASH}.json",
        stock_plan=_P7 / f"plan_{_P7_STOCK_HASH}.json",
        stock_formal_audits=stock_audits,
        stock_indicator_audits=indicator_audits,
        stock_indicator_checkpoints=(
            _P8_STAGING / "rebuild_5m_checkpoint.json",
            _P8_STAGING / "rebuild_15m_v3_full_checkpoint.json",
            _P8_STAGING / "rebuild_30m_v3_full_checkpoint.json",
            _P8_STAGING / "rebuild_60m_v3_full_checkpoint.json",
        ),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("dry-run", "apply", "post-audit"))
    parser.add_argument("--lake-root", type=Path, default=Path(DEFAULT_LAKE_ROOT))
    parser.add_argument("--family", choices=P9_FAMILIES)
    parser.add_argument("--expected-plan-hash")
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-event-write", action="store_true")
    return parser


def _validate(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.command == "dry-run":
        if (
            args.family
            or args.expected_plan_hash
            or args.checkpoint
            or args.confirm_event_write
        ):
            parser.error("dry-run does not accept apply/post-audit arguments")
        return
    if not args.family or not args.expected_plan_hash or args.checkpoint is None:
        parser.error(
            f"{args.command} requires --family, --expected-plan-hash and --checkpoint"
        )
    if args.command == "apply" and not args.confirm_event_write:
        parser.error("apply requires --confirm-event-write")
    if args.command == "post-audit" and args.confirm_event_write:
        parser.error("post-audit does not accept --confirm-event-write")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    _validate(parser, args)
    instance = dg.DagsterInstance.get()
    plan = build_p9_plan(
        instance=instance,
        evidence=default_evidence(),
        lake_root=args.lake_root,
        families=P9_FAMILIES if args.command == "dry-run" else (args.family,),
    )
    if args.command == "dry-run":
        report = plan
    elif args.command == "apply":
        report = apply_p9_family(
            instance=instance,
            plan=plan,
            family=args.family,
            checkpoint_path=args.checkpoint,
            expected_plan_hash=args.expected_plan_hash,
        )
    else:
        report = post_audit_p9_family(
            instance=instance,
            plan=plan,
            family=args.family,
            checkpoint_path=args.checkpoint,
            expected_plan_hash=args.expected_plan_hash,
        )
    write_p9_report(report, args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
