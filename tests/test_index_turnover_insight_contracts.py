from __future__ import annotations

import pytest

from src.biz.services.wealth.market.index_turnover_insight.index_turnover_insight_exception_builder import (
    INDEX_TURNOVER_INSIGHT_EXCEPTION_SEVERITY,
    IndexTurnoverInsightExceptionBuilder,
)


def test_exception_builder_owns_the_exact_registered_severity_contract() -> None:
    assert dict(INDEX_TURNOVER_INSIGHT_EXCEPTION_SEVERITY) == {
        "ITI_SOURCE_NOT_READY": "warn",
        "ITI_SOURCE_DELAYED": "warn",
        "ITI_SOURCE_CONTRACT_MISMATCH": "error",
        "ITI_CODE_SCOPE_MISMATCH": "error",
        "ITI_TIME_GRID_MISMATCH": "error",
        "ITI_POINT_QUALITY_INVALID": "error",
        "ITI_AVERAGE_WINDOW_INCOMPLETE": "warn",
        "ITI_QUERY_FAILED": "error",
    }
    exception = IndexTurnoverInsightExceptionBuilder.build(
        code="ITI_SOURCE_NOT_READY", message="not ready"
    )
    assert exception.severity == "warn"
    with pytest.raises(ValueError):
        IndexTurnoverInsightExceptionBuilder.build(
            code="TI_SOURCE_DELAYED", message="wrong module"
        )


def test_exception_primary_code_uses_the_lld_priority() -> None:
    assert IndexTurnoverInsightExceptionBuilder.select_primary(
        ["ITI_SOURCE_NOT_READY", "ITI_TIME_GRID_MISMATCH", "ITI_QUERY_FAILED"]
    ) == "ITI_QUERY_FAILED"
    assert IndexTurnoverInsightExceptionBuilder.select_primary(
        ["ITI_AVERAGE_WINDOW_INCOMPLETE", "ITI_SOURCE_DELAYED"]
    ) == "ITI_SOURCE_DELAYED"
