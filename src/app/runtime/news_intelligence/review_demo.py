"""Freeze ten real NLI suggestions from existing tutorial facts; no DB access."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

from src.biz.services.wealth.news_intelligence.policy import (
    build_label_candidates, event_type_hypothesis, topic_hypothesis,
)
from src.biz.services.wealth.news_intelligence.review_policy import SUBTOPICS
from src.biz.services.wealth.news_intelligence.review_prelabel import (
    NLI_REVISION, PROMPT_VERSION, SUBTOPIC_TRIGGERS, _literal_matches,
    build_demo_prediction,
)
from .argilla_review import VERSIONS, prepare_review_record
from .artifact_store import AtomicArtifactWriter, REQUIRED_ARTIFACTS, verify_artifact_directory
from .model_runtime import FrozenModelPaths, FrozenModelRuntime
from .resource_monitor import StageResourceMonitor


def prepare_review_demo(*, input_experiment: Path, output_root: Path,
                        experiment_id: str, model_root: Path, code_commit: str,
                        timeout_seconds: float = 900.0) -> Path:
    if not experiment_id or Path(experiment_id).name != experiment_id or experiment_id in {".", ".."}:
        raise ValueError("experiment_id must be a safe path component")
    if (output_root / experiment_id).exists():
        raise FileExistsError("review demo is frozen; refusing to rerun models or overwrite")
    verify_artifact_directory(input_experiment)
    pool = []
    with (input_experiment / "annotation_import.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            pool.append(row)
    # Prefer existing tutorials; the original tutorial pool contains no CCTV.
    # Any selected pilot item becomes exposed TUTORIAL, never independent gold.
    selected = []
    for source, count in (("news", 4), ("major_news", 3), ("cctv_news", 3)):
        group = sorted((r for r in pool if r["fields"]["source_type"] == source),
                       key=lambda r: (r["metadata"].get("sample_group") != "TUTORIAL", r["external_id"]))
        if len(group) < count:
            raise ValueError(f"insufficient frozen pilot samples for {source}")
        selected.extend(group[:count])
    requests = {}
    for row in selected:
        title, content = row["fields"]["title"], row["fields"]["content"]
        premise = title[:80] + "\n" + content[:240]
        candidates = build_label_candidates(title, content)
        hypotheses = [tuple(topic_hypothesis(c) for c in candidates.primary_topics),
                      tuple(event_type_hypothesis(c) for c in candidates.event_types)]
        matched = _literal_matches(title + "\n" + content, SUBTOPIC_TRIGGERS)
        for parent in ("ECONOMY_BUSINESS_FINANCE", "SCIENCE_TECHNOLOGY"):
            paths = [code for code in matched if SUBTOPICS[code][0] == parent][:3]
            hypotheses.append(tuple(f"这条新闻主要报道{SUBTOPICS[c][1]}。" for c in paths))
        for options in hypotheses:
            if options:
                key = (premise, options)
                requests.setdefault(key, f"review-{len(requests)}")
    if not requests:
        raise ValueError("demo has no model candidates; cannot fabricate a model run")
    runtime = FrozenModelRuntime(FrozenModelPaths.from_root(model_root),
                                 lock_path=output_root / ".review-demo-model.lock")
    started = time.monotonic()
    resource_samples = []
    with StageResourceMonitor(resource_samples.append).measure("review_demo_nli"):
        scores = runtime.nli(((request_id, premise, options)
                              for (premise, options), request_id in requests.items()),
                             timeout_seconds=timeout_seconds)
    if set(scores) != set(requests.values()):
        raise ValueError("model returned missing or unexpected request identities")
    imports = []
    for row in selected:
        title, content = row["fields"]["title"], row["fields"]["content"]
        prediction = build_demo_prediction(title=title, content=content,
            infer=lambda premise, options: scores[requests[(premise, options)]])
        task = {"external_id": row["external_id"], "fields": {"title": title, "content": content},
                "metadata": {**VERSIONS, "sample_id": row["external_id"],
                             "input_hash": row["metadata"]["input_hash"],
                             "evaluation_role": "TUTORIAL", "prediction_exposed": True},
                "machine_prediction": prediction}
        prepare_review_record(task)  # Fail before publishing any invalid proposal.
        imports.append(task)
    duration = time.monotonic() - started
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    for path in sorted(Path(__file__).parents[3].joinpath("biz/services/wealth/news_intelligence").glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    with AtomicArtifactWriter(output_root, experiment_id) as writer:
        manifest = {**VERSIONS, "experiment_id": experiment_id, "code_commit": code_commit,
                    "code_tree_sha256": digest.hexdigest(), "model_revision": NLI_REVISION,
                    "prompt_version": PROMPT_VERSION, "input_experiment": str(input_experiment),
                    "input_annotation_sha256": hashlib.sha256((input_experiment / "annotation_import.jsonl").read_bytes()).hexdigest(),
                    "sample_count": 10, "source_counts": dict(Counter(r["fields"]["source_type"] for r in selected)),
                    "nli_requests": len(requests), "wall_seconds": duration,
                    "selected_original_groups": {r["external_id"]: r["metadata"].get("sample_group") for r in selected},
                    "status": "DEMO_ONLY_NOT_QUALITY_ACCEPTANCE", "qwen_calls": 0,
                    "database_access": False, "threshold": 0.5, "importance_status": "NOT_ASSESSED"}
        for name in sorted(REQUIRED_ARTIFACTS):
            if name == "manifest.json":
                writer.write_json(name, manifest)
            elif name == "source_snapshot.jsonl":
                writer.write_jsonl(name, selected)
            elif name == "annotation_import.jsonl":
                writer.write_jsonl(name, imports)
            elif name == "analysis_results.jsonl":
                writer.write_jsonl(name, ({"sample_id": r["external_id"], "machine_prediction": r["machine_prediction"]} for r in imports))
            elif name == "resource_samples.jsonl":
                writer.write_jsonl(name, (asdict(sample) for sample in resource_samples))
            elif name.endswith(".jsonl"):
                writer.write_jsonl(name, [])
            elif name.endswith(".json"):
                writer.write_json(name, {"status": "NOT_EVALUATED", "reason": "ten_sample_demo_only"})
            elif name == "report.md":
                writer.write_text(name, f"# v3 十条审核演示\n\n真实NLI {duration:.2f}秒，{len(requests)}个有界请求。仅教学用途，不是独立质量验收。原文完整展示；模型只看标题/导语，行业及关注方向为字面规则，重要度尚未评估。没有DB访问、Qwen调用或消息发送。\n")
        return writer.commit()
