from __future__ import annotations

from src.foundation.resolution.types import ResolutionPolicy
from src.foundation.serving.builders.security_serving_builder import SecurityServingBuilder


def test_serving_builder_writes_provenance_fields_when_target_supports_it() -> None:
    builder = SecurityServingBuilder()
    policy = ResolutionPolicy(
        dataset_key="stock_basic",
        mode="field_merge",
        primary_source_key="tushare",
        fallback_source_keys=("biying",),
        version=9,
    )
    result = builder.build_rows(
        std_rows_by_source={
            "tushare": [{"source_key": "tushare", "ts_code": "000001.SZ", "name": "平安银行"}],
            "biying": [{"source_key": "biying", "ts_code": "000001.SZ", "name": "平安银行"}],
        },
        policy=policy,
        active_sources={"tushare", "biying"},
        target_columns={
            "ts_code",
            "name",
            "source",
            "resolution_mode",
            "resolution_policy_version",
            "candidate_sources",
            "resolution_audit",
        },
    )

    row = result.rows[0]
    assert row["resolution_mode"] == "field_merge"
    assert row["resolution_policy_version"] == 9
    assert row["candidate_sources"] == "biying,tushare"
    assert isinstance(row["resolution_audit"], dict)


def test_serving_builder_skips_provenance_fields_when_target_does_not_support_it() -> None:
    builder = SecurityServingBuilder()
    policy = ResolutionPolicy(
        dataset_key="stock_basic",
        mode="primary",
        primary_source_key="tushare",
        fallback_source_keys=("biying",),
        version=1,
    )
    result = builder.build_rows(
        std_rows_by_source={
            "tushare": [{"source_key": "tushare", "ts_code": "000001.SZ", "name": "平安银行"}]
        },
        policy=policy,
        active_sources={"tushare"},
        target_columns={"ts_code", "name", "source"},
    )

    row = result.rows[0]
    assert "resolution_mode" not in row
    assert "resolution_policy_version" not in row
    assert "candidate_sources" not in row
    assert "resolution_audit" not in row
