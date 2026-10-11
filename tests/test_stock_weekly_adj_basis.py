"""Value-based weekly basis validation, including real delisting-period shapes."""

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from src.foundation.datasets.stock_weekly_adj_contracts import (
    WeeklyAdjContractError,
    canonical_source_rows,
)
from src.foundation.ingestion.stock_weekly_adj_delivery import (
    validate_weekly_adj_source_basis,
)
from src.foundation.ingestion.stock_weekly_adj_planning import resolve_weekly_adj_units
from test_stock_weekly_adj_p1_contracts import weekly_definition
from test_stock_weekly_adj_p2 import (
    CODE,
    OLD,
    WEEK,
    Calendar,
    Daily,
    Factor,
    Raw,
    Serving,
    Delivery,
    db as sqlite_db,
    execute,
    fake_pages,
    planned,
    requested,
    row,
)


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
                        close=Decimal("10"),
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
            now=datetime(2026, 6, 13, tzinfo=timezone.utc),
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
        session.get(Factor, (RETIRED, LAST)).adj_factor = Decimal("2")
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


def test_recent_date_with_old_price_is_still_rejected(db):
    definition, _, units = planned(db)
    with (
        Session(db) as session,
        pytest.raises(WeeklyAdjContractError, match="close 与独立因子不一致"),
    ):
        validate_weekly_adj_source_basis(
            session,
            units[0],
            canonical_source_rows(
                [row(qfq="10")], definition.planning.weekly_adj_policy
            ),
            floor=WEEK,
            bootstrap=False,
        )


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


def test_bootstrap_keeps_unverified_source_values_and_records_reason(db, monkeypatch):
    seed_retired(db, basis_factor=False)
    definition = weekly_definition()
    with Session(db) as session:
        request, units = resolve_weekly_adj_units(
            session,
            requested(code=None, end=OLD),
            definition,
            now=datetime(2026, 6, 6, tzinfo=timezone.utc),
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


def test_date_lagged_stock_outside_first_twenty_cannot_bypass_price_check(db):
    seed_retired(db)
    rows = [row(code=CODE)]
    with Session(db) as session:
        for n in range(2, 21):
            code = f"{n:06d}.SZ"
            session.add_all(
                [
                    Daily(ts_code=code, trade_date=OLD, source="tushare"),
                    Factor(ts_code=code, trade_date=OLD, adj_factor=Decimal("1")),
                    Factor(ts_code=code, trade_date=WEEK, adj_factor=Decimal("2")),
                ]
            )
            rows.append(row(code=code))
        session.commit()
    rows.append({**retired_row(), "close_qfq": Decimal(".99")})
    with pytest.raises(WeeklyAdjContractError, match="688287.SH"):
        validate(db, rows)


def test_many_earlier_dates_use_bounded_sql_batches(db):
    rows = []
    with Session(db) as session:
        for n in range(257):
            code = f"{800000 + n:06d}.SH"
            rows.append({**retired_row(), "ts_code": code})
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
    assert (
        len(queries) == 6
    )  # Three chunks, one indexed date SQL and one factor SQL each.
