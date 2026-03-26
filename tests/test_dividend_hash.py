from decimal import Decimal

from src.services.transform.dividend_hash import build_dividend_event_key_hash, build_dividend_row_key_hash


def test_dividend_row_key_hash_changes_when_record_state_changes() -> None:
    base = {
        "ts_code": "000001.SZ",
        "end_date": "2025-12-31",
        "ann_date": "2026-03-21",
        "div_proc": "预案",
        "stk_div": Decimal("0"),
        "stk_bo_rate": None,
        "stk_co_rate": None,
        "cash_div": Decimal("0"),
        "cash_div_tax": Decimal("0.36"),
        "record_date": None,
        "ex_date": None,
        "pay_date": None,
        "div_listdate": None,
        "imp_ann_date": None,
        "base_date": "2025-12-31",
        "base_share": Decimal("1940591.8198"),
    }
    revised = {**base, "cash_div_tax": Decimal("0.40")}

    assert build_dividend_row_key_hash(base) != build_dividend_row_key_hash(revised)
    assert build_dividend_event_key_hash(base) == build_dividend_event_key_hash(revised)


def test_dividend_hash_treats_none_as_empty_string() -> None:
    row = {
        "ts_code": "000001.SZ",
        "end_date": None,
        "ann_date": None,
        "div_proc": "预案",
        "stk_div": None,
        "stk_bo_rate": None,
        "stk_co_rate": None,
        "cash_div": None,
        "cash_div_tax": None,
        "record_date": None,
        "ex_date": None,
        "pay_date": None,
        "div_listdate": None,
        "imp_ann_date": None,
        "base_date": None,
        "base_share": None,
    }

    assert len(build_dividend_row_key_hash(row)) == 64
    assert len(build_dividend_event_key_hash(row)) == 64
