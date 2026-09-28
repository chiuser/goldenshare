from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
import json
from pathlib import Path
import subprocess

from sqlalchemy.orm import Session

from src.app.runtime.news_intelligence.argilla_exchange import (
    annotation_schema,
    build_argilla_import_record,
)
from src.app.runtime.news_intelligence.artifact_store import AtomicArtifactWriter
from src.app.runtime.news_intelligence.artifact_store import verify_artifact_directory
from src.app.runtime.news_intelligence.model_runtime import (
    FrozenModelPaths,
    FrozenModelRuntime,
)
from src.app.runtime.news_intelligence.resource_monitor import (
    ResourceSample,
    StageResourceMonitor,
)
from src.biz.queries.wealth.news_intelligence.source_query import (
    NewsIntelligenceReplaySourceQuery,
)
from src.biz.services.wealth.news_intelligence.contracts import M1Manifest, as_jsonable
from src.biz.services.wealth.news_intelligence.policy import (
    MODEL_POLICY_VERSION,
    SCORING_VERSION,
    SUMMARY_VERSION,
    TAXONOMY_VERSION,
)
from src.biz.services.wealth.news_intelligence.calibration_pipeline import (
    run_lightweight_pipeline,
)
from src.biz.services.wealth.news_intelligence.replay import (
    build_replay_windows,
    clean_candidate,
    mark_exact_duplicates,
)
from src.biz.services.wealth.news_intelligence.sampling import select_taxonomy_pilot


MODEL_REVISIONS = {
    "embedding": "Qwen/Qwen3-Embedding-0.6B@97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3",
    "classification_nli": "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli@8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c",
    "generation": "Qwen/Qwen3-4B-GGUF@bc640142c66e1fdd12af0bd68f40445458f3869b:Q4_K_M",
}


def prepare_pilot_experiment(
    session: Session,
    *,
    dates: tuple[date, ...],
    output_root: Path,
    experiment_id: str,
    code_commit: str | None = None,
) -> Path:
    if not dates:
        raise ValueError("at least one replay date is required")
    source = NewsIntelligenceReplaySourceQuery(batch_size=500)
    windows = tuple(
        window for day in sorted(set(dates)) for window in build_replay_windows(day)
    )
    by_sample_id = {}
    for window in windows:
        for item in source.stream_timed_window(session, window=window):
            existing = by_sample_id.get(item.sample_id)
            if existing is not None and existing.input_hash != item.input_hash:
                raise RuntimeError(
                    f"source changed inside repeatable-read snapshot: {item.sample_id}"
                )
            by_sample_id[item.sample_id] = item
    for day in sorted(set(dates)):
        for item in source.stream_cctv_date(session, content_date=day):
            existing = by_sample_id.get(item.sample_id)
            if existing is not None and existing.input_hash != item.input_hash:
                raise RuntimeError(
                    f"source changed inside repeatable-read snapshot: {item.sample_id}"
                )
            by_sample_id[item.sample_id] = item

    items = tuple(sorted(by_sample_id.values(), key=lambda item: item.sample_id))
    decisions = mark_exact_duplicates(
        items, tuple(clean_candidate(item) for item in items)
    )
    pilot = select_taxonomy_pilot(items, decisions)
    _assert_pilot_contract(pilot)
    manifest = M1Manifest(
        experiment_id=experiment_id,
        created_at=datetime.now(timezone.utc),
        code_commit=code_commit or _git_commit(),
        query_contract="historical-business-time-v1+cctv-date-cohort-v1",
        taxonomy_version=TAXONOMY_VERSION,
        scoring_version=SCORING_VERSION,
        summary_version=SUMMARY_VERSION,
        model_policy_version=MODEL_POLICY_VERSION,
        windows=windows,
        model_revisions=MODEL_REVISIONS,
        parameters={
            "source_batch_size": 500,
            "tutorial_size": 20,
            "blind_per_source": 40,
            "database_mode": "REPEATABLE_READ_READ_ONLY",
            "production_increment_reconstructed": False,
        },
        notes=(
            "Historical business-time replay is not a reconstruction of Raw-id arrival order.",
            "CCTV records use a date cohort and never receive a fabricated intraday timestamp.",
            "Model execution and human annotation are pending later M1 gates.",
        ),
    )
    counts = Counter(item.source_type.value for item in items)
    report = _pilot_report(experiment_id, counts, decisions, pilot)

    with AtomicArtifactWriter(output_root, experiment_id) as writer:
        writer.write_json("manifest.json", as_jsonable(manifest))
        writer.write_jsonl(
            "source_snapshot.jsonl", (as_jsonable(item) for item in items)
        )
        writer.write_jsonl(
            "candidate_results.jsonl", (as_jsonable(decision) for decision in decisions)
        )
        writer.write_jsonl("event_results.jsonl", ())
        writer.write_jsonl("analysis_results.jsonl", ())
        writer.write_jsonl(
            "annotation_import.jsonl",
            (build_argilla_import_record(selection) for selection in pilot),
        )
        writer.write_jsonl("annotation_export.jsonl", ())
        writer.write_json(
            "classification_metrics.json",
            {"status": "PENDING_ANNOTATION", "annotation_schema": annotation_schema()},
        )
        writer.write_json(
            "clustering_metrics.json", {"status": "PENDING_MODEL_AND_ANNOTATION"}
        )
        writer.write_json(
            "summary_audit.json", {"status": "PENDING_MODEL_AND_ANNOTATION"}
        )
        writer.write_json(
            "ranking_metrics.json", {"status": "PENDING_MODEL_AND_ANNOTATION"}
        )
        writer.write_jsonl("resource_samples.jsonl", ())
        writer.write_text("report.md", report)
        return writer.commit()


def run_calibration_sample_experiment(
    *,
    input_experiment: Path,
    output_root: Path,
    experiment_id: str,
    model_root: Path,
    embedding_timeout_seconds: float,
    nli_timeout_seconds: float,
) -> Path:
    verify_artifact_directory(input_experiment)
    source_records = _read_jsonl(input_experiment / "source_snapshot.jsonl")
    selected_records = _read_jsonl(input_experiment / "annotation_import.jsonl")
    selected_ids = {
        str(record["metadata"]["sample_id"])
        for record in selected_records
        if isinstance(record.get("metadata"), dict)
    }
    items = tuple(
        _frozen_item_from_record(record)
        for record in source_records
        if record.get("sample_id") in selected_ids
    )
    if len(items) != len(selected_ids):
        raise RuntimeError(
            "annotation import references samples missing from the frozen source snapshot"
        )
    paths = FrozenModelPaths.from_root(model_root)
    runtime = FrozenModelRuntime(
        paths, lock_path=paths.runtime_root / "tmp/m1-model.lock"
    )
    resource_samples: list[ResourceSample] = []
    monitor = StageResourceMonitor(resource_samples.append)
    with monitor.measure("calibration_sample_lightweight_pipeline"):
        result = run_lightweight_pipeline(
            items,
            embedding_provider=runtime,
            nli_provider=runtime,
            embedding_timeout_seconds=embedding_timeout_seconds,
            nli_timeout_seconds=nli_timeout_seconds,
        )
    parent_manifest = json.loads(
        (input_experiment / "manifest.json").read_text(encoding="utf-8")
    )
    manifest = {
        **parent_manifest,
        "experiment_id": experiment_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "code_commit": _git_commit(),
        "parent_experiment_id": parent_manifest.get("experiment_id"),
        "stage": "CALIBRATION_SAMPLE_LIGHTWEIGHT_MODELS",
        "parameters": {
            **dict(parent_manifest.get("parameters", {})),
            "embedding_timeout_seconds": embedding_timeout_seconds,
            "nli_timeout_seconds": nli_timeout_seconds,
            "model_input_count": len(items),
            "deep_analysis_limit": 30,
        },
    }
    report = "\n".join(
        (
            f"# News Intelligence M1 lightweight model replay — {experiment_id}",
            "",
            "状态：Embedding、保守事件聚类与分层 NLI 已完成；人工标注、Qwen 深分析和业务准入尚未执行。",
            "",
            f"- input samples: {len(items)}",
            f"- eligible candidates: {sum(candidate.exclusion_code is None for candidate in result.candidates)}",
            f"- events: {len(result.events)}",
            f"- deep-analysis candidates (not executed): {len(result.deep_analysis_event_ids)}",
            "",
            "This result is not a production or M2 admission decision.",
            "",
        )
    )
    with AtomicArtifactWriter(output_root, experiment_id) as writer:
        writer.write_json("manifest.json", manifest)
        writer.write_jsonl(
            "source_snapshot.jsonl", (as_jsonable(item) for item in items)
        )
        writer.write_jsonl(
            "candidate_results.jsonl", (as_jsonable(item) for item in result.candidates)
        )
        writer.write_jsonl(
            "event_results.jsonl", (as_jsonable(item) for item in result.events)
        )
        writer.write_jsonl(
            "analysis_results.jsonl", (as_jsonable(item) for item in result.analyses)
        )
        writer.write_jsonl("annotation_import.jsonl", selected_records)
        writer.write_jsonl("annotation_export.jsonl", ())
        writer.write_json(
            "classification_metrics.json", {"status": "PENDING_ANNOTATION"}
        )
        writer.write_json("clustering_metrics.json", {"status": "PENDING_ANNOTATION"})
        writer.write_json(
            "summary_audit.json", {"status": "PENDING_QWEN_AND_ANNOTATION"}
        )
        writer.write_json("ranking_metrics.json", {"status": "PENDING_ANNOTATION"})
        writer.write_jsonl(
            "resource_samples.jsonl",
            (as_jsonable(sample) for sample in resource_samples),
        )
        writer.write_text("report.md", report)
        return writer.commit()


def _assert_pilot_contract(pilot: tuple[object, ...]) -> None:
    groups = Counter(getattr(selection, "sample_group") for selection in pilot)
    if groups != {"TUTORIAL": 20, "BLIND_PILOT": 120}:
        raise RuntimeError(f"pilot sample contract cannot be satisfied: {dict(groups)}")
    sources = Counter(
        getattr(selection, "item").source_type.value
        for selection in pilot
        if getattr(selection, "sample_group") == "BLIND_PILOT"
    )
    if sources != {"news": 40, "major_news": 40, "cctv_news": 40}:
        raise RuntimeError(f"pilot source quota cannot be satisfied: {dict(sources)}")


def _git_commit() -> str:
    result = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _pilot_report(
    experiment_id: str,
    counts: Counter[str],
    decisions: tuple[object, ...],
    pilot: tuple[object, ...],
) -> str:
    excluded = Counter(
        getattr(decision, "exclusion_code")
        for decision in decisions
        if getattr(decision, "exclusion_code")
    )
    return "\n".join(
        (
            f"# News Intelligence M1 pilot — {experiment_id}",
            "",
            "状态：已冻结历史只读输入和 Argilla 导入包；模型回放、人工标注和质量门禁尚未执行。",
            "",
            "## Source snapshot",
            "",
            *(f"- `{source}`: {count}" for source, count in sorted(counts.items())),
            "",
            "## Deterministic cleaning",
            "",
            f"- candidates: {len(decisions)}",
            f"- exclusions: {dict(sorted(excluded.items()))}",
            "",
            "## Annotation package",
            "",
            f"- records: {len(pilot)}",
            "- tutorial: 20",
            "- blind pilot: 120 (40 per source)",
            "",
            "This report does not claim production incremental reconstruction or model acceptance.",
            "",
        )
    )


def _read_jsonl(path: Path) -> tuple[dict[str, object], ...]:
    output = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path.name}:{line_number} must contain an object")
        output.append(value)
    return tuple(output)


def _frozen_item_from_record(record: dict[str, object]):
    from src.biz.services.wealth.news_intelligence.contracts import (
        FrozenNewsItem,
        NewsSourceType,
    )

    published_at = record.get("published_at")
    content_date = record.get("content_date")
    return FrozenNewsItem(
        sample_id=str(record["sample_id"]),
        source_type=NewsSourceType(str(record["source_type"])),
        source_key=str(record["source_key"]),
        title=str(record["title"]),
        content=str(record["content"]),
        source_name=str(record["source_name"]),
        published_at=datetime.fromisoformat(str(published_at))
        if published_at
        else None,
        content_date=date.fromisoformat(str(content_date)) if content_date else None,
        fetched_at=datetime.fromisoformat(str(record["fetched_at"])),
        input_hash=str(record["input_hash"]),
        replay_assignment=str(record["replay_assignment"]),
    )
