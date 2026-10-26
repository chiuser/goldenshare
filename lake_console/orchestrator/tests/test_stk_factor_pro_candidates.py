from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from orchestrator.defs.io.stk_factor_pro_candidates import (
    build_stk_factor_pro_raw_batch,
    release_stk_factor_pro_day_source,
    stk_factor_pro_double,
    stk_factor_pro_raw_trade_date,
)
from orchestrator.defs.io.stk_factor_pro_download import (
    verify_stk_factor_pro_day_source,
)
from tests.stk_factor_pro_test_support import (
    NAMES,
    connection,
    contract,
    identity,
    result,
    row,
    summary,
)


@pytest.mark.parametrize(
    "value",
    [
        True,
        "1",
        1.0,
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("1e9999"),
        Decimal("1e-9999"),
    ],
)
def test_http_invalid_numbers_rejected(value):
    with pytest.raises(ValueError):
        stk_factor_pro_double(value, source="http")


@pytest.mark.parametrize("value", [None, 0, -1, Decimal("-1.25"), Decimal("1e-300")])
def test_http_valid_numbers_preserved(value):
    assert stk_factor_pro_double(value, source="http") == (
        None if value is None else float(value)
    )


@pytest.mark.parametrize(
    "value", [True, 1, Decimal(1), "1", float("nan"), float("inf")]
)
def test_prod_invalid_numbers_rejected(value):
    with pytest.raises(ValueError):
        stk_factor_pro_double(value, source="prod_postgres")


def test_prod_date_and_finite_float_rule():
    assert (
        stk_factor_pro_raw_trade_date(date(2026, 10, 16), source="prod_postgres")
        == "20261016"
    )
    assert stk_factor_pro_double(-1.25, source="prod_postgres") == -1.25
    with pytest.raises(ValueError):
        stk_factor_pro_raw_trade_date(
            datetime(2026, 10, 16, tzinfo=UTC), source="prod_postgres"
        )


@pytest.mark.parametrize(
    "value", [None, 20261016, "2026-10-16", "20260230", "20261016 ", "２０２６１０１６"]
)
def test_invalid_source_date_rejected(value):
    with pytest.raises((ValueError, TypeError)):
        stk_factor_pro_raw_trade_date(value, source="http")


def test_per_record_field_reordering_and_independent_u(tmp_path):
    original = result((row(), row("600000.SH", close=Decimal(20))))
    reversed_record = replace(
        original.records[1],
        fields=tuple(reversed(NAMES)),
        values=tuple(reversed(original.records[1].values)),
    )
    reordered = replace(
        original,
        records=(original.records[0], reversed_record),
        observed_field_sets=(NAMES, tuple(reversed(NAMES))),
    )
    with connection(tmp_path) as conn:
        source = verify_stk_factor_pro_day_source(
            conn,
            identity=identity(),
            result=reordered,
            summary=summary(2),
            contract=contract(),
        )
        assert source.unit_result is reordered
        assert conn.execute(
            "SELECT ts_code,open,close,macd_bfq,pe FROM stk_factor_pro_day_source ORDER BY ts_code"
        ).fetchall() == [
            ("000001.SZ", 1.25, 10.0, -1.25, None),
            ("600000.SH", 1.25, 20.0, -1.25, None),
        ]
        assert "stk_factor_pro_current_batch" not in {
            r[0] for r in conn.execute("SHOW TABLES").fetchall()
        }
        release_stk_factor_pro_day_source(conn)
        assert conn.execute("SHOW TABLES").fetchall() == []


@pytest.mark.parametrize(
    "kind", ["missing", "extra", "duplicate", "width", "date", "key", "duplicate_key"]
)
def test_invalid_unit_input_rejected_without_u_leak(tmp_path, kind):
    original = result((row(),))
    rec = original.records[0]
    if kind == "missing":
        rec = replace(rec, fields=NAMES[:-1], values=rec.values[:-1])
    elif kind == "extra":
        rec = replace(rec, fields=(*NAMES, "extra"), values=(*rec.values, 0))
    elif kind == "duplicate":
        rec = replace(rec, fields=(*NAMES[:-1], NAMES[0]))
    elif kind == "width":
        rec = replace(rec, values=rec.values[:-1])
    elif kind == "date":
        rec = replace(rec, values=row(day="20261015"))
    elif kind == "key":
        rec = replace(rec, values=row(code=" 000001.SZ"))
    records = (rec, rec) if kind == "duplicate_key" else (rec,)
    value = replace(
        original,
        records=records,
        observed_field_sets=(rec.fields,),
        statistics=replace(original.statistics, row_count=len(records)),
    )
    with connection(tmp_path) as conn:
        with pytest.raises(ValueError):
            verify_stk_factor_pro_day_source(
                conn,
                identity=identity(),
                result=value,
                summary=summary(len(records)),
                contract=contract(),
            )
        assert conn.execute("SHOW TABLES").fetchall() == []


def test_batch_uses_nullable_float_columns_and_no_type_guessing():
    frame = build_stk_factor_pro_raw_batch(
        rows=(row(),),
        source_fields=NAMES,
        source="http",
        expected_dates=(date(2026, 10, 16),),
    )
    assert str(frame.pe.dtype) == "Float64" and frame.pe.isna().all()
    assert tuple(frame.columns) == NAMES


def test_conversion_error_identifies_stock_date_field_without_dumping_row():
    with pytest.raises(ValueError, match="000001.SZ/20261016字段close转换失败"):
        build_stk_factor_pro_raw_batch(
            rows=(row(close="invalid-number"),),
            source_fields=NAMES,
            source="http",
            expected_dates=(date(2026, 10, 16),),
        )
