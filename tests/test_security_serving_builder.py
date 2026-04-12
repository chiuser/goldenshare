from __future__ import annotations

from src.foundation.resolution.types import ResolutionPolicy
from src.foundation.serving.builders.security_serving_builder import SecurityServingBuilder


def test_security_serving_builder_merges_and_normalizes_rows() -> None:
    builder = SecurityServingBuilder()
    policy = ResolutionPolicy(
        dataset_key="stock_basic",
        mode="primary",
        primary_source_key="tushare",
        fallback_source_keys=("biying",),
    )
    result = builder.build_rows(
        std_rows_by_source={
            "tushare": [
                {
                    "source_key": "tushare",
                    "ts_code": "000001.SZ",
                    "name": "平安银行",
                    "exchange": "SZSE",
                    "area": "深圳",
                    "security_type": "EQUITY",
                }
            ],
            "biying": [
                {
                    "source_key": "biying",
                    "ts_code": "000002.SZ",
                    "name": "万科A",
                    "exchange": "SZ",
                    "security_type": "EQUITY",
                }
            ],
        },
        policy=policy,
        active_sources={"tushare", "biying"},
        target_columns={"ts_code", "name", "exchange", "area", "security_type", "source"},
    )

    assert result.resolved_count == 2
    assert len(result.rows) == 2
    row1 = next(row for row in result.rows if row["ts_code"] == "000001.SZ")
    row2 = next(row for row in result.rows if row["ts_code"] == "000002.SZ")
    assert row1["source"] == "tushare"
    assert row1["area"] == "深圳"
    assert row2["source"] == "biying"
    assert row2["area"] is None


def test_security_serving_builder_fills_provenance_fields_when_target_has_columns() -> None:
    builder = SecurityServingBuilder()
    policy = ResolutionPolicy(
        dataset_key="stock_basic",
        mode="field_merge",
        primary_source_key="tushare",
        fallback_source_keys=("biying",),
        version=3,
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

    assert result.resolved_count == 1
    row = result.rows[0]
    assert row["source"] == "tushare"
    assert row["resolution_mode"] == "field_merge"
    assert row["resolution_policy_version"] == 3
    assert row["candidate_sources"] == "biying,tushare"
    assert isinstance(row["resolution_audit"], dict)
