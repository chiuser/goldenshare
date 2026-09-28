from __future__ import annotations

import pytest

from src.biz.services.wealth.news_intelligence.calibration_pipeline import (
    run_lightweight_pipeline,
    select_deep_analysis,
)
from src.biz.services.wealth.news_intelligence.generation_contract import (
    QWEN_ANALYSIS_FIELDS,
    QWEN_ANALYSIS_GBNF,
    build_analysis_prompt,
    validate_analysis_payload,
)
from tests.news_intelligence.test_replay_contracts import _item


class _EmbeddingProvider:
    def embed(self, texts, *, timeout_seconds):
        assert timeout_seconds > 0
        return {
            request_id: (1.0, float(index))
            for index, (request_id, _) in enumerate(texts)
        }


class _NliProvider:
    def nli(self, requests, *, timeout_seconds):
        assert timeout_seconds > 0
        return {
            request_id: tuple(
                0.9 if index == 0 else 0.1 for index, _ in enumerate(hypotheses)
            )
            for request_id, _, hypotheses in requests
        }


def test_lightweight_pipeline_bounds_model_inputs_and_selects_priority_event() -> None:
    items = (
        _item(
            "macro", title="央行降准", content="央行宣布降准。公开市场操作同步调整。"
        ),
        _item(
            "ai",
            title="人工智能模型发布",
            content="公司发布人工智能大模型。技术发布完成。",
        ),
    )
    result = run_lightweight_pipeline(
        items,
        embedding_provider=_EmbeddingProvider(),
        nli_provider=_NliProvider(),
        embedding_timeout_seconds=10,
        nli_timeout_seconds=10,
        clustering_threshold=0.99,
    )
    assert len(result.events) == 2
    assert all(
        len(analysis.candidates.primary_topics) <= 4 for analysis in result.analyses
    )
    assert all(
        len(analysis.candidates.event_types) <= 6 for analysis in result.analyses
    )
    assert len(result.deep_analysis_event_ids) == 2
    assert {analysis.primary_topic for analysis in result.analyses} == {
        "ECONOMY_BUSINESS_FINANCE",
        "SCIENCE_TECHNOLOGY",
    }


def test_deep_analysis_limit_cannot_exceed_frozen_maximum() -> None:
    with pytest.raises(ValueError, match="0..30"):
        select_deep_analysis((), (), (), limit=31)


def test_qwen_contract_requires_exact_supported_json() -> None:
    prompt = build_analysis_prompt(title="标题", content="正文")
    assert "只能依据" in prompt
    assert "root ::=" in QWEN_ANALYSIS_GBNF
    payload = {
        "importance": 4,
        "one_sentence": "一句结论",
        "facts": ["事实"],
        "impact": "影响",
        "uncertainties": ["不确定性"],
        "entities": ["主体"],
        "evidence": ["原文证据"],
    }
    assert set(validate_analysis_payload(payload)) == QWEN_ANALYSIS_FIELDS
    with pytest.raises(ValueError, match="keys"):
        validate_analysis_payload({**payload, "extra": "forbidden"})
    with pytest.raises(ValueError, match="importance"):
        validate_analysis_payload({**payload, "importance": 6})
