from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

import pytest

from src.app.runtime.news_intelligence.argilla_exchange import (
    build_argilla_import_record,
    normalize_argilla_export,
)
from src.app.runtime.news_intelligence.offline_replay import prepare_pilot_experiment
from src.app.runtime.news_intelligence.artifact_store import (
    REQUIRED_ARTIFACTS,
    ArtifactContractError,
    AtomicArtifactWriter,
    verify_artifact_directory,
)
from src.app.runtime.news_intelligence.model_process import (
    ModelProcessError,
    SerializedModelProcess,
    assert_loopback_url,
)
from src.app.runtime.news_intelligence.model_runtime import (
    FrozenModelPaths,
    _model_worker_path,
)
from src.app.runtime.news_intelligence.model_worker import _entailment_index
from src.biz.services.wealth.news_intelligence.sampling import SampleSelection
from src.biz.services.wealth.news_intelligence.contracts import NewsSourceType
from tests.news_intelligence.test_replay_contracts import _item
from src.biz.services.wealth.news_intelligence.replay import clean_candidate


def test_atomic_artifact_set_and_tamper_detection(tmp_path: Path) -> None:
    with AtomicArtifactWriter(tmp_path, "experiment") as writer:
        for name in REQUIRED_ARTIFACTS:
            if name.endswith(".json"):
                writer.write_json(name, {"status": "test"})
            elif name.endswith(".jsonl"):
                writer.write_jsonl(name, ())
            else:
                writer.write_text(name, "test\n")
        path = writer.commit()
    verify_artifact_directory(path)
    (path / "report.md").write_text("tampered", encoding="utf-8")
    with pytest.raises(ArtifactContractError, match="checksum mismatch"):
        verify_artifact_directory(path)


def test_incomplete_artifact_set_is_not_published(tmp_path: Path) -> None:
    with pytest.raises(ArtifactContractError, match="incomplete"):
        with AtomicArtifactWriter(tmp_path, "incomplete") as writer:
            writer.write_json("manifest.json", {})
            writer.commit()
    assert not (tmp_path / "incomplete").exists()


def test_serialized_model_process_parses_json_and_cleans_lock(tmp_path: Path) -> None:
    runner = SerializedModelProcess(lock_path=tmp_path / "model.lock")
    responses = runner.run(
        (
            sys.executable,
            "-c",
            "import sys; [print(line.strip()) for line in sys.stdin if line.strip()]",
        ),
        ({"sample_id": "one"},),
        timeout_seconds=5,
    )
    assert responses == ({"sample_id": "one"},)
    assert not (tmp_path / "model.lock").exists()


def test_serialized_model_process_times_out_and_cleans_group(tmp_path: Path) -> None:
    runner = SerializedModelProcess(lock_path=tmp_path / "model.lock")
    with pytest.raises(ModelProcessError, match="timed out"):
        runner.run(
            (sys.executable, "-c", "import time; time.sleep(5)"),
            (),
            timeout_seconds=0.1,
        )
    assert not (tmp_path / "model.lock").exists()


def test_only_loopback_model_server_is_allowed() -> None:
    assert_loopback_url("http://127.0.0.1:8080")
    with pytest.raises(ValueError, match="loopback"):
        assert_loopback_url("http://0.0.0.0:8080")


def test_argilla_roundtrip_preserves_stable_identity() -> None:
    item = _item("argilla")
    selection = SampleSelection(
        item=item,
        decision=clean_candidate(item),
        sample_group="BLIND_PILOT",
        stratum="news:SHORT",
        selection_probability=0.5,
        enrichment_reason=None,
    )
    imported = build_argilla_import_record(selection)
    exported = normalize_argilla_export(
        {
            "metadata": imported["metadata"],
            "response": {"primary_topic": "ECONOMY_BUSINESS_FINANCE"},
        },
        reviewer_id="reviewer-1",
        annotation_round=1,
    )
    assert exported["sample_id"] == item.sample_id
    assert exported["input_hash"] == item.input_hash


def test_frozen_model_paths_match_m0_layout(tmp_path: Path) -> None:
    paths = FrozenModelPaths.from_root(tmp_path)
    assert paths.python == tmp_path / "runtime/python-3.13-m0-v1/venv/bin/python"
    assert paths.nli_onnx.name == "model_quantized.onnx"
    assert paths.llama_server.name == "llama-server"
    assert paths.qwen_model.name == "Qwen3-4B-Q4_K_M.gguf"
    assert _model_worker_path().name == "model_worker.py"
    assert _model_worker_path().is_file()


def test_nli_entailment_index_comes_from_frozen_model_config(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text(
        '{"id2label":{"0":"entailment","1":"neutral","2":"contradiction"}}',
        encoding="utf-8",
    )
    assert _entailment_index(tmp_path) == 0


def test_prepare_pilot_publishes_exact_annotation_contract(
    tmp_path: Path, monkeypatch
) -> None:
    class FakeSourceQuery:
        def __init__(self, *, batch_size):
            assert batch_size == 500

        def stream_timed_window(self, session, *, window):
            if window.end_at.hour != 8:
                return iter(())
            news = tuple(
                _item(f"news-{index}", title=f"news {index}") for index in range(80)
            )
            major = tuple(
                _item(
                    f"major-{index}",
                    source_type=NewsSourceType.MAJOR_NEWS,
                    title=f"major {index}",
                )
                for index in range(80)
            )
            return iter(news + major)

        def stream_cctv_date(self, session, *, content_date):
            return iter(
                tuple(
                    _item(
                        f"cctv-{index}",
                        source_type=NewsSourceType.CCTV_NEWS,
                        title=f"cctv {index}",
                    )
                    for index in range(80)
                )
            )

    monkeypatch.setattr(
        "src.app.runtime.news_intelligence.offline_replay.NewsIntelligenceReplaySourceQuery",
        FakeSourceQuery,
    )
    path = prepare_pilot_experiment(
        object(),
        dates=(date(2026, 9, 20),),
        output_root=tmp_path,
        experiment_id="pilot",
        code_commit="deadbeef",
    )
    verify_artifact_directory(path)
    records = [
        line
        for line in (path / "annotation_import.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    assert len(records) == 140
