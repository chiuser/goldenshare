from __future__ import annotations

from src.foundation.resolution.policy_engine import ResolutionPolicyEngine
from src.foundation.resolution.types import ResolutionInput, ResolutionPolicy


def test_policy_engine_primary_prefers_primary_source() -> None:
    engine = ResolutionPolicyEngine()
    policy = ResolutionPolicy(
        dataset_key="stock_basic",
        mode="primary",
        primary_source_key="tushare",
        fallback_source_keys=("biying",),
        version=3,
    )
    resolution_input = ResolutionInput(
        dataset_key="stock_basic",
        business_key="000001.SZ",
        candidates_by_source={
            "tushare": {"ts_code": "000001.SZ", "name": "平安银行"},
            "biying": {"ts_code": "000001.SZ", "name": "平安银行"},
        },
    )

    output = engine.resolve(resolution_input, policy)

    assert output.resolved_source_key == "tushare"
    assert output.resolved_record == {"ts_code": "000001.SZ", "name": "平安银行"}
    assert output.policy_version == 3


def test_policy_engine_fallback_uses_secondary_when_primary_missing() -> None:
    engine = ResolutionPolicyEngine()
    policy = ResolutionPolicy(
        dataset_key="stock_basic",
        mode="fallback",
        primary_source_key="tushare",
        fallback_source_keys=("biying",),
    )
    resolution_input = ResolutionInput(
        dataset_key="stock_basic",
        business_key="000002.SZ",
        candidates_by_source={
            "biying": {"ts_code": "000002.SZ", "name": "万科A"},
        },
    )

    output = engine.resolve(resolution_input, policy)

    assert output.resolved_source_key == "biying"
    assert output.resolved_record == {"ts_code": "000002.SZ", "name": "万科A"}


def test_policy_engine_field_merge_overrides_selected_fields() -> None:
    engine = ResolutionPolicyEngine()
    policy = ResolutionPolicy(
        dataset_key="stock_basic",
        mode="field_merge",
        primary_source_key="tushare",
        fallback_source_keys=("biying",),
        field_rules={
            "name": {"preferred_sources": ["biying", "tushare"]},
            "exchange": {"preferred_sources": ["tushare"]},
        },
    )
    resolution_input = ResolutionInput(
        dataset_key="stock_basic",
        business_key="000001.SZ",
        candidates_by_source={
            "tushare": {"ts_code": "000001.SZ", "name": "平安银行", "exchange": "SZSE"},
            "biying": {"ts_code": "000001.SZ", "name": "平 安 银 行", "exchange": "SZ"},
        },
    )

    output = engine.resolve(resolution_input, policy)

    assert output.resolved_source_key == "tushare"
    assert output.resolved_record == {
        "ts_code": "000001.SZ",
        "name": "平 安 银 行",
        "exchange": "SZSE",
    }


def test_policy_engine_freshness_first_uses_latest_timestamp_then_priority() -> None:
    engine = ResolutionPolicyEngine()
    policy = ResolutionPolicy(
        dataset_key="stock_basic",
        mode="freshness_first",
        primary_source_key="tushare",
        fallback_source_keys=("biying",),
        field_rules={"__freshness__": {"field": "updated_at"}},
    )
    resolution_input = ResolutionInput(
        dataset_key="stock_basic",
        business_key="000001.SZ",
        candidates_by_source={
            "tushare": {"ts_code": "000001.SZ", "updated_at": "2026-04-12T10:00:00+08:00"},
            "biying": {"ts_code": "000001.SZ", "updated_at": "2026-04-12T09:00:00+08:00"},
        },
    )

    output = engine.resolve(resolution_input, policy)

    assert output.resolved_source_key == "tushare"
    assert output.resolved_record == {"ts_code": "000001.SZ", "updated_at": "2026-04-12T10:00:00+08:00"}
