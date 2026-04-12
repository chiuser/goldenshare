from __future__ import annotations

from src.foundation.resolution.conflict_scorer import ConflictScorer


def test_conflict_scorer_collects_field_level_conflicts() -> None:
    scorer = ConflictScorer()
    conflicts = scorer.collect_conflicts(
        {
            "tushare": {"ts_code": "000001.SZ", "name_norm": "平安银行", "exchange_norm": "SZ"},
            "biying": {"ts_code": "000001.SZ", "name_norm": "平安银行", "exchange_norm": "SH"},
        },
        comparable_fields=("name_norm", "exchange_norm"),
    )

    assert len(conflicts) == 1
    assert conflicts[0].field == "exchange_norm"
    assert conflicts[0].values_by_source == {"tushare": "SZ", "biying": "SH"}


def test_conflict_scorer_ignores_non_comparable_or_same_values() -> None:
    scorer = ConflictScorer()
    conflicts = scorer.collect_conflicts(
        {
            "tushare": {"ts_code": "000001.SZ", "name_norm": "平安银行"},
            "biying": {"ts_code": "000001.SZ", "name_norm": "平安银行"},
        },
        comparable_fields=("name_norm", "exchange_norm"),
    )

    assert conflicts == []
