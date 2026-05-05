from decimal import Decimal

from src.foundation.services.transform.build_adjusted_bar_service import BuildAdjustedBarService
from src.foundation.services.transform.normalize_security_service import NormalizeSecurityService
from src.utils import parse_tushare_date


def test_parse_tushare_date() -> None:
    assert parse_tushare_date("20260324").isoformat() == "2026-03-24"


def test_parse_tushare_date_treats_pseudo_null_text_as_none() -> None:
    assert parse_tushare_date(0) is None
    assert parse_tushare_date("0") is None
    assert parse_tushare_date("nan") is None
    assert parse_tushare_date("NaT") is None
    assert parse_tushare_date(" null ") is None
    assert parse_tushare_date("none") is None


def test_calculate_qfq_price() -> None:
    service = BuildAdjustedBarService()
    result = service.calculate_qfq_price(Decimal("10"), Decimal("2"), Decimal("4"))
    assert result == Decimal("5.0000")


def test_normalize_security_from_biying() -> None:
    service = NormalizeSecurityService()
    row = service.to_core({"dm": "000001.SZ", "mc": "平安银行", "jys": "SZ"}, source_key="biying")
    assert row["ts_code"] == "000001.SZ"
    assert row["symbol"] == "000001"
    assert row["name"] == "平安银行"
    assert row["exchange"] == "SZ"
    assert row["source"] == "biying"
