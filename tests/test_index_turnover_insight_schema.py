from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from src.biz.queries.wealth.market.index_turnover_insight.index_turnover_insight_calculator import (
    IndexTurnoverInsightCalculator,
)
from src.biz.schemas.wealth.market.index_turnover_insight import (
    IndexTurnoverInsightResponseDto,
    IndexTurnoverInsightTradingDayDto,
)
from src.biz.services.wealth.market.index_turnover_insight.index_turnover_insight_universe import (
    INDEX_TURNOVER_INSIGHT_UNIVERSE,
)


def _empty_payload() -> dict:
    calculator = IndexTurnoverInsightCalculator()
    return {
        "status": "ERROR",
        "tradingDay": IndexTurnoverInsightTradingDayDto(
            market="CN_A",
            expectedTradeDate=date(2026, 9, 1),
            observedTradeDate=None,
            previousObservedTradeDate=None,
            isTradingDay=True,
            sessionStatus="CLOSED",
            generatedAt=datetime(2026, 9, 2, 8, 0),
        ),
        "indices": [
            calculator.build_panel_dto(
                identity=identity,
                calculation=None,
                status="ERROR",
                message="error",
                exception_code="ITI_QUERY_FAILED",
            )
            for identity in INDEX_TURNOVER_INSIGHT_UNIVERSE
        ],
        "message": "error",
        "exceptionCode": "ITI_QUERY_FAILED",
    }


def test_schema_accepts_fixed_ten_placeholders_and_forbids_extra_fields() -> None:
    response = IndexTurnoverInsightResponseDto.model_validate(_empty_payload())
    assert len(response.indices) == 10

    invalid = _empty_payload()
    invalid["codes"] = ["000001.SH"]
    with pytest.raises(ValidationError):
        IndexTurnoverInsightResponseDto.model_validate(invalid)


def test_schema_rejects_missing_identity_and_invalid_delayed_date() -> None:
    missing = _empty_payload()
    missing["indices"] = missing["indices"][:-1]
    with pytest.raises(ValidationError):
        IndexTurnoverInsightResponseDto.model_validate(missing)

    delayed = _empty_payload()
    delayed["status"] = "DELAYED"
    delayed["tradingDay"] = delayed["tradingDay"].model_copy(
        update={"observedTradeDate": date(2026, 9, 1)}
    )
    with pytest.raises(ValidationError):
        IndexTurnoverInsightResponseDto.model_validate(delayed)
