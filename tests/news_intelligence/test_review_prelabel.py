import json

import pytest

from src.app.runtime.news_intelligence.artifact_store import AtomicArtifactWriter, REQUIRED_ARTIFACTS, verify_artifact_directory
from src.app.runtime.news_intelligence.review_demo import prepare_review_demo
from src.biz.services.wealth.news_intelligence.review_prelabel import build_demo_prediction


def test_demo_uses_nli_and_separates_company_topic_from_chip_interest():
    calls = []

    def infer(premise, hypotheses):
        calls.append(hypotheses)
        return tuple(0.9 if ("经济、商业" in h or "公司与机构经营" in h or "财报" in h) else 0.1 for h in hypotheses)

    pred = build_demo_prediction(title="芯片公司财报", content="芯片公司公布财报，净利润增长。", infer=infer)
    assert pred["values"]["topic_path"] == "ECONOMY.BUSINESS_OPERATIONS"
    assert pred["values"]["industries"] == ["ELECTRONICS_SEMICONDUCTORS"]
    assert pred["values"]["interest_tags"] == ["SEMICONDUCTORS"]
    assert pred["values"]["importance_tier"] == "UNKNOWN"
    assert pred["importance_status"] == "NOT_ASSESSED"
    assert calls and max(map(len, calls)) <= 6
    assert pred["evidence"]["industries"]["source"] == "RULE"
    assert pred["evidence"]["topic_path"]["source"] == "MODEL"


@pytest.mark.parametrize("scores", [(), (float("nan"),), (2.0,)])
def test_bad_model_scores_fail_explicitly(scores):
    with pytest.raises(ValueError):
        build_demo_prediction(title="央行降息", content="央行宣布降息。", infer=lambda *args: scores)


def test_freeze_ten_only_with_fake_model_and_no_database(tmp_path, monkeypatch):
    from src.app.runtime.news_intelligence import review_demo

    class FakeRuntime:
        def __init__(self, *args, **kwargs):
            pass

        def nli(self, requests, **kwargs):
            result = {}
            for request_id, premise, hypotheses in requests:
                assert len(hypotheses) <= 6
                result[request_id] = tuple(0.8 for _ in hypotheses)
            return result

    monkeypatch.setattr(review_demo, "FrozenModelRuntime", FakeRuntime)
    records = []
    for source, size in (("news", 8), ("major_news", 7), ("cctv_news", 5)):
        for index in range(size):
            sample_id = f"m1:{source}:{index}"
            records.append({"external_id": sample_id, "fields": {"title": "芯片公司财报", "content": "芯片公司发布财报，利润增长。", "source_type": source},
                            "metadata": {"input_hash": "a" * 64, "sample_group": "BLIND_PILOT" if source == "cctv_news" else "TUTORIAL"}})
    with AtomicArtifactWriter(tmp_path, "input") as writer:
        for name in REQUIRED_ARTIFACTS:
            if name == "annotation_import.jsonl":
                writer.write_jsonl(name, records)
            elif name.endswith(".jsonl"):
                writer.write_jsonl(name, [])
            elif name.endswith(".json"):
                writer.write_json(name, {})
            else:
                writer.write_text(name, "test fixture")
        frozen = writer.commit()
    output = prepare_review_demo(input_experiment=frozen, output_root=tmp_path, experiment_id="demo",
                                 model_root=tmp_path, code_commit="fake-only")
    verify_artifact_directory(output)
    manifest = json.loads((output / "manifest.json").read_text())
    imports = [json.loads(line) for line in (output / "annotation_import.jsonl").read_text().splitlines()]
    assert manifest["sample_count"] == len(imports) == 10
    assert manifest["source_counts"] == {"news": 4, "major_news": 3, "cctv_news": 3}
    assert manifest["qwen_calls"] == 0 and manifest["database_access"] is False
    assert all(row["metadata"]["evaluation_role"] == "TUTORIAL" for row in imports)
    assert all(row["metadata"]["prediction_exposed"] for row in imports)
    assert json.loads((output / "classification_metrics.json").read_text())["status"] == "NOT_EVALUATED"
    with pytest.raises(FileExistsError):
        prepare_review_demo(input_experiment=frozen, output_root=tmp_path, experiment_id="demo",
                            model_root=tmp_path, code_commit="fake-only")
