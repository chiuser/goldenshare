import json

import pytest

from src.app.runtime.news_intelligence.artifact_store import AtomicArtifactWriter, REQUIRED_ARTIFACTS, verify_artifact_directory
from src.app.runtime.news_intelligence.review_demo import prepare_review_demo
from src.biz.services.wealth.news_intelligence.review_prelabel import build_demo_prediction, build_review_input
from src.biz.services.wealth.news_intelligence.policy import build_label_candidates


@pytest.mark.parametrize('text', [
    '财政部：全国一般公共预算收入同比增长，重点支持就业工资支出。',
    '布伦特原油价格走高，俄罗斯ESPO混合原油升至每桶120美元。',
    '南非兰特兑美元日内跌幅扩大至1%。',
])
def test_real_missed_economic_cases_recall_candidates_without_forcing_model_answer(text):
    candidates = build_label_candidates('', text)
    assert 'ECONOMY_BUSINESS_FINANCE' in candidates.primary_topics
    assert len(candidates.primary_topics) <= 4 and len(candidates.event_types) <= 6
    pred = build_demo_prediction(title='', content=text,
                                 infer=lambda premise, options: tuple(0.1 for _ in options))
    assert pred['values']['classification_status'] == 'UNRESOLVED'
    assert pred['values']['topic_path'] is None


def test_budget_release_event_recall_does_not_turn_every_fiscal_policy_into_data_release():
    assert 'MACRO_DATA_RELEASE' in build_label_candidates('', '全国公共预算收入同比增长5.7%。').event_types
    assert 'MACRO_DATA_RELEASE' not in build_label_candidates('', '会议讨论财政政策改革。').event_types


def test_visible_input_is_cleaned_before_truncation_and_never_uses_attributes():
    raw = '<div data-hint="人工智能 软件 央行" class="' + 'x' * 400 + '">芯片公司发布财报，净利润增长。</div>'
    title, content, premise = build_review_input('芯片公司财报', raw)
    assert premise == '芯片公司财报\n芯片公司发布财报，净利润增长。'
    assert len(premise) <= 321
    seen = []
    pred = build_demo_prediction(title=title, content=raw,
        infer=lambda text, options: (seen.append(text) or tuple(0.8 for _ in options)))
    assert all(text == premise for text in seen)
    assert pred['values']['interest_tags'] == ['SEMICONDUCTORS']
    assert 'SOFTWARE_SECURITY' not in pred['values']['interest_tags']


def test_code_comments_and_html_entities_do_not_become_fake_raw_quotes():
    raw = '<style>人工智能 软件</style><!--央行--><script>大模型</script><p>半导&#20307;公司发布财报。</p>'
    assert build_review_input('', raw)[1] == '半导体公司发布财报。'
    pred = build_demo_prediction(title='', content=raw, infer=lambda text, options: tuple(0.8 for _ in options))
    assert pred['values']['interest_tags'] == ['SEMICONDUCTORS']
    assert all(entry['quote'] in raw for entry in pred['evidence'].values())


@pytest.mark.parametrize('content', ['', '<script>人工智能</script>', '<img src="芯片.png">'])
def test_no_visible_news_never_calls_a_model(content):
    def forbidden(*args):
        raise AssertionError('model must not run')
    with pytest.raises(ValueError, match='no visible news'):
        build_demo_prediction(title='', content=content, infer=forbidden)


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
