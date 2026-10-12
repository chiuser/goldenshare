"""Value-based weekly basis validation, including real delisting-period shapes."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from test_stock_weekly_adj_p1_contracts import weekly_definition
from test_stock_weekly_adj_p2 import (
    CODE,
    OLD,
    WEEK,
    Calendar,
    Daily,
    Delivery,
    Factor,
    Raw,
    Serving,
    execute,
    fake_pages,
    planned,
    requested,
    row,
)
from test_stock_weekly_adj_p2 import (
    db as sqlite_db,
)

from src.foundation.datasets.stock_weekly_adj_contracts import (
    WeeklyAdjContractError,
    canonical_source_rows,
)
from src.foundation.ingestion.stock_weekly_adj_delivery import (
    validate_weekly_adj_source_basis,
)
from src.foundation.ingestion.stock_weekly_adj_planning import resolve_weekly_adj_units


@pytest.fixture
def db(tmp_path):
    yield from sqlite_db.__wrapped__(tmp_path)


RETIRED = "688287.SH"
BASIS = date(2026, 5, 21)
LAST = date(2026, 6, 8)
LAST_WEEK = date(2026, 6, 12)
FACTOR = Decimal("1.5915")


def retired_row(day=OLD):
    result = row(day, code=RETIRED, close="0.35", qfq="0.35", basis=BASIS)
    # Literal actual source values, not expected values calculated by the validator.
    values = (
        {
            "open": ".35",
            "high": ".38",
            "low": ".34",
            "close": ".35",
            "open_hfq": ".56",
            "high_hfq": ".60",
            "low_hfq": ".54",
            "close_hfq": ".56",
            "vol": "519475.41",
            "amount": "18349.07",
        }
        if day == OLD
        else {
            "open": ".35",
            "high": ".38",
            "low": ".35",
            "close": ".37",
            "open_hfq": ".56",
            "high_hfq": ".60",
            "low_hfq": ".56",
            "close_hfq": ".59",
            "vol": "209982.81",
            "amount": "7553.89",
        }
    )
    result.update({key: Decimal(value) for key, value in values.items()})
    result.update(
        {key + "_qfq": result[key] for key in ("open", "high", "low", "close")}
    )
    return result


def seed_retired(engine, *, basis_factor=True):
    with Session(engine) as session:
        session.add_all(
            [
                *(
                    Daily(
                        ts_code=CODE,
                        trade_date=date(2026, 6, n),
                        close=Decimal(10),
                        source="tushare",
                    )
                    for n in range(1, 5)
                ),
                Daily(
                    ts_code=RETIRED,
                    trade_date=OLD,
                    close=Decimal(".35"),
                    source="tushare",
                ),
                Daily(
                    ts_code=RETIRED,
                    trade_date=LAST,
                    close=Decimal(".37"),
                    source="tushare",
                ),
                Factor(ts_code=RETIRED, trade_date=OLD, adj_factor=FACTOR),
                Factor(ts_code=RETIRED, trade_date=LAST, adj_factor=FACTOR),
                *(
                    Calendar(exchange="SSE", trade_date=date(2026, 6, n), is_open=True)
                    for n in range(8, 13)
                ),
            ]
        )
        if basis_factor:
            session.add(Factor(ts_code=RETIRED, trade_date=BASIS, adj_factor=FACTOR))
        session.commit()


def validate(engine, values, *, floor=None, bootstrap=False, unit=None):
    definition, _, units = planned(engine, requested(code=RETIRED, end=LAST_WEEK))
    with Session(engine) as session:
        return validate_weekly_adj_source_basis(
            session,
            unit or units[0],
            canonical_source_rows(values, definition.planning.weekly_adj_policy),
            floor=floor,
            bootstrap=bootstrap,
        )


@pytest.mark.parametrize("bootstrap", [False, True])
def test_old_date_same_factor_is_valid_even_after_delisting(db, bootstrap):
    seed_retired(db)
    basis, audit = validate(
        db, [retired_row(), retired_row(LAST_WEEK)], floor=WEEK, bootstrap=bootstrap
    )
    assert basis == BASIS
    assert audit["checked"] == audit["earlier_basis_verified"] == 1
    assert audit["unverified_codes"] == 0


def test_delisting_week_friday_label_publishes_all_source_fields(db, monkeypatch):
    seed_retired(db)
    # The market remains open after this stock's last trading day.
    with Session(db) as session:
        session.add_all(
            Daily(ts_code=CODE, trade_date=date(2026, 6, n), source="tushare")
            for n in range(8, 13)
        )
        session.commit()
    definition = weekly_definition()
    with Session(db) as session:
        request, units = resolve_weekly_adj_units(
            session,
            requested(mode="point", code=RETIRED, end=LAST_WEEK),
            definition,
            now=datetime(2026, 6, 13, tzinfo=UTC),
        )
    assert units[0].progress_context["require_complete_source"] is True
    source = retired_row(LAST_WEEK)
    result = execute(
        db, monkeypatch, definition, request, units, fake_pages(lambda _: [source])
    )
    assert result.rows_written == 1
    with Session(db) as session:
        raw = session.get(Raw, (RETIRED, LAST_WEEK, "week"))
        serving = session.get(Serving, (RETIRED, LAST_WEEK, "week"))
        assert raw.end_date == serving.end_date == BASIS
        assert raw.trade_date == serving.trade_date == LAST_WEEK
        assert raw.vol == serving.vol == Decimal("209982.81")
        assert raw.amount == serving.amount == Decimal("7553.89")
        record = session.scalar(select(Delivery).where(Delivery.record_kind == "unit"))
        assert record.reason_summary["basis_audit"]["earlier_basis_verified"] == 1
        assert len(record.payload["rows"]) == 1


@pytest.mark.parametrize("bootstrap", [False, True])
def test_older_basis_with_different_target_factor_is_rejected(db, bootstrap):
    seed_retired(db)
    with Session(db) as session:
        session.get(Factor, (RETIRED, LAST)).adj_factor = Decimal(2)
        session.commit()
    with pytest.raises(WeeklyAdjContractError, match="目标因子不同"):
        validate(db, [retired_row()], floor=WEEK, bootstrap=bootstrap)


@pytest.mark.parametrize("basis", [BASIS, LAST])
def test_frozen_factor_checked_even_when_basis_date_differs_from_cutoff(db, basis):
    seed_retired(db)
    _, _, units = planned(db, requested(code=RETIRED, end=LAST_WEEK))
    unit = replace(
        units[0], progress_context={**units[0].progress_context, "factor_target": "2"}
    )
    with pytest.raises(WeeklyAdjContractError, match="冻结计划不同"):
        validate(db, [{**retired_row(), "end_date": basis}], floor=WEEK, unit=unit)


def test_frozen_factor_same_value_accepts_earlier_date(db):
    seed_retired(db)
    _, _, units = planned(db, requested(code=RETIRED, end=LAST_WEEK))
    unit = replace(
        units[0],
        progress_context={**units[0].progress_context, "factor_target": str(FACTOR)},
    )
    assert validate(db, [retired_row()], floor=WEEK, unit=unit)[1]["checked"] == 1


def test_recent_basis_price_difference_is_diagnostic_only(db):
    definition, _, units = planned(db)
    with Session(db) as session:
        basis, audit = validate_weekly_adj_source_basis(
            session,
            units[0],
            canonical_source_rows(
                [row(qfq="10")], definition.planning.weekly_adj_policy
            ),
            floor=WEEK,
            bootstrap=False,
        )
    assert basis == WEEK
    assert audit["checked"] == audit["price_compared"] == 1
    assert audit["price_difference_count"] == 1
    assert Decimal(audit["price_max_absolute_difference"]) == Decimal(5)
    assert Decimal(audit["price_max_relative_difference"]) == Decimal(".5")
    sample = audit["price_difference_samples"][0]
    assert sample["ts_code"] == CODE
    assert Decimal(sample["source_close_qfq"]) == Decimal(10)
    assert sample["calculated_close_qfq"] == "5.00"
    assert sample["actual_trade_date"] == OLD.isoformat()
    assert sample["source_basis_date"] == WEEK.isoformat()


def test_missing_factor_is_unverified_in_bootstrap_and_blocks_update(db):
    seed_retired(db, basis_factor=False)
    basis, audit = validate(db, [retired_row()], floor=WEEK, bootstrap=True)
    assert basis is None and audit["checked"] == 0
    assert audit["unverified_samples"] == [
        {"ts_code": RETIRED, "reason": "weekly_adj.factor_coverage_missing"}
    ]
    with pytest.raises(WeeklyAdjContractError) as caught:
        validate(db, [retired_row()], floor=WEEK)
    assert caught.value.code == "weekly_adj.factor_coverage_missing"


@pytest.mark.parametrize("bootstrap", [False, True])
@pytest.mark.parametrize(
    "qfq,absolute", [("4.99", ".01"), ("5.19", ".19"), (".01", "4.99"), ("0", "5")]
)
def test_price_diagnostics_have_no_amount_threshold_and_handle_zero(
    db, bootstrap, qfq, absolute
):
    definition, _, units = planned(db)
    source = canonical_source_rows(
        [row(qfq=qfq)], definition.planning.weekly_adj_policy
    )
    original = [dict(value) for value in source]
    with Session(db) as session:
        basis, audit = validate_weekly_adj_source_basis(
            session, units[0], source, floor=WEEK, bootstrap=bootstrap
        )
    assert basis == WEEK
    assert source == original
    assert audit["price_compared"] == audit["price_difference_count"] == 1
    assert Decimal(audit["price_max_absolute_difference"]) == Decimal(absolute)
    sample = audit["price_difference_samples"][0]
    assert sample["calculated_close_qfq"] == "5.00"
    assert Decimal(sample["difference"]) == Decimal(qfq) - Decimal(5)
    if qfq == "0":
        assert audit["price_max_relative_difference"] is None
        assert sample["relative_difference"] is None
    else:
        assert Decimal(audit["price_max_relative_difference"]) == Decimal(
            absolute
        ) / Decimal(qfq)


def test_mixed_source_basis_remains_blocking(db):
    with pytest.raises(WeeklyAdjContractError) as caught:
        validate(db, [row(), row(WEEK, basis=OLD)])
    assert caught.value.code == "weekly_adj.basis_not_updated"


@pytest.mark.parametrize("bootstrap", [False, True])
@pytest.mark.parametrize(
    "code,week,last,basis,close,qfq,trade_factor,basis_factor,expected",
    [
        (
            "601198.SH",
            "2020-01-03",
            "2020-01-03",
            "2026-09-14",
            "12.94",
            "11.69",
            "1.0494",
            "1.1611",
            "11.70",
        ),
        (
            "000668.SZ",
            "2020-01-10",
            "2020-01-10",
            "2026-09-30",
            "13.67",
            "13.54",
            "3.6617",
            "3.6983",
            "13.53",
        ),
        (
            "002898.SZ",
            "2020-01-10",
            "2020-01-10",
            "2026-07-16",
            "13.86",
            "12.54",
            "1.019",
            "1.1255",
            "12.55",
        ),
        (
            "300029.SZ",
            "2020-01-10",
            "2020-01-10",
            "2026-07-09",
            "6.61",
            "6.61",
            "1.024",
            "1.023",
            "6.62",
        ),
        (
            "300760.SZ",
            "2021-01-01",
            "2020-12-31",
            "2026-10-09",
            "426.0",
            "380.58",
            "1.0125",
            "1.1339",
            "380.39",
        ),
        (
            "920522.BJ",
            "2020-01-24",
            "2020-01-23",
            "2026-10-09",
            "3.66",
            "1.51",
            "1.0863",
            "2.6237",
            "1.52",
        ),
        (
            "002713.SZ",
            "2026-04-17",
            "2026-04-17",
            "2026-10-09",
            "14.37",
            "14.37",
            "3.9441",
            "5.0743",
            "11.17",
        ),
        (
            "000908.SZ",
            "2026-05-15",
            "2026-05-15",
            "2026-10-09",
            "7.83",
            "7.83",
            "2.8300",
            "4.1345",
            "5.36",
        ),
    ],
)
def test_literal_audited_price_differences_do_not_block(
    db,
    bootstrap,
    code,
    week,
    last,
    basis,
    close,
    qfq,
    trade_factor,
    basis_factor,
    expected,
):
    # 2026-10-12 source/read-only audit values. The first two intentionally retain
    # the historical pre-maintenance factors; fixtures never load audit reports.
    last_day, basis_day = date.fromisoformat(last), date.fromisoformat(basis)
    with Session(db) as session:
        session.add_all(
            [
                Daily(ts_code=code, trade_date=last_day, source="tushare"),
                Daily(ts_code=code, trade_date=basis_day, source="tushare"),
                Factor(
                    ts_code=code, trade_date=last_day, adj_factor=Decimal(trade_factor)
                ),
                Factor(
                    ts_code=code, trade_date=basis_day, adj_factor=Decimal(basis_factor)
                ),
            ]
        )
        session.commit()
    definition, _, units = planned(db)
    source = canonical_source_rows(
        [
            row(
                date.fromisoformat(week),
                code=code,
                close=close,
                qfq=qfq,
                basis=basis_day,
            )
        ],
        definition.planning.weekly_adj_policy,
    )
    with Session(db) as session:
        accepted_basis, audit = validate_weekly_adj_source_basis(
            session, units[0], source, floor=basis_day, bootstrap=bootstrap
        )
    assert accepted_basis == basis_day
    assert audit["unverified_codes"] == 0
    assert audit["checked"] == audit["price_difference_count"] == 1
    sample = audit["price_difference_samples"][0]
    assert sample["calculated_close_qfq"] == expected
    assert Decimal(sample["source_close_qfq"]) == Decimal(qfq)
    assert sample["actual_trade_date"] == last
    assert sample["source_basis_date"] == basis
    assert Decimal(audit["price_max_absolute_difference"]) == abs(
        Decimal(qfq) - Decimal(expected)
    )


def test_empty_source_has_zero_diagnostics_and_no_factor_query(db):
    _, _, units = planned(db)
    with Session(db) as session:
        basis, audit = validate_weekly_adj_source_basis(
            session, units[0], [], floor=WEEK, bootstrap=True
        )
    assert basis is None
    assert (
        audit["checked"]
        == audit["price_compared"]
        == audit["price_difference_count"]
        == 0
    )
    assert audit["price_difference_samples"] == []


def test_price_difference_publication_preserves_source_fields_and_replays(
    db, monkeypatch
):
    definition, request, units = planned(db)
    source = row(qfq="4.99")
    calls = []

    def page(unit):
        calls.append(unit.unit_id)
        return [dict(source)]

    result = execute(
        db,
        monkeypatch,
        definition,
        request,
        units,
        fake_pages(page),
        progress=lambda *_: (_ for _ in ()).throw(RuntimeError("observer unavailable")),
    )
    assert result.unit_done == 1 and result.unit_failed == 0
    with Session(db) as session:
        for model in (Raw, Serving):
            stored = session.get(model, (CODE, OLD, "week"))
            assert {
                name: getattr(
                    stored,
                    "change_amount" if model is Serving and name == "change" else name,
                )
                for name in source
            } == source
        assert session.get(Raw, (CODE, OLD, "month")).close_qfq == Decimal(5)
        assert session.get(Serving, (CODE, OLD, "month")) is None
        record = session.scalar(select(Delivery).where(Delivery.record_kind == "unit"))
        before = record.payload_digest, record.reason_summary
        audit = record.reason_summary["basis_audit"]
        assert audit["price_difference_count"] == 1
        assert Decimal(record.payload["rows"][0]["close_qfq"]) == Decimal("4.99")
        assert (
            session.scalar(
                select(Delivery).where(Delivery.record_kind == "batch_closed")
            )
            is not None
        )
        # Diagnosis never rewrites historical factors to force price equality.
        assert session.get(Factor, (CODE, OLD)).adj_factor == Decimal(1)
    execute(db, monkeypatch, definition, request, units, fake_pages(page))
    assert calls == [units[0].unit_id]
    with Session(db) as session:
        record = session.scalar(select(Delivery).where(Delivery.record_kind == "unit"))
        assert (record.payload_digest, record.reason_summary) == before


def test_bootstrap_keeps_unverified_source_values_and_records_reason(db, monkeypatch):
    seed_retired(db, basis_factor=False)
    definition = weekly_definition()
    with Session(db) as session:
        request, units = resolve_weekly_adj_units(
            session,
            requested(code=None, end=OLD),
            definition,
            now=datetime(2026, 6, 6, tzinfo=UTC),
        )
    assert request.execution_context["business_plan"]["metadata"]["bootstrap"] is True
    result = execute(
        db,
        monkeypatch,
        definition,
        request,
        units,
        fake_pages(lambda _: [row(qfq="10", basis=BASIS), retired_row()]),
    )
    assert result.rows_written == 2
    with Session(db) as session:
        raw = session.get(Raw, (RETIRED, OLD, "week"))
        assert raw.end_date == BASIS and raw.close_qfq == Decimal(".35")
        record = session.scalar(select(Delivery).where(Delivery.record_kind == "unit"))
        audit = record.reason_summary["basis_audit"]
        assert record.basis_date is None and audit["checked"] == 0
        assert audit["unverified_codes"] == 2
        assert {
            "ts_code": RETIRED,
            "reason": "weekly_adj.factor_coverage_missing",
        } in audit["unverified_samples"]
        assert record.payload["summary"]["basis"] == audit


def test_date_lagged_stock_outside_first_twenty_is_still_compared(db):
    seed_retired(db)
    rows = [row(code=CODE)]
    with Session(db) as session:
        for n in range(2, 21):
            code = f"{n:06d}.SZ"
            session.add_all(
                [
                    Daily(ts_code=code, trade_date=OLD, source="tushare"),
                    Factor(ts_code=code, trade_date=OLD, adj_factor=Decimal(1)),
                    Factor(ts_code=code, trade_date=WEEK, adj_factor=Decimal(2)),
                ]
            )
            rows.append(row(code=code))
        session.commit()
    rows.append({**retired_row(), "close_qfq": Decimal(".99")})
    _, audit = validate(db, rows)
    assert audit["checked"] == audit["price_compared"] == 21
    assert audit["price_difference_count"] == 1
    assert audit["price_difference_samples"][0]["ts_code"] == RETIRED
    assert Decimal(audit["price_max_absolute_difference"]) == Decimal(".64")


@pytest.mark.parametrize("qfq", [".35", ".99"])
def test_many_earlier_dates_use_bounded_sql_batches_and_samples(db, qfq):
    rows = []
    with Session(db) as session:
        for n in range(257):
            code = f"{800000 + n:06d}.SH"
            rows.append({**retired_row(), "ts_code": code, "close_qfq": Decimal(qfq)})
            session.add_all(
                [
                    Daily(ts_code=code, trade_date=OLD, source="tushare"),
                    Factor(ts_code=code, trade_date=OLD, adj_factor=FACTOR),
                    Factor(ts_code=code, trade_date=BASIS, adj_factor=FACTOR),
                ]
            )
        session.commit()
    definition, _, units = planned(db, requested(mode="point", code=None, end=OLD))
    queries = []

    def track(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(db, "before_cursor_execute", track)
    try:
        with Session(db) as session:
            _, audit = validate_weekly_adj_source_basis(
                session,
                units[0],
                canonical_source_rows(rows, definition.planning.weekly_adj_policy),
                floor=None,
                bootstrap=False,
            )
    finally:
        event.remove(db, "before_cursor_execute", track)
    assert audit["checked"] == audit["earlier_basis_verified"] == 257
    assert audit["price_compared"] == 257
    assert audit["price_difference_count"] == (257 if qfq == ".99" else 0)
    assert len(audit["price_difference_samples"]) == (20 if qfq == ".99" else 0)
    assert (
        len(queries) == 6
    )  # Three chunks, one indexed date SQL and one factor SQL each.
