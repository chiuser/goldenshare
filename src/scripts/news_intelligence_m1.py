from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path

from src.app.runtime.news_intelligence.artifact_store import verify_artifact_directory
from src.app.runtime.news_intelligence.argilla_workspace import (
    ArgillaHttpClient,
    export_submitted_annotations,
    import_annotation_tasks,
)
from src.app.runtime.news_intelligence.argilla_review import import_review_tasks, export_reviews
from src.app.runtime.news_intelligence.review_demo import prepare_review_demo
from src.app.runtime.news_intelligence.offline_replay import (
    prepare_pilot_experiment,
    run_calibration_sample_experiment,
)
from src.db import SessionLocal


DEFAULT_OUTPUT_ROOT = Path("/data/disk/goldenshare/news-intelligence/m1")
DEFAULT_ARGILLA_API_URL = "http://127.0.0.1:6900/api/v1"
DEFAULT_ARGILLA_WORKSPACE = "news-intelligence-m1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="新闻智能简报 M1 离线只读回放工具。"
    )
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
    run_sample.add_argument("--code-commit")

    verify = subparsers.add_parser(
        "verify-artifacts", help="校验冻结制品文件集合和 SHA-256。"
    )
    verify.add_argument("path", type=Path)

    argilla_import = subparsers.add_parser(
        "argilla-import",
        help="将冻结的20+120条试标任务幂等导入本机Argilla。",
    )
    _add_argilla_connection_arguments(argilla_import)
    argilla_import.add_argument("--input", required=True, type=Path)

    argilla_export = subparsers.add_parser(
        "argilla-export", help="从本机Argilla导出已提交的版本化标注。"
    )
    _add_argilla_connection_arguments(argilla_export)
    argilla_export.add_argument("--dataset-id", required=True)
    argilla_export.add_argument("--output", required=True, type=Path)
    argilla_export.add_argument("--annotation-round", required=True, type=int)
    review_import = subparsers.add_parser("argilla-review-import", help="导入新版机器辅助或独立审核任务；不覆盖旧集。")
    _add_argilla_connection_arguments(review_import)
    review_import.add_argument("--input", required=True, type=Path)
    review_export = subparsers.add_parser("argilla-review-export", help="导出新版建议、人工响应与最终答案。")
    _add_argilla_connection_arguments(review_export)
    review_export.add_argument("--dataset-id", required=True)
    review_export.add_argument("--output", required=True, type=Path)
    review_export.add_argument("--annotation-round", required=True, type=int)
    review_demo = subparsers.add_parser("prepare-review-demo", help="仅对冻结样本中的10条运行新版NLI预标注。")
    review_demo.add_argument("--input-experiment", required=True, type=Path)
    review_demo.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    review_demo.add_argument("--experiment-id", required=True)
    review_demo.add_argument("--model-root", required=True, type=Path)
    review_demo.add_argument("--code-commit", required=True)
    review_demo.add_argument("--timeout-seconds", type=float, default=900.0)
    return parser


def _add_argilla_connection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--api-url", default=DEFAULT_ARGILLA_API_URL)
    parser.add_argument("--api-key-file", required=True, type=Path)
    parser.add_argument("--workspace", default=DEFAULT_ARGILLA_WORKSPACE)


def _argilla_client(args: argparse.Namespace) -> ArgillaHttpClient:
    api_key = args.api_key_file.read_text(encoding="utf-8").strip()
    return ArgillaHttpClient(api_url=args.api_url, api_key=api_key)


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "prepare-review-demo":
        path = prepare_review_demo(input_experiment=args.input_experiment, output_root=args.output_root,
                                   experiment_id=args.experiment_id, model_root=args.model_root,
                                   code_commit=args.code_commit, timeout_seconds=args.timeout_seconds)
        print(path)
        return 0
    if args.command == "argilla-review-import":
        result = import_review_tasks(client=_argilla_client(args), input_path=args.input, workspace_name=args.workspace)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "argilla-review-export":
        result = export_reviews(client=_argilla_client(args), dataset_id=args.dataset_id, output_path=args.output,
                                annotation_round=args.annotation_round)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
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
            code_commit=args.code_commit,
        )
        print(path)
        return 0
    if args.command == "argilla-import":
        result = import_annotation_tasks(
            client=_argilla_client(args),
            input_path=args.input,
            workspace_name=args.workspace,
        )
        print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "argilla-export":
        result = export_submitted_annotations(
            client=_argilla_client(args),
            dataset_id=args.dataset_id,
            output_path=args.output,
            annotation_round=args.annotation_round,
        )
        payload = asdict(result)
        payload["output_path"] = str(result.output_path)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    raise AssertionError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
