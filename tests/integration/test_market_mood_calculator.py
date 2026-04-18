from __future__ import annotations

import json
import os
from datetime import date

import pytest
from sqlalchemy import func, select

from src.biz.services.market_mood_calculator import MarketMoodCalculator
from src.db import SessionLocal
from src.foundation.models.core.dc_index import DcIndex
from src.foundation.models.core.dc_member import DcMember
from src.foundation.models.core_serving.equity_daily_bar import EquityDailyBar

_RUN_FLAG = "RUN_MARKET_MOOD_CALC"


@pytest.mark.skipif(
    os.getenv(_RUN_FLAG) != "1",
    reason=f"set {_RUN_FLAG}=1 to run live market mood calculation smoke test",
)
def test_market_mood_calculation_smoke() -> None:
    with SessionLocal() as session:
        latest_trade_date = session.scalar(select(func.max(EquityDailyBar.trade_date)))
        assert latest_trade_date is not None

        # 你刚补过的日期，顺手做一次覆盖校验，确保主线相关计算不会因缺口失真。
        concept_count_20260402 = session.scalar(
            select(func.count()).select_from(DcIndex).where(
                DcIndex.trade_date == date(2026, 4, 2),
                DcIndex.idx_type == "概念板块",
            )
        )
        member_count_20260402 = session.scalar(
            select(func.count()).select_from(DcMember).where(DcMember.trade_date == date(2026, 4, 2))
        )
        assert (concept_count_20260402 or 0) > 0
        assert (member_count_20260402 or 0) > 0

        calculator = MarketMoodCalculator(sample_threshold=5)
        result = calculator.calculate_for_trade_date(
            session,
            trade_date=latest_trade_date,
        )
        payload = result.to_dict()

    print("\n===== market mood calculation snapshot =====")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))

    assert payload["trade_date"] == latest_trade_date.isoformat()
    assert payload["temperature"]["universe_size"] >= 1000
    assert "red_rate" in payload["temperature"]
    assert "mainline_concentration" in payload["temperature"]
    assert "structure_tag" in payload["emotion"]
