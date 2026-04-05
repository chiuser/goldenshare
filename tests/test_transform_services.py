from decimal import Decimal

from src.foundation.services.transform.build_adjusted_bar_service import BuildAdjustedBarService
from src.utils import parse_tushare_date


def test_parse_tushare_date() -> None:
    assert parse_tushare_date("20260324").isoformat() == "2026-03-24"


def test_calculate_qfq_price() -> None:
    service = BuildAdjustedBarService()
    result = service.calculate_qfq_price(Decimal("10"), Decimal("2"), Decimal("4"))
    assert result == Decimal("5.0000")
