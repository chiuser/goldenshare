from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from src.app.runtime.news_intelligence.artifact_store import verify_artifact_directory
from src.app.runtime.news_intelligence.offline_replay import (
    prepare_pilot_experiment,
    run_calibration_sample_experiment,
)
from src.db import SessionLocal


DEFAULT_OUTPUT_ROOT = Path("/data/disk/goldenshare/news-intelligence/m1")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="新闻智能简报 M1 离线只读回放工具。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser(
        "prepare-pilot", help="冻结历史事实并生成 20+120 条试标包。"
    )
    prepare.add_argument(
        "--date", action="append", required=True, type=date.fromisoformat, dest="dates"
    )
    prepare.add_argument("--experiment-id", required=True)
    prepare.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    prepare.add_argument("--code-commit")

    run_sample = subparsers.add_parser(
        "run-calibration-sample",
        help="仅对冻结试标样本运行 Embedding、聚类和分层 NLI。",
    )
    run_sample.add_argument("--input-experiment", required=True, type=Path)
    run_sample.add_argument("--experiment-id", required=True)
    run_sample.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    run_sample.add_argument("--model-root", required=True, type=Path)
    run_sample.add_argument("--embedding-timeout-seconds", type=float, default=3_600.0)
    run_sample.add_argument("--nli-timeout-seconds", type=float, default=3_600.0)

    verify = subparsers.add_parser(
        "verify-artifacts", help="校验冻结制品文件集合和 SHA-256。"
    )
    verify.add_argument("path", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "verify-artifacts":
        verify_artifact_directory(args.path)
        print(f"verified: {args.path}")
        return 0
    if args.command == "prepare-pilot":
        session = SessionLocal()
        try:
            path = prepare_pilot_experiment(
                session,
                dates=tuple(args.dates),
                output_root=args.output_root,
                experiment_id=args.experiment_id,
                code_commit=args.code_commit,
            )
        finally:
            session.rollback()
            session.close()
        print(path)
        return 0
    if args.command == "run-calibration-sample":
        path = run_calibration_sample_experiment(
            input_experiment=args.input_experiment,
            output_root=args.output_root,
            experiment_id=args.experiment_id,
            model_root=args.model_root,
            embedding_timeout_seconds=args.embedding_timeout_seconds,
            nli_timeout_seconds=args.nli_timeout_seconds,
        )
        print(path)
        return 0
    raise AssertionError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
